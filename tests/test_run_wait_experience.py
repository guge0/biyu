"""2026-10 等待体验:刷新恢复后能看到真实阶段与不重置的计时。

- 执行器以 -u 起子进程(stdout 无缓冲,阶段提示实时到页面)
- 快照带 run_info(started_at/log_path),前端计时用服务端起点
- run-log 接口返回日志尾段+总数;run_id 白名单校验
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


def _make_book(tmp_path: Path) -> Path:
    book = tmp_path / "Book"
    book.mkdir()
    (book / "book.json").write_text('{"title":"Book","genre":"dushi"}', encoding="utf-8")
    return book


def test_executor_launches_python_unbuffered(tmp_path, monkeypatch) -> None:
    """阶段提示要实时到页面:子进程必须带 -u(无缓冲)。"""
    import biyu.ui.cli_executor as ex

    book = _make_book(tmp_path)
    captured: dict = {}

    class FakeProcess:
        stdout = asyncio.StreamReader()
        stdin = None

        def __init__(self) -> None:
            self.stdout.feed_eof()

        async def wait(self) -> int:
            return 0

    async def fake_create(*args, **kwargs):
        captured["argv"] = list(args)
        return FakeProcess()

    monkeypatch.setattr(ex, "resolve_book_dir", lambda _book: book)
    monkeypatch.setattr(ex.asyncio, "create_subprocess_exec", fake_create)

    async def run() -> list:
        return [event async for event in ex.execute(
            "write", book="Book", chapter=1, confirmed=True, extra={},
        )]

    asyncio.run(run())
    argv = [str(a) for a in captured["argv"]]
    assert "-u" in argv
    assert argv.index("-u") == argv.index(str(argv[0])) + 1  # 紧跟解释器


def test_snapshot_carries_run_info_with_server_start(tmp_path, monkeypatch) -> None:
    """恢复态计时要用服务端起点:快照暴露 run_info.started_at。"""
    import biyu.ui.cli_executor as ex
    from biyu.ui import workbench

    book = _make_book(tmp_path)
    (book / "outlines").mkdir()
    (book / "logs" / "ch1").mkdir(parents=True)
    monkeypatch.setattr(workbench, "_book_dir", lambda _b: book)
    monkeypatch.setattr(
        ex, "running_run",
        lambda book, chapter: {
            "action": "write", "run_id": "20261012T164145_e8627760",
            "log_path": "logs/ch1/runs/x.log",
            "started_at": "2026-10-12T16:41:45.350360+00:00",
        },
    )
    snapshot = workbench.chapter_snapshot(book, 1)
    assert snapshot["run_info"]["started_at"].endswith("+00:00")
    assert snapshot["run_info"]["action"] == "write"


def test_run_log_endpoint_returns_tail_and_rejects_bad_id(tmp_path, monkeypatch) -> None:
    from fastapi import HTTPException

    from biyu.ui.workbench import chapter_run_log

    book = _make_book(tmp_path)
    runs = book / "logs" / "ch1" / "runs"
    runs.mkdir(parents=True)
    (runs / "20261012T164145_e8627760.log").write_text(
        "run_id=20261012T164145_e8627760\naction=write\nstarted_at=2026-10-12T16:41:45+00:00\nstatus=running\n---\n"
        "argv=write -c 1\n开始生成第 1 章\n  [1/4] OK - 49.4s\n  [2/4] Writer ...\n",
        encoding="utf-8",
    )
    from biyu.ui import workbench

    monkeypatch.setattr(workbench, "_book_dir", lambda _b: book)
    monkeypatch.setattr(
        "biyu.ui.cli_executor.running_run", lambda book, chapter: None
    )

    data = chapter_run_log("Book", 1)
    # 无 _RUNNING(服务重启后):日志未完结也不算"当前运行",只供阶段回放
    assert data["running"] is False
    assert data["started_at"] == "2026-10-12T16:41:45+00:00"
    assert data["total"] == 5  # argv 行 + --- 分隔 + 3 条阶段/正文行
    assert any("[2/4]" in line for line in data["lines"])

    with pytest.raises(HTTPException) as exc_info:
        chapter_run_log("Book", 1, run_id="../../etc")
    assert exc_info.value.status_code == 400


# ---------- S-3B 缺陷0:run 完成后无条件清 _RUNNING ----------

def test_running_read_path_self_heals_after_process_exit() -> None:
    """读路径自愈:_RUNNING 条目里的进程已退出时,running_* 立即视为不在运行。"""
    import biyu.ui.cli_executor as ex

    class ExitedProc:
        returncode = 0

    class LiveProc:
        returncode = None

    try:
        ex._RUNNING[("Book", 7)] = {"action": "write", "process": ExitedProc()}
        assert ex.running_action("Book", 7) is None
        assert ("Book", 7) not in ex._RUNNING
        assert ex.running_run("Book", 7) is None

        ex._RUNNING[("Book", 8)] = {"action": "adopt", "process": LiveProc()}
        assert ex.running_action("Book", 8) == "adopt"
        assert ex.running_run("Book", 8)["action"] == "adopt"

        # 旧式条目可能没有 process 键,宽容处理
        ex._RUNNING[("Book", 9)] = {"action": "write"}
        assert ex.running_action("Book", 9) == "write"
    finally:
        for key in (("Book", 7), ("Book", 8), ("Book", 9)):
            ex._RUNNING.pop(key, None)


def test_run_completion_clears_running_even_when_consumer_gone(tmp_path, monkeypatch) -> None:
    """SSE 消费端断开(刷新页面)后,run 完成必须无条件清 _RUNNING,章动作恢复可用。

    模拟方式:消费端拿到 started 事件后放弃消费(生成器不关闭、finally 不执行),
    子进程真实退出;看门狗必须替它收尸。
    """
    import sys as _sys

    import biyu.ui.cli_executor as ex
    from biyu.ui.action_registry import Action

    book = _make_book(tmp_path)
    monkeypatch.setattr(ex, "resolve_book_dir", lambda _book: book)
    monkeypatch.setattr(
        ex, "action_for",
        lambda action_id, *, book, chapter: Action(argv=(), confirm=False, estimate="¥0"),
    )
    captured: dict = {}
    real_create = asyncio.create_subprocess_exec

    async def fake_create(*args, **kwargs):
        # 忽略业务 argv,起一个真实、打印一行、存活片刻后退出的子进程
        proc = await real_create(
            _sys.executable, "-u", "-c",
            "print('阶段提示'); import sys, time; sys.stdout.flush(); time.sleep(0.3)",
            stdin=kwargs.get("stdin"), stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"), env=kwargs.get("env"),
        )
        captured["proc"] = proc
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)

    async def scenario() -> None:
        ex._RUNNING.pop(("Book", 1), None)
        gen = ex.execute("write", book="Book", chapter=1, confirmed=True, extra={})
        try:
            event = await gen.__anext__()
            assert event["type"] == "started"
            assert ex.running_action("Book", 1) == "write"  # 运行中照常可见
            # 消费端就此消失:不 aclose,不取消——生成器挂在 yield 上
            proc = captured["proc"]
            await proc.wait()  # 子进程退出(run 已成功)
            for _ in range(100):
                if ("Book", 1) not in ex._RUNNING:
                    break
                await asyncio.sleep(0.05)
            assert ("Book", 1) not in ex._RUNNING, "子进程退出后 _RUNNING 必须被无条件清除"
            assert ex.running_action("Book", 1) is None
            assert ex.running_run("Book", 1) is None
        finally:
            await gen.aclose()  # 清理生成器;finally 再 pop 是空操作
            ex._RUNNING.pop(("Book", 1), None)

    asyncio.run(scenario())
