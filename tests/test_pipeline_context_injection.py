from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from biyu.pipeline import _q1_worldbook_prompt, _run_q1_tool_loop
from biyu.prompts.chapter_writer import build_layer2_context
from biyu.prompts.v3_opening import build_planning_prompt


FIXED_TAIL_LABEL = "上一章结尾(若本章另起新场景,可不接续)"
FIXED_CATALOG_LABEL = "以下只是清单,要用再查,不必全查"


def test_prompt_builders_keep_q1_labels_behind_switch() -> None:
    old = build_layer2_context("", [], "", "旧尾", "", "方案", "")
    new = build_layer2_context(
        "", [], "", "旧尾", "", "方案", "", injection_v2=True,
        original_outline="原始细纲", character_catalog="-甲", worldbook_catalog="-地理",
        history_catalog="-第1章",
    )
    assert FIXED_TAIL_LABEL not in old
    assert FIXED_CATALOG_LABEL not in old
    assert FIXED_TAIL_LABEL in new
    assert FIXED_CATALOG_LABEL in new
    assert "原始细纲" in new and "方案" in new

    architect = build_planning_prompt(
        "细纲", prev_tail="旧尾", character_catalog="-甲",
        worldbook_catalog="-地理", injection_v2=True,
    )
    assert FIXED_TAIL_LABEL in architect
    assert FIXED_CATALOG_LABEL in architect


def test_q1_worldbook_preload_excludes_power_and_catalog_fields() -> None:
    prompt = _q1_worldbook_prompt({
        "narrative_anchors": {"tone": "冷"}, "facts": ["硬"], "forbidden": ["禁"],
        "power_system": {"rules": ["力量"]}, "geography": ["地理"],
    })
    assert "创作锚点" in prompt and "不可变硬设定" in prompt and "绝对禁止" in prompt
    assert "力量" not in prompt and "地理" not in prompt


class _FakeAdapter:
    supports_tools = True
    max_tokens = 100

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def generate(self, messages, **kwargs):
        self.calls.append((list(messages), dict(kwargs)))
        return self.responses.pop(0)


def _response(*, calls=None, text="", cost=0.1, tokens=10):
    return SimpleNamespace(
        text=text, cost=cost, prompt_tokens=tokens - 1, completion_tokens=1,
        total_tokens=tokens, degraded=False, finish_reason="tool_calls" if calls else "stop",
        raw={"choices": [{"message": {"content": text, "tool_calls": calls or []}}]},
    )


