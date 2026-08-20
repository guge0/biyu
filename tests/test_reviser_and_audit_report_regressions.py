"""返修定位、审读报告渲染与同步的回归测试。"""
import json
import pytest
from pathlib import Path

from biyu.reviser.prompts import (
    find_target_paragraph, _fuzzy_match, ReviserLocationError,
    build_reviser_prompt,
)
from biyu.audit_reports.state import (
    AuditIssue, AuditReportJSON, build_report_from_editor_result,
)
from biyu.audit_reports.builder import build_audit_md_from_json
from biyu.audit_reports.sync import sync_md_to_json
from biyu.editor.parser import parse_editor_response, EditorIssue


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_PARAGRAPHS = [
    "老樵看着张今空，忽然说了句话。",
    "曹操冷笑道：后人编的都是假的。",
    "张今空在水中用布画了一张图。",
    "红糖糍粑红糖糍粑红糖糍粑，他一直在吃红糖糍粑。",
]

SAMPLE_CHAPTER = "\n".join(SAMPLE_PARAGRAPHS)


# ===========================================================================
# 必修-1: find_target_paragraph — 引文优先匹配
# ===========================================================================

def test_locate_by_quoted_text_exact():
    """精确引文匹配：quoted_text 在段落中逐字存在。"""
    idx = find_target_paragraph(
        SAMPLE_PARAGRAPHS,
        quoted_text="曹操冷笑道：后人编的都是假的",
        line=999,  # line 故意给错，验证引文优先
    )
    assert idx == 1


def test_locate_by_quoted_text_fuzzy():
    """引文略变形（标点不同）仍能匹配。"""
    # 原文是"后人编的都是假的"，引文用了不同标点
    idx = find_target_paragraph(
        SAMPLE_PARAGRAPHS,
        quoted_text="曹操冷笑道:后人编的都是假的",  # 英文冒号
        line=999,
    )
    assert idx == 1


def test_locate_fallback_to_line():
    """无 quoted_text 时 line 字段生效。"""
    idx = find_target_paragraph(
        SAMPLE_PARAGRAPHS,
        quoted_text="",
        line=3,  # 1-indexed → index 2
        issue_id="ch27-001",
    )
    assert idx == 2


def test_locate_raises_when_all_fail():
    """引文和 line 都失败时 raise 明确异常。"""
    with pytest.raises(ReviserLocationError) as exc_info:
        find_target_paragraph(
            SAMPLE_PARAGRAPHS,
            quoted_text="这段文字完全不存在于任何段落中",
            line=999,
            issue_id="ch27-003",
        )
    assert "ch27-003" in str(exc_info.value)
    assert "4 段" in str(exc_info.value)


# ===========================================================================
# 必修-2: bounds check — reviser prompt 边界
# ===========================================================================

def test_reviser_handles_boundary_paragraph():
    """第一段(idx=0, 无 prev)不会 IndexError。"""
    prompt = build_reviser_prompt(
        chapter_text=SAMPLE_CHAPTER,
        paragraph_index=0,
        issue_description="test",
        fix_suggestion="fix",
    )
    assert "上一段落" not in prompt
    assert "下一段落" in prompt
    assert "老樵看着张今空" in prompt


def test_reviser_handles_last_paragraph():
    """最后段(idx=len-1, 无 next)不会 IndexError。"""
    prompt = build_reviser_prompt(
        chapter_text=SAMPLE_CHAPTER,
        paragraph_index=len(SAMPLE_PARAGRAPHS) - 1,
        issue_description="test",
        fix_suggestion="fix",
    )
    assert "上一段落" in prompt
    assert "下一段落" not in prompt
    assert "红糖糍粑" in prompt


def test_reviser_handles_out_of_bounds():
    """越界 index 不报错，目标段落为空。"""
    prompt = build_reviser_prompt(
        chapter_text=SAMPLE_CHAPTER,
        paragraph_index=999,
        issue_description="test",
        fix_suggestion="fix",
    )
    assert "目标段落（需要改写）" in prompt
    # 目标段落应为空
    assert "审稿意见" in prompt


