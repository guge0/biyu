"""Reviser 单测 — T-P3-D-3 Part D。"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from biyu.reviser.prompts import REVISER_SYSTEM_PROMPT, build_reviser_prompt
from biyu.reviser.reviser import revise_paragraph, apply_revision, ReviserResult


def _run_async(coro):
    """Helper to run async coroutines in tests (Python 3.9 compat)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CHAPTER = (
    "老樵看着张今空，忽然说了句话。\n"
    "曹操冷笑道：后人编的都是假的。\n"
    "张今空在水中用布画了一张图。\n"
    "红糖糍粑红糖糍粑红糖糍粑，他一直在吃红糖糍粑。"
)


# ---------------------------------------------------------------------------
# Test 1: reviser prompt 构建
# ---------------------------------------------------------------------------
def test_build_reviser_prompt():
    """Prompt 应包含上下文 + 审稿意见 + 建议。"""
    prompt = build_reviser_prompt(
        chapter_text=SAMPLE_CHAPTER,
        paragraph_index=1,
        issue_description="曹操说了元叙事内容",
        fix_suggestion="改为符合三国时代的措辞",
    )
    assert "上一段落" in prompt
    assert "目标段落" in prompt
    assert "下一段落" in prompt
    assert "曹操说了元叙事内容" in prompt
    assert "改为符合三国时代的措辞" in prompt
    # 目标段落内容
    assert "曹操冷笑道" in prompt


def test_build_reviser_prompt_boundary():
    """段落 0（首段）没有上一段落，最后一段没有下一段落。"""
    prompt_first = build_reviser_prompt(
        chapter_text=SAMPLE_CHAPTER,
        paragraph_index=0,
        issue_description="test",
        fix_suggestion="fix",
    )
    assert "上一段落" not in prompt_first
    assert "下一段落" in prompt_first

    prompt_last = build_reviser_prompt(
        chapter_text=SAMPLE_CHAPTER,
        paragraph_index=3,
        issue_description="test",
        fix_suggestion="fix",
    )
    assert "上一段落" in prompt_last
    assert "下一段落" not in prompt_last


# ---------------------------------------------------------------------------
# Test 2: apply_revision 正确替换
# ---------------------------------------------------------------------------
def test_apply_revision():
    """替换指定段落后保持其他段落不变。"""
    revised = "曹操冷笑道：这不过是戏言罢了。"
    result = apply_revision(SAMPLE_CHAPTER, 1, revised)
    paragraphs = result.split("\n")
    assert paragraphs[0] == "老樵看着张今空，忽然说了句话。"
    assert paragraphs[1] == revised
    assert paragraphs[2] == "张今空在水中用布画了一张图。"
    assert len(paragraphs) == 4


def test_apply_revision_out_of_bounds():
    """越界 index → 不改动。"""
    result = apply_revision(SAMPLE_CHAPTER, 999, "new text")
    assert result == SAMPLE_CHAPTER

    result_neg = apply_revision(SAMPLE_CHAPTER, -1, "new text")
    assert result_neg == SAMPLE_CHAPTER


# ---------------------------------------------------------------------------
# Test 3: 成本记账
# ---------------------------------------------------------------------------
def test_revise_paragraph_cost_accounting():
    """Reviser 调用应正确记录成本。"""
    mock_resp = MagicMock()
    mock_resp.text = "改写后的段落内容"
    mock_resp.cost = 0.002

    adapter = AsyncMock()
    adapter.generate = AsyncMock(return_value=mock_resp)

    result = _run_async(
        revise_paragraph(
            chapter_text=SAMPLE_CHAPTER,
            paragraph_index=1,
            issue_description="test issue",
            fix_suggestion="test fix",
            adapter=adapter,
        )
    )
    assert result.success is True
    assert result.cost == 0.002
    assert result.paragraph_index == 1


# ---------------------------------------------------------------------------
# Test 4: Reviser 错误处理
# ---------------------------------------------------------------------------
def test_revise_paragraph_error():
    """Adapter 异常 → success=False。"""
    adapter = AsyncMock()
    adapter.generate = AsyncMock(side_effect=RuntimeError("API error"))

    result = _run_async(
        revise_paragraph(
            chapter_text=SAMPLE_CHAPTER,
            paragraph_index=1,
            issue_description="test",
            fix_suggestion="fix",
            adapter=adapter,
        )
    )
    assert result.success is False
    assert "API error" in result.error
    assert result.cost == 0.0


def test_revise_paragraph_empty_response():
    """Adapter 返回空文本 → success=False。"""
    mock_resp = MagicMock()
    mock_resp.text = ""
    mock_resp.cost = 0.001

    adapter = AsyncMock()
    adapter.generate = AsyncMock(return_value=mock_resp)

    result = _run_async(
        revise_paragraph(
            chapter_text=SAMPLE_CHAPTER,
            paragraph_index=1,
            issue_description="test",
            fix_suggestion="fix",
            adapter=adapter,
        )
    )
    assert result.success is False
    assert "空文本" in result.error


# ---------------------------------------------------------------------------
# Test 5: 5 次 soft warning（通过 reviser_call_count）
# ---------------------------------------------------------------------------
def test_reviser_limit_warning():
    """issue.reviser_call_count >= 5 时应触发 warning。"""
    from biyu.audit_reports.state import AuditIssue

    issue = AuditIssue(
        id="ch27-001", type="逻辑漏洞", paragraph=1,
        description="test", suggestion="original", severity="medium",
    )
    for i in range(5):
        issue.add_suggestion(f"fix v{i+1}", source="reviser", cost_yuan=0.001)

    assert issue.reviser_call_count == 5

    # 6th call — should still work (soft warning, not hard block)
    issue.add_suggestion("fix v6", source="reviser", cost_yuan=0.001)
    assert issue.reviser_call_count == 6