@pytest.mark.asyncio
async def test_tool_loop_records_hit_and_miss_with_shared_response_usage(tmp_path: Path) -> None:
    (tmp_path / "characters.yaml").write_text(
        "characters:\n  - name: 甲\n    tier: protagonist\n", encoding="utf-8",
    )
    calls = [
        {"id": "1", "function": {"name": "look_up_character", "arguments": json.dumps({"query": "甲"}, ensure_ascii=False)}},
        {"id": "2", "function": {"name": "look_up_character", "arguments": json.dumps({"query": "乙"}, ensure_ascii=False)}},
    ]
    adapter = _FakeAdapter([_response(calls=calls, cost=0.2, tokens=20), _response(text="正文", cost=0.3, tokens=30)])
    result = await _run_q1_tool_loop(
        adapter=adapter, fallback_adapter=None, messages=[{"role": "user", "content": "x"}],
        book_dir=tmp_path, chapter_num=2, role="writer", guarded=False, generate_kwargs={},
    )
    rows = [json.loads(line) for line in (tmp_path / "logs/tool_calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["hit"] for row in rows] == [True, False]
    assert {row["response_group"] for row in rows} == {"writer:1"}
    assert all(row["response_tool_call_count"] == 2 for row in rows)
    assert result.cost == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_tool_loop_stops_on_cost_gate_and_logs_spend(tmp_path: Path) -> None:
    adapter = _FakeAdapter([_response(text="不会交付", cost=0.61, tokens=30)])
    with pytest.raises(RuntimeError, match="超过 ¥0.60"):
        await _run_q1_tool_loop(
            adapter=adapter, fallback_adapter=None,
            messages=[{"role": "user", "content": "x"}], book_dir=tmp_path,
            chapter_num=3, role="writer", guarded=False, generate_kwargs={},
        )
    cost_log = (tmp_path / "logs/cost_log.csv").read_text(encoding="utf-8")
    assert "writer" in cost_log and "cost_stop" in cost_log and "0.6100" in cost_log


@pytest.mark.asyncio
async def test_writer_empty_final_response_is_billed_and_stopped(tmp_path: Path) -> None:
    adapter = _FakeAdapter([_response(text="", cost=0.12, tokens=30)])
    with pytest.raises(RuntimeError, match="空内容"):
        await _run_q1_tool_loop(
            adapter=adapter, fallback_adapter=None,
            messages=[{"role": "user", "content": "x"}], book_dir=tmp_path,
            chapter_num=4, role="writer", guarded=False, generate_kwargs={},
        )
    cost_log = (tmp_path / "logs/cost_log.csv").read_text(encoding="utf-8")
    assert "writer,0.1200" in cost_log and "empty" in cost_log


@pytest.mark.asyncio
async def test_writer_gets_five_lookup_rounds_then_one_tool_free_final_round(tmp_path: Path) -> None:
    calls = [
        {"id": str(index), "function": {
            "name": "look_up_character",
            "arguments": json.dumps({"query": f"甲{index}"}, ensure_ascii=False),
        }}
        for index in range(1, 6)
    ]
    adapter = _FakeAdapter([
        *[_response(calls=[call], cost=0.01, tokens=10) for call in calls],
        _response(text="最终正文", cost=0.02, tokens=20),
    ])

    result = await _run_q1_tool_loop(
        adapter=adapter, fallback_adapter=None,
        messages=[{"role": "user", "content": "原始写作任务"}], book_dir=tmp_path,
        chapter_num=9, role="writer", guarded=False,
        generate_kwargs={"max_tokens": 16384},
    )

    assert result.text == "最终正文"
    assert len(adapter.calls) == 6
    assert all("tools" in kwargs for _, kwargs in adapter.calls[:5])
    final_messages, final_kwargs = adapter.calls[5]
    assert "tools" not in final_kwargs and "tool_choice" not in final_kwargs
    assert final_kwargs["max_tokens"] == 16384
    assert final_messages[-1]["role"] == "user"
    assert "最后一轮" in final_messages[-1]["content"]
    assert "正文" in final_messages[-1]["content"]


@pytest.mark.asyncio
async def test_writer_final_round_tool_calls_are_empty_failure_and_not_executed(tmp_path: Path) -> None:
    lookup = {"id": "lookup", "function": {
        "name": "look_up_character", "arguments": json.dumps({"query": "甲"}, ensure_ascii=False),
    }}
    forbidden_final = {"id": "forbidden", "function": {
        "name": "look_up_character", "arguments": json.dumps({"query": "不应执行"}, ensure_ascii=False),
    }}
    adapter = _FakeAdapter([
        *[_response(calls=[{**lookup, "id": str(index)}], cost=0.01) for index in range(5)],
        _response(calls=[forbidden_final], cost=0.02),
    ])

    with pytest.raises(RuntimeError, match="空内容"):
        await _run_q1_tool_loop(
            adapter=adapter, fallback_adapter=None,
            messages=[{"role": "user", "content": "x"}], book_dir=tmp_path,
            chapter_num=9, role="writer", guarded=False, generate_kwargs={},
        )

    rows = (tmp_path / "logs/tool_calls.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 5
    assert all("不应执行" not in row for row in rows)
    cost_log = (tmp_path / "logs/cost_log.csv").read_text(encoding="utf-8")
    assert "writer,0.0700" in cost_log and "empty" in cost_log


@pytest.mark.asyncio
async def test_writer_blank_final_round_is_billed_as_empty(tmp_path: Path) -> None:
    call = {"id": "lookup", "function": {
        "name": "look_up_character", "arguments": json.dumps({"query": "甲"}, ensure_ascii=False),
    }}
    adapter = _FakeAdapter([
        *[_response(calls=[{**call, "id": str(index)}], cost=0.01) for index in range(5)],
        _response(text="   ", cost=0.02),
    ])

    with pytest.raises(RuntimeError, match="收尾轮返回了空内容"):
        await _run_q1_tool_loop(
            adapter=adapter, fallback_adapter=None,
            messages=[{"role": "user", "content": "x"}], book_dir=tmp_path,
            chapter_num=9, role="writer", guarded=False, generate_kwargs={},
        )

    cost_log = (tmp_path / "logs/cost_log.csv").read_text(encoding="utf-8")
    assert "writer,0.0700" in cost_log and "empty" in cost_log


@pytest.mark.asyncio
async def test_architect_keeps_unbounded_tool_loop(tmp_path: Path) -> None:
    call = {"id": "lookup", "function": {
        "name": "look_up_character", "arguments": json.dumps({"query": "甲"}, ensure_ascii=False),
    }}
    adapter = _FakeAdapter([
        *[_response(calls=[{**call, "id": str(index)}], cost=0.01) for index in range(6)],
        _response(text="方案", cost=0.01),
    ])

    result = await _run_q1_tool_loop(
        adapter=adapter, fallback_adapter=None,
        messages=[{"role": "user", "content": "x"}], book_dir=tmp_path,
        chapter_num=9, role="architect", guarded=False, generate_kwargs={},
    )

    assert result.text == "方案"
    assert len(adapter.calls) == 7
    assert all("tools" in kwargs for _, kwargs in adapter.calls)