def test_reviser_handles_negative_index():
    """负数 index 不报错。"""
    prompt = build_reviser_prompt(
        chapter_text=SAMPLE_CHAPTER,
        paragraph_index=-1,
        issue_description="test",
        fix_suggestion="fix",
    )
    assert "审稿意见" in prompt


# ===========================================================================
# 必修-3: MD 模板渲染 checkbox + sync 端到端
# ===========================================================================

def test_md_renders_checkbox_for_open_issue(tmp_path):
    """open issue 渲染 `- [ ]` 行。"""
    issue = AuditIssue(
        id="ch27-001", type="视角穿帮", paragraph=42,
        description="test", suggestion="fix it", severity="high",
    )
    report = AuditReportJSON(
        chapter=27, generated_at="2026-05-12 10:00:00",
        issues=[issue],
    )
    path = build_audit_md_from_json(report, tmp_path)
    content = path.read_text(encoding="utf-8")
    assert "- [ ]" in content
    assert "#ch27-001" in content


def test_md_renders_checkbox_for_resolved(tmp_path):
    """resolved issue 渲染 `- [x]` 行。"""
    issue = AuditIssue(
        id="ch27-001", type="视角穿帮", paragraph=42,
        description="test", suggestion="fix it", severity="high",
        status="resolved_by_author",
    )
    report = AuditReportJSON(
        chapter=27, generated_at="2026-05-12 10:00:00",
        issues=[issue],
    )
    path = build_audit_md_from_json(report, tmp_path)
    content = path.read_text(encoding="utf-8")
    assert "- [x]" in content
    assert "#ch27-001" in content


def test_sync_recognizes_template_format(tmp_path):
    """端到端：模板渲染的 MD 勾选后 sync 能识别。"""
    report_dir = tmp_path / "audit_reports"
    report_dir.mkdir()

    # 创建 open issue 的 JSON
    issue = AuditIssue(
        id="ch27-001", type="视角穿帮", paragraph=42,
        description="test", suggestion="fix it", severity="high",
    )
    report = AuditReportJSON(
        chapter=27, generated_at="2026-05-12 10:00:00",
        issues=[issue],
    )
    report.save(report_dir)

    # 渲染 MD
    md_path = build_audit_md_from_json(report, tmp_path)
    md_content = md_path.read_text(encoding="utf-8")

    # 模拟作者勾选：将 [ ] 改为 [x]
    md_content = md_content.replace("- [ ]", "- [x]")
    md_path.write_text(md_content, encoding="utf-8")

    # sync 应该识别并更新
    updated = sync_md_to_json(tmp_path, 27)
    assert updated == 1

    loaded = AuditReportJSON.load(report_dir / "ch27.json")
    assert loaded.issues[0].status == "resolved_by_author"


# ===========================================================================
# quoted_text 端到端：Editor → AuditIssue → find_target_paragraph
# ===========================================================================

def test_quoted_text_flows_from_editor_to_reviser():
    """quoted_text 从 Editor 输出流经 AuditIssue 到 Reviser 定位。"""
    # 模拟 Editor LLM 返回
    response = json.dumps({
        "issues": [{
            "line": 465,  # 幻觉行号，远超实际段落数
            "quote": "后人编的都是假的",
            "quoted_text": "曹操冷笑道：后人编的都是假的",
            "type": "认知边界",
            "subtype": None,
            "explanation": "穿帮",
            "fix_suggestion": "改为符合三国时代的措辞",
            "auto_fixable": False,
            "severity": "high",
        }],
        "queries_used": [],
        "confidence": "high",
    })
    editor_result = parse_editor_response(response, SAMPLE_CHAPTER)

    # quoted_text 应被解析
    assert editor_result.issues[0].quoted_text == "曹操冷笑道：后人编的都是假的"

    # 构造 AuditReportJSON
    report = build_report_from_editor_result(27, editor_result)
    assert report.issues[0].quoted_text == "曹操冷笑道：后人编的都是假的"

    # 用 find_target_paragraph 定位 — 引文优先，幻觉行号被忽略
    idx = find_target_paragraph(
        SAMPLE_PARAGRAPHS,
        quoted_text=report.issues[0].quoted_text,
        line=report.issues[0].paragraph,  # 465 — 越界
        issue_id=report.issues[0].id,
    )
    assert idx == 1  # 正确定位到第二段
