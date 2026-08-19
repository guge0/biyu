from __future__ import annotations

import json
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from biyu.call_evidence import record_call_evidence
from biyu.editor.editor import review_chapter
from biyu.editor.multi_agent import _run_agent_phase2
from biyu.editor.schema import AgentIssueList
from biyu.pipeline import _run_q1_tool_loop


def _response() -> SimpleNamespace:
    return SimpleNamespace(
        text="绝密完整输出",
        prompt_tokens=123,
        completion_tokens=45,
        total_tokens=168,
        cost=0.0123,
        finish_reason="stop",
        raw={"api_key": "sk-RAW-MUST-NOT-LEAK"},
    )


def test_call_evidence_writes_only_safe_summary(monkeypatch, tmp_path: Path) -> None:
    evidence_dir = tmp_path / "outside-evidence"
    monkeypatch.setenv("BIYU_CALL_EVIDENCE_DIR", str(evidence_dir))
    messages = [
        {"role": "system", "content": "sk-SYSTEM-MUST-NOT-LEAK"},
        {"role": "user", "content": "完整提示词-MUST-NOT-LEAK"},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "look_up_character", "arguments": "SECRET-ARGS"}}]},
        {"role": "tool", "content": "SECRET-TOOL-RESULT"},
    ]

    path = record_call_evidence(
        role="writer", chapter_num=9, round_num=2, messages=messages,
        response=_response(), final_round=True,
    )

    assert path is not None
    raw_text = path.read_text(encoding="utf-8")
    for secret in (
        "sk-SYSTEM-MUST-NOT-LEAK", "完整提示词-MUST-NOT-LEAK",
        "SECRET-ARGS", "SECRET-TOOL-RESULT", "绝密完整输出",
        "sk-RAW-MUST-NOT-LEAK", str(evidence_dir),
    ):
        assert secret not in raw_text
    row = json.loads(raw_text)
    assert row["role"] == "writer"
    assert row["chapter"] == 9 and row["round"] == 2 and row["final_round"] is True
    assert row["messages"] == [
        {"role": "system", "content_length": len("sk-SYSTEM-MUST-NOT-LEAK"), "tool_call_count": 0},
        {"role": "user", "content_length": len("完整提示词-MUST-NOT-LEAK"), "tool_call_count": 0},
        {"role": "assistant", "content_length": 0, "tool_call_count": 1},
        {"role": "tool", "content_length": len("SECRET-TOOL-RESULT"), "tool_call_count": 0},
    ]
    assert row["finish_reason"] == "stop"
    assert row["usage"] == {
        "prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168,
    }
    assert row["response"] == {"text_length": 6, "tool_call_count": 0}


def test_call_evidence_is_noop_without_explicit_directory(monkeypatch) -> None:
    monkeypatch.delenv("BIYU_CALL_EVIDENCE_DIR", raising=False)
    assert record_call_evidence(
        role="architect", chapter_num=1, round_num=1,
        messages=[{"role": "user", "content": "prompt"}],
        response=_response(), final_round=False,
    ) is None


def test_call_evidence_rejects_repository_directory(monkeypatch) -> None:
    monkeypatch.setenv("BIYU_CALL_EVIDENCE_DIR", str(Path.cwd() / "scratch" / "forbidden-evidence"))
    try:
        record_call_evidence(
            role="writer", chapter_num=1, round_num=1,
            messages=[{"role": "user", "content": "prompt"}],
            response=_response(), final_round=False,
        )
    except ValueError as exc:
        assert "仓库之外" in str(exc)
    else:
        raise AssertionError("仓内证据目录必须被拒绝")


def test_multi_agent_editor_phase2_records_when_injection_enabled(monkeypatch, tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    monkeypatch.setenv("BIYU_CALL_EVIDENCE_DIR", str(evidence_dir))
    response = _response()
    response.raw = {"choices": [{"message": {"content": "", "tool_calls": []}}]}
    adapter = MagicMock()
    adapter.generate = AsyncMock(return_value=response)

    asyncio.run(_run_agent_phase2(
        agent_id="A", chapter_num=9, adapter=adapter,
        own_v1=AgentIssueList(agent="A", phase=1, chapter=9),
        peer_v1s=[AgentIssueList(agent="B", phase=1, chapter=9)],
        config={}, injection_v2=True,
    ))

    rows = [json.loads(line) for line in (evidence_dir / "call_evidence.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["role"] == "editor"
    assert rows[0]["round"] == 1 and rows[0]["final_round"] is True


def test_single_editor_disabled_writes_no_evidence(monkeypatch, tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    monkeypatch.setenv("BIYU_CALL_EVIDENCE_DIR", str(evidence_dir))
    response = _response()
    response.raw = {"choices": [{"message": {"content": "", "tool_calls": []}}]}
    adapter = MagicMock()
    adapter.generate = AsyncMock(return_value=response)

    asyncio.run(review_chapter(1, "候选正文", tmp_path, adapter, injection_v2=False))

    assert not evidence_dir.exists()


def test_q1_loop_records_architect_and_writer_responses(monkeypatch, tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    monkeypatch.setenv("BIYU_CALL_EVIDENCE_DIR", str(evidence_dir))

    async def run(role: str, text: str) -> None:
        adapter = MagicMock()
        adapter.supports_tools = True
        adapter.max_tokens = 100
        adapter.generate = AsyncMock(return_value=SimpleNamespace(
            text=text, prompt_tokens=10, completion_tokens=2, total_tokens=12,
            cost=0.001, finish_reason="stop", degraded=False,
            raw={"choices": [{"message": {"content": text, "tool_calls": []}}]},
        ))
        await _run_q1_tool_loop(
            adapter=adapter, fallback_adapter=None,
            messages=[{"role": "user", "content": "prompt"}],
            book_dir=tmp_path, chapter_num=9, role=role, guarded=False,
            generate_kwargs={},
        )

    asyncio.run(run("architect", "方案"))
    asyncio.run(run("writer", "正文"))

    rows = [json.loads(line) for line in (evidence_dir / "call_evidence.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["role"] for row in rows] == ["architect", "writer"]
