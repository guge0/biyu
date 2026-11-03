"""S-4A — 责编助手工具清单(tools.py)单测。

覆盖(工单测试节):
- 工具清单内容与 tier;禁用工具(approve_* 等)不在清单;
- read 工具读得到、截断 ≤4000、书稿类外包防注入声明;
- run 工具只登记不执行;
- 路径穿越书名被拒;
- 坏参数 → 错误文本,不抛异常。

零烧钱,纯本地文件 fixture。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from biyu.agent.confirmations import PendingActionStore
from biyu.agent.tools import (
    FORBIDDEN_TOOL_NAMES,
    MANUSCRIPT_NOTE,
    MAX_RESULT_CHARS,
    ToolInputError,
    build_tool_specs,
    execute_tool,
    openai_tools_payload,
    safe_book_dir,
)

READ_TOOLS = {
    "list_books", "book_overview", "read_chapter", "search_book",
    "chapter_status", "outline_history", "quickcheck_chapter", "quickcheck_text",
}
RUN_TOOLS = {"request_write", "request_rewrite", "request_review", "request_diagnose"}


def make_book(root: Path, name: str = "MyBook") -> Path:
    book = root / name
    (book / "chapters" / "_pending").mkdir(parents=True)
    (book / "outlines").mkdir()
    (book / "truth_files").mkdir()
    (book / "logs").mkdir()
    (book / "book.json").write_text(
        json.dumps({"id": "mb-1", "title": "测试书", "display_name": "测试书"}), encoding="utf-8",
    )
    (book / "chapters" / "ch1.md").write_text("第一章正文。林砚推门进来。", encoding="utf-8")
    (book / "chapters" / "ch2.md").write_text("长" * 6000, encoding="utf-8")
    (book / "chapters" / "_pending" / "ch3.md").write_text(
        "候选稿:林砚不由得叹了口气，仿佛卸下了千斤重担。", encoding="utf-8",
    )
    (book / "outlines" / "ch1.md").write_text("# 第一章细纲\n林砚进城。", encoding="utf-8")
    (book / "truth_files" / "current_state.md").write_text(
        "| 字段 | 值 |\n|------|-----|\n| 当前章节 | 1 |", encoding="utf-8",
    )
    (book / "characters.yaml").write_text(
        "characters:\n  - name: 林砚\n    personality: 冷静\n", encoding="utf-8",
    )
    (book / "worldbook.yaml").write_text(
        "facts:\n  - 青云宗在大陆东境\n", encoding="utf-8",
    )
    return book


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    make_book(tmp_path)
    return tmp_path


def specs_for(data_root: Path, book: str = "MyBook"):
    return {s.name: s for s in build_tool_specs(book=book, data_root=data_root)}


def run(specs: dict, name: str, args: dict):
    return execute_tool(specs[name], args)


# ---------------------------------------------------------------------------
# 清单
# ---------------------------------------------------------------------------


def test_registry_contains_exactly_expected_tools(data_root: Path):
    specs = specs_for(data_root)
    assert set(specs) == READ_TOOLS | RUN_TOOLS
    assert {n for n, s in specs.items() if s.tier == "read"} == READ_TOOLS
    assert {n for n, s in specs.items() if s.tier == "run"} == RUN_TOOLS


def test_forbidden_tools_absent_from_registry(data_root: Path):
    specs = specs_for(data_root)
    assert not (set(specs) & FORBIDDEN_TOOL_NAMES)
    assert "approve_planning" not in specs
    assert "approve_chapter" not in specs
    assert "adopt" not in specs
    # 工具参数里也不该出现任何文件路径字段
    for spec in specs.values():
        assert "path" not in json.dumps(spec.parameters)


def test_openai_payload_shape(data_root: Path):
    payload = openai_tools_payload(list(specs_for(data_root).values()))
    assert all(item["type"] == "function" for item in payload)
    names = {item["function"]["name"] for item in payload}
    assert names == READ_TOOLS | RUN_TOOLS
    assert all(item["function"]["parameters"]["type"] == "object" for item in payload)


# ---------------------------------------------------------------------------
# 路径穿越
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["../evil", "a/b", "a\\b", "..", "", "."])
def test_traversal_book_rejected(data_root: Path, bad: str):
    with pytest.raises(ToolInputError):
        build_tool_specs(book=bad, data_root=data_root)
    with pytest.raises(ToolInputError):
        safe_book_dir(bad, data_root)


# ---------------------------------------------------------------------------
# read 工具
# ---------------------------------------------------------------------------


def test_read_chapter_returns_content_with_manuscript_note(data_root: Path):
    specs = specs_for(data_root)
    outcome = run(specs, "read_chapter", {"chapter": 1})
    assert "林砚推门进来" in outcome.text
    assert outcome.text.startswith(MANUSCRIPT_NOTE)


def test_read_chapter_truncated_to_limit(data_root: Path):
    specs = specs_for(data_root)
    outcome = run(specs, "read_chapter", {"chapter": 2})
    assert len(outcome.text) <= MAX_RESULT_CHARS
    assert outcome.text.endswith("[已截断]")


def test_read_chapter_missing_chapter(data_root: Path):
    specs = specs_for(data_root)
    outcome = run(specs, "read_chapter", {"chapter": 99})
    assert "不存在" in outcome.text


def test_search_book_hits_character_and_setting(data_root: Path):
    specs = specs_for(data_root)
    outcome = run(specs, "search_book", {"keyword": "林砚"})
    assert "林砚" in outcome.text
    assert outcome.text.startswith(MANUSCRIPT_NOTE)
    outcome2 = run(specs, "search_book", {"keyword": "青云宗"})
    assert "青云宗" in outcome2.text


def test_chapter_status_reports_step_and_pending(data_root: Path):
    from biyu.ui.workbench_state import write_workbench_step

    book = data_root / "MyBook"
    write_workbench_step(book, 3, "reading")
    (book / "logs" / "ch3" / "planning.md").write_text(
        "status: 已批\n方案正文", encoding="utf-8",
    )
    specs = specs_for(data_root)
    outcome = run(specs, "chapter_status", {"chapter": 3})
    assert "读稿定夺" in outcome.text
    assert "已批" in outcome.text and "方案已锁定" in outcome.text
    assert "待审稿:有" in outcome.text
    # 非书稿类结果不包防注入声明
    assert not outcome.text.startswith(MANUSCRIPT_NOTE)


def test_book_overview_and_outline_history(data_root: Path):
    specs = specs_for(data_root)
    overview = run(specs, "book_overview", {})
    assert "正式章节 2 章" in overview.text
    assert "待审稿 1 章" in overview.text
    assert "细纲 1 份" in overview.text
    assert "当前章节" in overview.text  # 真相文件摘要拼进来了
    outlines = run(specs, "outline_history", {})
    assert "细纲数: 1" in outlines.text


def test_quickcheck_chapter_prefers_pending(data_root: Path):
    specs = specs_for(data_root)
    outcome = run(specs, "quickcheck_chapter", {"chapter": 3})
    assert "AI 味指数" in outcome.text


def test_quickcheck_text_rejects_oversize(data_root: Path):
    specs = specs_for(data_root)
    outcome = run(specs, "quickcheck_text", {"text": "字" * 200_001})
    assert "上限" in outcome.text


def test_list_books_lists_book_json_dirs(data_root: Path):
    specs = specs_for(data_root)
    outcome = run(specs, "list_books", {})
    assert "MyBook" in outcome.text
    assert "测试书" in outcome.text


# ---------------------------------------------------------------------------
# 坏参数不抛
# ---------------------------------------------------------------------------


def test_bad_arguments_return_error_text_not_exception(data_root: Path):
    specs = specs_for(data_root)
    for args in ({"chapter": "abc"}, {"chapter": 0}, {}):
        outcome = run(specs, "read_chapter", args)
        assert "参数不合法" in outcome.text


# ---------------------------------------------------------------------------
# run 工具:只登记,不执行
# ---------------------------------------------------------------------------


def test_request_write_registers_pending_without_executing(data_root: Path):
    store = PendingActionStore(data_root)
    specs = {s.name: s for s in build_tool_specs(
        book="MyBook", data_root=data_root, session_id="sess-1", store=store,
    )}
    book = data_root / "MyBook"

    def _tree() -> list[str]:
        # 登记只写 consults/ 目录;该目录之外不应有任何变化(没执行任何动作)
        consults = book / "consults"
        return sorted(
            str(p) for p in book.rglob("*")
            if consults not in p.parents and p != consults
        )

    before = _tree()
    outcome = run(specs, "request_write", {"chapter": 4})
    assert "已提交待作者确认" in outcome.text
    assert "预估" in outcome.text
    assert outcome.pending is not None
    assert outcome.pending["action_id"] == "write"
    assert outcome.pending["status"] == "pending"
    assert outcome.pending["session_id"] == "sess-1"
    # 登记落盘
    records = store.list_actions(book="MyBook")
    assert len(records) == 1 and records[0]["chapter"] == 4
    # 没有执行:除登记文件外文件树不变,没有登记运行中的动作
    assert _tree() == before
    from biyu.ui.cli_executor import running_action

    assert running_action("MyBook", 4) is None


def test_all_four_run_tools_register_their_action(data_root: Path):
    store = PendingActionStore(data_root)
    specs = {s.name: s for s in build_tool_specs(
        book="MyBook", data_root=data_root, store=store,
    )}
    for tool, action_id in (
        ("request_write", "write"),
        ("request_rewrite", "rewrite"),
        ("request_review", "review"),
        ("request_diagnose", "diagnose"),
    ):
        outcome = run(specs, tool, {"chapter": 1})
        assert outcome.pending["action_id"] == action_id, tool
    assert [r["action_id"] for r in store.list_actions(book="MyBook")] == [
        "write", "rewrite", "review", "diagnose",
    ]
