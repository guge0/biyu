"""P8-M2 T3 · Editor standalone 问题卡渲染 + 编排 — 单测。

零成本:用 mock EditorResult + StubAdapter,不调真 LLM。

覆盖三维:
- 正确性:渲染出 spec 要求的"出处/因由/改法"三件套 + 元数据;编排正确加载章+渲染
- 稳定性:同输入 → 同输出
- 边缘:空 issues / 长 quote / 含 Markdown 特殊字符 / 多种失败模式 / 章不存在 / truth_files 缺失
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pytest

from biyu.editor.parser import EditorIssue, EditorResult
from biyu.editor.standalone import (
    render_issues_markdown,
    run_standalone_review,
    summarize_failure_modes,
    summarize_issues,
)


# ---------------------------------------------------------------------------
# summarize_failure_modes
# ---------------------------------------------------------------------------

def test_failure_modes_no_errors():
    """空 parse_errors → 空汇总。"""
    result = EditorResult(parse_errors=[])
    assert summarize_failure_modes(result) == {}


def test_failure_modes_bad_arguments():
    """识别 BAD_ARGUMENTS。"""
    result = EditorResult(parse_errors=["failure:BAD_ARGUMENTS", "其他诊断"])
    summary = summarize_failure_modes(result)
    assert summary.get("BAD_ARGUMENTS") == 1


def test_failure_modes_multiple_kinds():
    """RUN_FAIL ×2 + TRUNCATION ×1。"""
    result = EditorResult(parse_errors=[
        "failure:RUN_FAIL",
        "failure:RUN_FAIL",
        "failure:TRUNCATION",
    ])
    summary = summarize_failure_modes(result)
    assert summary.get("RUN_FAIL") == 2
    assert summary.get("TRUNCATION") == 1


def test_failure_modes_ignores_non_failure_errors():
    """非 failure: 前缀的 parse_error 不计入失败模式。"""
    result = EditorResult(parse_errors=[
        "幻觉过滤: ...",
        "JSON 解析失败: ...",
    ])
    assert summarize_failure_modes(result) == {}


# ---------------------------------------------------------------------------
# summarize_issues
# ---------------------------------------------------------------------------

def test_summarize_issues_empty():
    result = EditorResult(issues=[])
    s = summarize_issues(result)
    assert s["total"] == 0
    assert s["by_type"] == {}
    assert s["by_severity"] == {}


def test_summarize_issues_by_type_and_severity():
    issues = [
        EditorIssue(line=1, quote="", type="战力等级", subtype=None,
                    explanation="", fix_suggestion="", auto_fixable=False, severity="high"),
        EditorIssue(line=2, quote="", type="战力等级", subtype=None,
                    explanation="", fix_suggestion="", auto_fixable=False, severity="low"),
        EditorIssue(line=3, quote="", type="字面伪影", subtype=None,
                    explanation="", fix_suggestion="", auto_fixable=True, severity="low"),
    ]
    result = EditorResult(issues=issues)
    s = summarize_issues(result)
    assert s["total"] == 3
    assert s["by_type"]["战力等级"] == 2
    assert s["by_type"]["字面伪影"] == 1
    assert s["by_severity"]["high"] == 1
    assert s["by_severity"]["low"] == 2


# ---------------------------------------------------------------------------
# render_issues_markdown — 正确性
# ---------------------------------------------------------------------------

def test_render_empty_result_has_header():
    """空结果也要有章节标题和元数据。"""
    result = EditorResult(confidence="medium", cost=0.0)
    md = render_issues_markdown(result, chapter_num=1)
    assert "第1章" in md
    assert "Issue 数" in md


def test_render_includes_three_piece_spec():
    """spec 要求的'出处/因由/改法'三件套都要在。"""
    issue = EditorIssue(
        line=42,
        quote="他一拳打碎了山头",
        type="战力等级",
        subtype=None,
        explanation="前文第5章设定主角刚入境,只能打碎石块,此处威力严重失衡。",
        fix_suggestion="改成「打裂巨石」与入境初期匹配。",
        auto_fixable=False,
        severity="high",
    )
    result = EditorResult(issues=[issue], confidence="high", cost=0.0083)
    md = render_issues_markdown(result, chapter_num=5)

    # 出处
    assert "他一拳打碎了山头" in md
    assert "line 42" in md or "第42行" in md
    # 因由
    assert "前文第5章设定" in md
    # 改法
    assert "改成「打裂巨石」" in md
    # 类型 + 严重度都标
    assert "战力等级" in md
    assert "high" in md


def test_render_includes_metadata_block():
    """元数据(信心/queries/cost/parse_errors)写进报告。"""
    result = EditorResult(
        issues=[],
        confidence="high",
        cost=0.0083,
        queries_used=['look_up_character({"char_name":"李星元"})'],
        parse_errors=[],
    )
    md = render_issues_markdown(result, chapter_num=3)
    assert "high" in md
    assert "0.0083" in md
    assert "look_up_character" in md


def test_render_includes_failure_modes_when_present():
    """有失败模式时,报告里要显式标。"""
    result = EditorResult(parse_errors=["failure:BAD_ARGUMENTS", "其他诊断"])
    md = render_issues_markdown(result, chapter_num=1)
    # 失败模式部分
    assert "BAD_ARGUMENTS" in md
    assert "1" in md  # count = 1


# ---------------------------------------------------------------------------
# render_issues_markdown — 稳定性
# ---------------------------------------------------------------------------

def test_render_stability_same_output():
    """同输入多次渲染 → 完全相同输出。"""
    issue = EditorIssue(
        line=10, quote="abc", type="字面伪影", subtype=None,
        explanation="x", fix_suggestion="y", auto_fixable=True, severity="low",
    )
    result = EditorResult(issues=[issue], confidence="medium", cost=0.01)
    a = render_issues_markdown(result, chapter_num=1)
    b = render_issues_markdown(result, chapter_num=1)
    assert a == b


# ---------------------------------------------------------------------------
# render_issues_markdown — 边缘情况
# ---------------------------------------------------------------------------

def test_render_truncates_long_quote():
    """超长 quote 应截断(避免一份 issue 占整页)。"""
    long_quote = "他" * 500
    issue = EditorIssue(
        line=1, quote=long_quote, type="字面伪影", subtype=None,
        explanation="x", fix_suggestion="y", auto_fixable=True, severity="low",
    )
    result = EditorResult(issues=[issue])
    md = render_issues_markdown(result, chapter_num=1)
    # 报告里不应包含完整 500 字 quote
    assert long_quote not in md
    # 应有省略号提示截断
    assert "…" in md or "..." in md


def test_render_special_chars_dont_break_markdown():
    """explanation/改法含 Markdown 特殊字符时,不应破坏结构。"""
    issue = EditorIssue(
        line=1, quote="正常文字",
        type="字面伪影", subtype=None,
        explanation="含 **星号** 和 # 井号 和 `反引号` 与 中文「」",
        fix_suggestion="改成 [链接](url) 样式",
        auto_fixable=True, severity="low",
    )
    result = EditorResult(issues=[issue])
    md = render_issues_markdown(result, chapter_num=1)
    # 内容应在(可以转义但内容不丢)
    assert "星号" in md
    assert "井号" in md
    # 标题层级不破(下一个 # 标题仍是结构性的)
    assert "## 问题卡" in md


def test_render_multiple_issues_with_index():
    """多条 issue 都要编号,且原文/因由/改法对应不串。"""
    issues = [
        EditorIssue(line=10, quote="第一处原文", type="战力等级", subtype=None,
                    explanation="第一个因由", fix_suggestion="第一种改法",
                    auto_fixable=False, severity="high"),
        EditorIssue(line=20, quote="第二处原文", type="字面伪影", subtype=None,
                    explanation="第二个因由", fix_suggestion="第二种改法",
                    auto_fixable=True, severity="low"),
    ]
    result = EditorResult(issues=issues)
    md = render_issues_markdown(result, chapter_num=1)
    assert "第一处原文" in md and "第一个因由" in md and "第一种改法" in md
    assert "第二处原文" in md and "第二个因由" in md and "第二种改法" in md
    # 都要有编号(#1, #2 或 1., 2.)
    assert "#1" in md or "1." in md
    assert "#2" in md or "2." in md


def test_render_chapter_words_when_provided():
    """传 chapter_words 时,元数据里显示字数。"""
    result = EditorResult()
    md = render_issues_markdown(result, chapter_num=1, chapter_words=2543)
    assert "2543" in md


# ---------------------------------------------------------------------------
# run_standalone_review — 编排
# ---------------------------------------------------------------------------

class _StubResponse:
    """LLM 响应桩,与 test_editor_output_contract.py 同模式。"""

    def __init__(self, text="", cost=0.0, reasoning="", raw=None,
                 tool_calls=None, finish_reason="stop"):
        self.text = text
        self.cost = cost
        self.reasoning_content = reasoning
        self.raw = raw or {"choices": [{"message": {"content": text}}]}
        self.finish_reason = finish_reason
        if tool_calls:
            self.raw["choices"][0]["message"]["tool_calls"] = tool_calls


class _StubAdapter:
    """LLM 适配器桩,按预置序列返回响应。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def generate(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if self._responses:
            return self._responses.pop(0)
        return _StubResponse(text='{"issues": []}')


def _make_submit_call(issues, confidence="medium"):
    """构造 submit_review tool_call,issues 通过 final-round 提交。"""
    args = json.dumps({"issues": issues, "confidence": confidence}, ensure_ascii=False)
    return [{
        "id": "call_submit",
        "type": "function",
        "function": {"name": "submit_review", "arguments": args},
    }]


def _make_book_dir(tmp_path: Path, *, with_truth_files: bool = True,
                   chapter_text: str = "第1章 测试\n这是测试正文。" * 50) -> Path:
    """在 tmp_path 下建一本假书的目录结构。"""
    book_dir = tmp_path / "TestBook"
    ch_dir = book_dir / "chapters"
    ch_dir.mkdir(parents=True)
    (ch_dir / "ch1.md").write_text(chapter_text, encoding="utf-8")
    if with_truth_files:
        tf = book_dir / "truth_files"
        tf.mkdir()
        (tf / "current_state.md").write_text("当前状态占位", encoding="utf-8")
        (tf / "particle_ledger.md").write_text("粒子账本占位", encoding="utf-8")
        (tf / "pending_hooks.md").write_text("待挂起钩子占位", encoding="utf-8")
    return book_dir


def test_run_orchestration_returns_result_and_md(tmp_path):
    """编排:正常路径返 (EditorResult, Markdown)。"""
    book_dir = _make_book_dir(tmp_path)
    issue_payload = [{
        "line": 1, "quote": "测试正文",
        "type": "字面伪影", "subtype": None,
        "explanation": "测试问题因由",
        "fix_suggestion": "测试改法",
        "auto_fixable": True, "severity": "low",
    }]
    adapter = _StubAdapter([_StubResponse(
        text="", cost=0.001,
        tool_calls=_make_submit_call(issue_payload, confidence="high"),
    )])

    result, md = asyncio.run(run_standalone_review(
        book_dir, chapter_num=1, adapter=adapter,
    ))
    assert isinstance(result, EditorResult)
    assert "第1章" in md
    assert "测试问题因由" in md


def test_run_orchestration_missing_chapter_raises(tmp_path):
    """章节文件不存在 → FileNotFoundError(不静默、不猜)。"""
    book_dir = _make_book_dir(tmp_path)
    adapter = _StubAdapter([])

    with pytest.raises(FileNotFoundError):
        asyncio.run(run_standalone_review(
            book_dir, chapter_num=999, adapter=adapter,
        ))


def test_run_orchestration_logs_warning_when_truth_files_missing(
    tmp_path, caplog,
):
    """D-70 兜底出声:truth_files 缺失时必须 log WARNING。"""
    book_dir = _make_book_dir(tmp_path, with_truth_files=False)
    adapter = _StubAdapter([_StubResponse(
        text="", cost=0.0,
        tool_calls=_make_submit_call([], confidence="medium"),
    )])

    with caplog.at_level(logging.WARNING, logger="biyu.editor.standalone"):
        asyncio.run(run_standalone_review(
            book_dir, chapter_num=1, adapter=adapter,
        ))

    # 兜底必须出声
    assert any("truth_files" in rec.message for rec in caplog.records)


def test_run_orchestration_chapter_words_in_md(tmp_path):
    """渲染的 md 含 chapter_words(从加载的章文自动算)。"""
    book_dir = _make_book_dir(tmp_path)
    adapter = _StubAdapter([_StubResponse(
        text="", cost=0.0,
        tool_calls=_make_submit_call([], confidence="medium"),
    )])

    _, md = asyncio.run(run_standalone_review(
        book_dir, chapter_num=1, adapter=adapter,
    ))
    # 加载的章文是 50 个"第1章 测试\n这是测试正文。"(每段 11 个 CJK)
    # 应能在 md 里找到字数(具体数值不强断言,只断言元数据条目存在)
    assert "章节字数" in md
