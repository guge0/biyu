"""2026-10 篇幅三档(老板裁定):档位即本章下限,只设下限不设上限。

覆盖三层:
- layer3 模板按档位渲染(2000/3000/4000)
- write 命令 --min-words 透传到 pipeline 的 min_words_override
- 越界值被拒绝(300-20000 防手滑)
"""
from __future__ import annotations

import pytest

from biyu.prompts.chapter_writer import build_layer3_constraints


@pytest.mark.parametrize("tier", [2000, 3000, 4000])
def test_layer3_renders_each_tier_as_floor(tier: int) -> None:
    result = build_layer3_constraints(min_words=tier)
    assert f"本章至少 {tier} 中文字符" in result
    assert "上不设限" in result


def test_write_cmd_forwards_min_words_to_pipeline(tmp_path, monkeypatch) -> None:
    """--min-words 只影响当次调用,原样到达 generate_chapter。"""
    captured: dict = {}

    class _FakeResult:
        word_count = 100
        cost_cny = 0.0
        latency_seconds = 0.0
        stage_latencies: dict = {}
        warnings: list = []

    import biyu.pipeline as pipeline_mod
    import biyu.config as config_mod

    async def _fake_generate(book_dir, chapter_num, **kwargs):
        captured.update(kwargs)
        return _FakeResult()

    monkeypatch.setattr(pipeline_mod, "generate_chapter", _fake_generate)
    (tmp_path / "book.json").write_text('{"title":"篇幅档位测试","genre":"xuanhuan"}', encoding="utf-8")
    monkeypatch.setattr(config_mod, "resolve_book_dir", lambda book: tmp_path)

    from biyu.cli.write_cmd import write_command

    write_command(chapter=1, book=None, min_words=4000)
    assert captured["min_words_override"] == 4000


def test_write_cmd_rejects_out_of_range_min_words(tmp_path, monkeypatch, capsys) -> None:
    import biyu.pipeline as pipeline_mod
    import biyu.config as config_mod

    monkeypatch.setattr(
        pipeline_mod,
        "generate_chapter",
        lambda *a, **k: pytest.fail("越界值不应触发生成"),
    )
    monkeypatch.setattr(config_mod, "resolve_book_dir", lambda book: tmp_path)

    from biyu.cli.write_cmd import write_command

    import typer

    with pytest.raises(typer.Exit):
        write_command(chapter=1, book=None, min_words=50)
    assert "300-20000" in capsys.readouterr().out


def test_workbench_write_registry_argv_unchanged() -> None:
    """三档经 actions/write 的 extra 透传,argv 注册表本身不变。"""
    from biyu.ui.action_registry import action_for

    argv = action_for("write", book="书", chapter=1).argv
    assert "--force-pending" in argv
    assert "--min-words" not in argv


def test_executor_forwards_min_words_flag(tmp_path, monkeypatch) -> None:
    """2026-10 事故回归:前端键名必须是 min-words(执行器按连字符取),argv 要带上档位。"""
    import asyncio

    import biyu.ui.cli_executor as ex

    book = tmp_path / "Book"
    book.mkdir()
    (book / "book.json").write_text("{}", encoding="utf-8")
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
            "write", book="Book", chapter=1, confirmed=True,
            extra={"min-words": "4000"},
        )]

    events = asyncio.run(run())
    argv = captured["argv"]
    assert "--min-words" in argv and argv[argv.index("--min-words") + 1] == "4000"
    assert events[-1]["type"] == "done"


def test_main_write_cli_accepts_min_words_without_optioninfo_crash(tmp_path) -> None:
    """走真实 CLI 入口(biyu write):--min-words 可解析,失败应是干净的缺细纲错误
    而不是 '<= not supported between int and OptionInfo'。"""
    import os
    import subprocess
    import sys
    from pathlib import Path

    book = tmp_path / "Book"
    book.mkdir()
    (book / "book.json").write_text('{"title":"Book","genre":"dushi"}', encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": "src",
        "BIYU_DATA_ROOT": str(tmp_path),
        "BIYU_DATA_ROOT_SOURCE": "environment",
    }
    result = subprocess.run(
        [sys.executable, "-c", "from biyu.cli.main import app; app()",
         "write", "-c", "1", "-b", "Book", "--force-pending", "--min-words", "3000"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=str(Path(__file__).resolve().parents[1]), timeout=120,
    )
    combined = result.stdout + result.stderr
    assert "OptionInfo" not in combined
    assert result.returncode != 0  # 没有细纲,应干净失败
    assert "Outline not found" in combined or "细纲" in combined
