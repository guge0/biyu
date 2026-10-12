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
