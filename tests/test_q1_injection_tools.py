"""Q-1 static injection catalogs, read-only queries and tool-call telemetry."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from biyu.injection_tools import (
    CATALOG_GUIDANCE,
    QueryResult,
    append_tool_call,
    build_character_catalog,
    build_history_catalog,
    build_truth_catalog,
    build_worldbook_catalog,
    query_character,
    query_history,
    query_truth,
    query_worldbook,
    editor_observation_sink,
)
from biyu.editor.tool_observer import ToolObservation


def _book(tmp_path: Path) -> Path:
    book = tmp_path / "book-one"
    (book / "chapters").mkdir(parents=True)
    (book / "truth_files").mkdir()
    (book / "book.json").write_text(
        json.dumps({"id": "book-id", "title": "测试书"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (book / "characters.yaml").write_text(
        yaml.safe_dump(
            {
                "characters": [
                    {
                        "name": "林舟",
                        "tier": "protagonist",
                        "role": "失忆的调查员",
                        "background": "完整背景原文，不得截断。",
                    },
                    {
                        "name": "苏禾",
                        "tier": "supporting",
                        "brief": "负责联络的旧友",
                        "background": "另一张完整人物卡。",
                    },
                ]
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (book / "worldbook.yaml").write_text(
        yaml.safe_dump(
            {
                "narrative_anchors": {"tone": "冷峻悬疑"},
                "facts": ["钟楼只能在午夜开启"],
                "power_system": {"rules": ["记忆不可凭空恢复"]},
                "forbidden": [],
                "geography": ["北岸旧城有钟楼"],
                "factions": [],
                "timeline": ["第一夜：停电"],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (book / "truth_files" / "current_state.md").write_text(
        "林舟正在北岸旧城。", encoding="utf-8"
    )
    (book / "truth_files" / "particle_ledger.md").write_text("", encoding="utf-8")
    (book / "chapters" / "ch1.md").write_text(
        "钟楼下发生了很长的一段往事，全文结果不得被查询层截断。", encoding="utf-8"
    )
    return book


def test_catalogs_are_static_complete_and_carry_lookup_guidance(tmp_path: Path) -> None:
    book = _book(tmp_path)

    character_catalog = build_character_catalog(book)
    assert "林舟 · protagonist · 失忆的调查员" in character_catalog
    assert "苏禾 · supporting · 负责联络的旧友" in character_catalog
    assert CATALOG_GUIDANCE in character_catalog

    worldbook_catalog = build_worldbook_catalog(book)
    for title in (
        "创作锚点",
        "不可变硬设定",
        "力量·修炼体系",
        "绝对禁止",
        "地理",
        "势力",
        "时间线锚点",
    ):
        assert title in worldbook_catalog
    assert "绝对禁止 · 空" in worldbook_catalog
    assert "势力 · 空" in worldbook_catalog
    assert CATALOG_GUIDANCE in worldbook_catalog

    truth_catalog = build_truth_catalog(book)
    assert "current_state.md" in truth_catalog
    assert "particle_ledger.md" not in truth_catalog
    assert CATALOG_GUIDANCE in truth_catalog

    history_catalog = build_history_catalog(book)
    assert "第 1 章" in history_catalog
    assert "全文结果不得被查询层截断" not in history_catalog
    assert CATALOG_GUIDANCE in history_catalog


def test_queries_report_hit_count_and_never_truncate_content(tmp_path: Path) -> None:
    book = _book(tmp_path)

    character = query_character(book, "林舟")
    assert character.hit is True
    assert character.return_count == 1
    assert "完整背景原文，不得截断" in character.content

    setting = query_worldbook(book, "钟楼")
    assert setting.hit is True
    assert setting.return_count == 2
    assert "钟楼只能在午夜开启" in setting.content
    assert "北岸旧城有钟楼" in setting.content

    history = query_history(book, "钟楼")
    assert history.hit is True
    assert history.return_count == 1
    assert "全文结果不得被查询层截断" in history.content

    natural_chapter = query_history(book, "第 1 章")
    assert natural_chapter.hit is True
    assert "全文结果不得被查询层截断" in natural_chapter.content

    truth = query_truth(book, "林舟")
    assert truth.hit is True
    assert truth.return_count == 1
    assert "林舟正在北岸旧城" in truth.content

    miss = query_character(book, "不存在")
    assert miss == QueryResult(content="", hit=False, return_count=0)


def test_tool_call_jsonl_logs_hit_and_miss_with_role_scoped_sequence(tmp_path: Path) -> None:
    book = _book(tmp_path)

    first = append_tool_call(
        book,
        role="writer",
        chapter=2,
        item="character",
        query="林舟",
        result=QueryResult("card", True, 1),
        tokens=31,
        cost=0.002,
        prompt_tokens=20,
        completion_tokens=11,
        response_group="writer:response:1",
        response_tool_call_count=2,
    )
    second = append_tool_call(
        book,
        role="writer",
        chapter=2,
        item="character",
        query="不存在",
        result=QueryResult("", False, 0),
        tokens=7,
        cost=0.0004,
        response_group="writer:response:2",
    )
    other_role = append_tool_call(
        book,
        role="editor",
        chapter=2,
        item="history",
        query="钟楼",
        result=QueryResult("chapter", True, 1),
        tokens=11,
        cost=0.0008,
    )

    assert first["query_index"] == 1
    assert second["query_index"] == 2
    assert other_role["query_index"] == 1

    rows = [
        json.loads(line)
        for line in (book / "logs" / "tool_calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows == [first, second, other_role]
    assert rows[0] == {
        "role": "writer",
        "book": "book-id",
        "chapter": 2,
        "item": "character",
        "query": "林舟",
        "hit": True,
        "return_count": 1,
        "tokens": 31,
        "cost": 0.002,
        "query_index": 1,
        "prompt_tokens": 20,
        "completion_tokens": 11,
        "response_group": "writer:response:1",
        "response_tool_call_count": 2,
        "usage_scope": "triggering_response_shared",
    }
    assert rows[1]["hit"] is False
    assert rows[1]["return_count"] == 0


def test_editor_observation_maps_shared_usage_without_fabricating_local_cost(tmp_path: Path) -> None:
    book = _book(tmp_path)
    sink = editor_observation_sink(book, chapter=3)
    sink(ToolObservation(
        response_group="single:1", tool_name="look_up_character", query="林舟",
        result="{'name': '林舟'}", matched=True, query_index=1, response_round=1,
        response_prompt_tokens=90, response_completion_tokens=10,
        response_total_tokens=100, response_cost=0.003,
        response_tool_call_count=2,
    ))
    row = json.loads((book / "logs" / "tool_calls.jsonl").read_text(encoding="utf-8"))
    assert row["role"] == "editor"
    assert row["return_count"] == 1
    assert row["response_group"] == "editor:single:1"
    assert row["usage_scope"] == "triggering_response_shared"
