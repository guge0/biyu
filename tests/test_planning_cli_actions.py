from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from typer.testing import CliRunner

from biyu.cli.main import app


runner = CliRunner()


def test_r3_actions_are_registered_as_cli_commands() -> None:
    for command in ("planning", "verdict", "talk", "workbench"):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0, result.output


def test_planning_approve_changes_only_status_line(tmp_path: Path, monkeypatch) -> None:
    from biyu.cli import planning_cmd

    planning = tmp_path / "logs" / "ch1" / "planning.md"
    planning.parent.mkdir(parents=True)
    body = "status: 待批\n\n老板红笔正文\n"
    planning.write_text(body, encoding="utf-8")
    monkeypatch.setattr(planning_cmd, "resolve_book_dir", lambda _book: tmp_path)

    planning_cmd.set_planning_status(chapter=1, book="测试书", revoke=False)

    assert planning.read_text(encoding="utf-8") == "status: 已批\n\n老板红笔正文\n"


def test_planning_approve_is_idempotent_and_revoke_restores_pending(tmp_path: Path, monkeypatch) -> None:
    from biyu.cli import planning_cmd

    planning = tmp_path / "logs" / "ch2" / "planning.md"
    planning.parent.mkdir(parents=True)
    planning.write_text("status: 已批\n正文", encoding="utf-8")
    monkeypatch.setattr(planning_cmd, "resolve_book_dir", lambda _book: tmp_path)

    planning_cmd.set_planning_status(chapter=2, book="测试书", revoke=False)
    assert planning.read_text(encoding="utf-8") == "status: 已批\n正文"
    planning_cmd.set_planning_status(chapter=2, book="测试书", revoke=True)
    assert planning.read_text(encoding="utf-8") == "status: 待批\n正文"


def test_verdict_add_writes_three_file_contract(tmp_path: Path, monkeypatch) -> None:
    import json
    from biyu.cli import verdict_cmd

    monkeypatch.setattr(verdict_cmd, "resolve_book_dir", lambda _book: tmp_path)
    negative = tmp_path / "样本库" / "负例候选.md"
    negative.parent.mkdir(parents=True)
    negative.write_text("存量负例\n", encoding="utf-8")
    before = (negative.read_bytes(), negative.stat().st_mtime_ns)
    verdict_cmd.add_verdict(
        chapter=3,
        book="测试书",
        verdict="这里节奏很稳",
        positive="这一段转折",
        negative="不要复用这句式",
    )

    assert "ch3" in (tmp_path / "判词" / "ch3.md").read_text(encoding="utf-8")
    assert "这一段转折" in (tmp_path / "样本库" / "正例候选.md").read_text(encoding="utf-8")
    assert (negative.read_bytes(), negative.stat().st_mtime_ns) == before
    ledger = json.loads((tmp_path / "反馈账.jsonl").read_text(encoding="utf-8"))
    assert ledger["scope"] == "chapter" and ledger["verdict"] == "不要复用这句式"
    assert ledger["action"] == "note_problem"
    assert "anchor" not in ledger and "text" not in ledger
    from biyu.cli import workbench_cmd
    monkeypatch.setattr(workbench_cmd, "resolve_book_dir", lambda _book: tmp_path)
    workbench_cmd.excerpt(
        chapter=3, book="测试书", kind="problem", content="不要复用这句式",
        version="candidate-sha", anchor=4,
    )
    assert (negative.read_bytes(), negative.stat().st_mtime_ns) == before
    ledger = [
        json.loads(line)
        for line in (tmp_path / "反馈账.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert ledger[-1]["scope"] == "sentence" and ledger[-1]["text"] == "不要复用这句式"
    assert ledger[-1]["action"] == "note_problem"
    assert ledger[-1]["chapter"] == 3 and ledger[-1]["candidate_sha"] == "candidate-sha" and ledger[-1]["anchor"] == 4


def test_talk_starts_interactive_creative_session_without_print_flag(monkeypatch) -> None:
    from biyu.cli import talk_cmd

    calls: list[tuple[list[str], dict]] = []
    registry = Path.cwd() / "tests" / ".tmp-director-sessions.json"
    monkeypatch.setattr(talk_cmd, "_bookroom_bat", lambda: Path("书房.bat"))
    monkeypatch.setattr(talk_cmd, "_registry_path", lambda _book: registry)
    monkeypatch.setattr(talk_cmd, "resolve_book_dir", lambda _book: Path(r"C:\\BiyuData\\测试书"))
    monkeypatch.setattr(talk_cmd.subprocess, "Popen", lambda args, **kwargs: calls.append((args, kwargs)))
    try:
        talk_cmd.open_talk(role="章节导演", book="测试书", chapter=1)
        talk_cmd.open_talk(role="章节导演", book="测试书", chapter=1)

        first, second = calls
        assert "--session-id" in first[0]
        assert "--resume" in second[0]
        assert "《测试书》" in first[0][-1] and "第1章" in first[0][-1]
        assert r"C:\BiyuData\测试书" in first[0][-1]
        assert "-p" not in first[0]
        assert first[1]["env"]["BIYU_TRACK"] == "creative"
        assert first[1]["creationflags"] == getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    finally:
        registry.unlink(missing_ok=True)


def test_total_director_uses_one_book_level_session_and_selective_craft(monkeypatch, tmp_path: Path) -> None:
    from biyu.cli import talk_cmd

    calls: list[tuple[list[str], dict]] = []
    registry = tmp_path / "total-director.json"
    monkeypatch.setattr(talk_cmd, "_bookroom_bat", lambda: Path("书房.bat"))
    monkeypatch.setattr(talk_cmd, "_registry_path", lambda _book, role="章节导演": registry)
    monkeypatch.setattr(talk_cmd, "resolve_book_dir", lambda _book: tmp_path / "测试书")
    monkeypatch.setattr(talk_cmd.subprocess, "Popen", lambda args, **kwargs: calls.append((args, kwargs)))

    talk_cmd.open_talk(role="总导演", book="测试书", chapter=None)
    talk_cmd.open_talk(role="总导演", book="测试书", chapter=None)

    assert "--session-id" in calls[0][0]
    assert "--resume" in calls[1][0]
    greeting = calls[0][0][-1]
    assert "北极星" in greeting and "全书方向" in greeting
    assert "网文Craft蒸馏_v0.md" in greeting and "按问题选读" in greeting
    assert "不直接写章节正文" in greeting


def test_total_director_start_failure_is_not_reported_as_success(monkeypatch, tmp_path: Path) -> None:
    from biyu.cli import talk_cmd

    monkeypatch.setattr(talk_cmd, "_bookroom_bat", lambda: Path("书房.bat"))
    monkeypatch.setattr(talk_cmd, "_registry_path", lambda _book, role="章节导演": tmp_path / "director.json")
    monkeypatch.setattr(talk_cmd, "resolve_book_dir", lambda _book: tmp_path / "测试书")
    monkeypatch.setattr(talk_cmd.subprocess, "Popen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("无法创建窗口")))

    with pytest.raises(OSError, match="无法创建窗口"):
        talk_cmd.open_talk(role="总导演", book="测试书", chapter=None)
    assert not (tmp_path / "director.json").exists()


def test_bookroom_launcher_keeps_an_interactive_session_after_the_greeting() -> None:
    text = Path("书房.bat").read_text(encoding="utf-8")

    assert "--dangerously-skip-permissions" in text
    assert "call \"%CLAUDE_CMD%\" --dangerously-skip-permissions %*" in text
