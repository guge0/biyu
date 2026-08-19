from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from biyu.editor.editor import review_chapter
from biyu.editor.multi_agent import _run_agent_phase1
from biyu.editor.prompts import build_editor_user_prompt


def _response(*, tool_calls: list[dict], cost: float, prompt_tokens: int, completion_tokens: int):
    response = MagicMock()
    response.text = ""
    response.cost = cost
    response.prompt_tokens = prompt_tokens
    response.completion_tokens = completion_tokens
    response.total_tokens = prompt_tokens + completion_tokens
    response.finish_reason = "tool_calls"
    response.reasoning_content = None
    response.raw = {"choices": [{"message": {"content": "", "tool_calls": tool_calls}}]}
    return response


def _call(name: str, arguments: dict, call_id: str = "call_lookup") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


def test_editor_anchor_is_preinjected_while_lookup_catalog_stays_v2_only() -> None:
    baseline = build_editor_user_prompt(4, "候选正文")
    disabled = build_editor_user_prompt(
        4,
        "候选正文",
        injection_v2=False,
        creative_anchor="不能泄露的创作锚点",
    )
    enabled = build_editor_user_prompt(
        4,
        "候选正文",
        injection_v2=True,
        creative_anchor="完整创作锚点",
        lookup_catalog="林舟 · 主角 · 返乡调查者 · 要用再查,不必全查",
        prev_chapter_tail="上一章尾声",
    )

    assert disabled != baseline
    assert "不能泄露的创作锚点" in disabled
    assert "完整创作锚点" in enabled
    assert "创作锚点" in enabled
    assert "上一章结尾(若本章另起新场景,可不接续)" in enabled
    assert "以下只是清单,要用再查,不必全查" in enabled
    assert "林舟 · 主角" in enabled


def test_single_editor_observer_sees_hit_and_miss_with_trigger_response_usage(tmp_path: Path) -> None:
    (tmp_path / "characters.yaml").write_text(
        "characters:\n  - name: 林舟\n    personality: 冷静\n",
        encoding="utf-8",
    )
    first = _response(
        tool_calls=[
            _call("look_up_character", {"char_name": "林舟"}, "hit"),
            _call("look_up_character", {"char_name": "不存在"}, "miss"),
        ],
        cost=0.012,
        prompt_tokens=120,
        completion_tokens=30,
    )
    final = _response(
        tool_calls=[_call("submit_review", {"issues": [], "confidence": "high"}, "done")],
        cost=0.003,
        prompt_tokens=160,
        completion_tokens=20,
    )
    adapter = MagicMock()
    adapter.generate = AsyncMock(side_effect=[first, final])
    seen = []

    asyncio.run(
        review_chapter(
            1,
            "候选正文",
            tmp_path,
            adapter,
            tool_observer=seen.append,
        )
    )

    assert [event.query for event in seen] == ["林舟", "不存在"]
    assert "林舟" in seen[0].result
    assert "未找到角色" in seen[1].result
    assert [event.query_index for event in seen] == [1, 2]
    assert all(event.response_prompt_tokens == 120 for event in seen)
    assert all(event.response_completion_tokens == 30 for event in seen)
    assert all(event.response_total_tokens == 150 for event in seen)
    assert all(event.response_cost == 0.012 for event in seen)
    assert all(event.response_tool_call_count == 2 for event in seen)
    assert all(event.response_group == "single:1" for event in seen)
    assert all(event.usage_scope == "triggering_response_shared" for event in seen)
    assert [event.return_count for event in seen] == [1, 0]


def test_multi_agent_phase1_supports_anchor_and_same_observer_contract(tmp_path: Path) -> None:
    first = _response(
        tool_calls=[_call("look_up_history", {"chapter_or_keyword": "旧事"})],
        cost=0.004,
        prompt_tokens=80,
        completion_tokens=10,
    )
    final = _response(
        tool_calls=[_call("submit_review", {"issues": []}, "done")],
        cost=0.001,
        prompt_tokens=90,
        completion_tokens=10,
    )
    adapter = MagicMock()
    adapter.generate = AsyncMock(side_effect=[first, final])
    seen = []

    asyncio.run(
        _run_agent_phase1(
            "A",
            3,
            "候选正文",
            tmp_path,
            adapter,
            {"agents": {"max_tool_calls_per_agent_phase1": 3, "max_issues_per_agent": 8}},
            "前章末尾",
            injection_v2=True,
            creative_anchor="完整创作锚点",
            lookup_catalog="历史章节目录 · 要用再查,不必全查",
            tool_observer=seen.append,
        )
    )

    first_messages = adapter.generate.call_args_list[0][0][0]
    assert "完整创作锚点" in first_messages[1]["content"]
    assert "上一章结尾(若本章另起新场景,可不接续)" in first_messages[1]["content"]
    assert "以下只是清单,要用再查,不必全查" in first_messages[1]["content"]
    assert len(seen) == 1
    assert seen[0].tool_name == "look_up_history"
    assert seen[0].query == "旧事"
    assert seen[0].response_total_tokens == 90
    assert seen[0].response_cost == 0.004
    assert seen[0].response_group == "agent-A:1"
