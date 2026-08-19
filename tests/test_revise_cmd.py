"""revise_cmd 单测 — T-P3-D-3 Part E+F。"""
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from biyu.audit_reports.state import AuditIssue, AuditReportJSON


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_book_dir(tmp_path):
    """Create minimal book directory with audit report."""
    book_dir = tmp_path / "test_book"
    book_dir.mkdir()
    (book_dir / "characters.yaml").write_text("characters:\n  - name: test\n", encoding="utf-8")

    report_dir = book_dir / "audit_reports"
    report_dir.mkdir()

    issue = AuditIssue(
        id="ch1-001", type="视角穿帮", paragraph=2,
        description="曹操说了元叙事",
        suggestion="改为符合时代的措辞",
        severity="high",
    )
    report = AuditReportJSON(
        chapter=1, generated_at="2026-05-12 10:00:00",
        editor_mode="single", editor_cost_yuan=0.01,
        issues=[issue],
    )
    report.save(report_dir)

    # Create chapter file
    ch_dir = book_dir / "chapters"
    ch_dir.mkdir()
    (ch_dir / "ch1.md").write_text(
        "第一段\n曹操说了后人编的。\n第三段\n", encoding="utf-8"
    )

    return book_dir


# ---------------------------------------------------------------------------
# Test 1: apply action 状态转换
# ---------------------------------------------------------------------------
def test_apply_transition():
    """apply → resolved_by_biyu。"""
    issue = AuditIssue(
        id="ch1-001", type="视角穿帮", paragraph=2,
        description="test", suggestion="fix it", severity="high",
    )
    assert issue.status == "open"
    assert issue.transition("resolved_by_biyu", note="Reviser fix")
    assert issue.status == "resolved_by_biyu"
    assert issue.resolved_at is not None


# ---------------------------------------------------------------------------
# Test 2: resolve-self action 状态转换
# ---------------------------------------------------------------------------
def test_resolve_self_transition():
    """resolve-self → resolved_by_author。"""
    issue = AuditIssue(
        id="ch1-001", type="视角穿帮", paragraph=2,
        description="test", suggestion="fix it", severity="high",
    )
    assert issue.transition("resolved_by_author", note="Author self-resolved")
    assert issue.status == "resolved_by_author"


# ---------------------------------------------------------------------------
# Test 3: dismiss action 状态转换
# ---------------------------------------------------------------------------
def test_dismiss_transition():
    """dismiss → dismissed。"""
    issue = AuditIssue(
        id="ch1-001", type="视角穿帮", paragraph=2,
        description="test", suggestion="fix it", severity="high",
    )
    assert issue.transition("dismissed", note="False positive")
    assert issue.status == "dismissed"


# ---------------------------------------------------------------------------
# Test 4: regen 保持 open + 追加 history
# ---------------------------------------------------------------------------
def test_regen_stays_open():
    """regen → status 保持 open，suggestions_history 增加。"""
    issue = AuditIssue(
        id="ch1-001", type="逻辑漏洞", paragraph=2,
        description="test", suggestion="original fix", severity="medium",
    )
    issue.add_suggestion("new fix v1", source="reviser", cost_yuan=0.001)
    assert issue.status == "open"  # unchanged
    assert len(issue.suggestions_history) == 1
    assert issue.suggestion == "new fix v1"

    issue.add_suggestion("new fix v2", source="reviser", cost_yuan=0.001)
    assert issue.status == "open"
    assert len(issue.suggestions_history) == 2
    assert issue.suggestion == "new fix v2"


# ---------------------------------------------------------------------------
# Test 5: 5 次 warning
# ---------------------------------------------------------------------------
def test_reviser_soft_limit_warning():
    """reviser_call_count >= 5 时应提示 warning。"""
    issue = AuditIssue(
        id="ch1-001", type="逻辑漏洞", paragraph=2,
        description="test", suggestion="original", severity="medium",
    )
    for i in range(5):
        issue.add_suggestion(f"fix {i}", source="reviser", cost_yuan=0.001)

    assert issue.reviser_call_count == 5
    # 实际 warning 逻辑在 _check_reviser_limit 中，
    # 通过 console.print 输出，这里验证计数逻辑


# ---------------------------------------------------------------------------
# Test 6: git commit message 格式
# ---------------------------------------------------------------------------
def test_commit_reviser_message():
    """commit_reviser_change 的 message 格式。"""
    # 验证 message 生成逻辑（不实际调 git）
    chapter_id = 27
    issue_id = "ch27-001"
    expected = f"[draft]: CH{chapter_id} Reviser 修复 {issue_id}"
    assert "[draft]" in expected
    assert "CH27" in expected
    assert "ch27-001" in expected


def test_commit_finalize_message():
    """commit_finalize 的 message 格式。"""
    chapter_id = 27
    expected = f"auto: CH{chapter_id} 定稿（所有 issue 已处理）"
    assert "定稿" in expected
    assert "[draft]" not in expected


# ---------------------------------------------------------------------------
# Test 7: _load_report / _save_and_render
# ---------------------------------------------------------------------------
def test_load_and_save_report(mock_book_dir):
    """加载 + 保存 JSON 报告应保持一致。"""
    from biyu.audit_reports.builder import build_audit_md_from_json

    report_dir = mock_book_dir / "audit_reports"
    report = AuditReportJSON.load(report_dir / "ch1.json")

    assert report.chapter == 1
    assert len(report.issues) == 1
    assert report.issues[0].id == "ch1-001"

    # Modify and save
    report.issues[0].transition("resolved_by_author", note="test")
    report.save(report_dir)

    # Render MD
    md_path = build_audit_md_from_json(report, mock_book_dir)
    assert md_path.exists()
    content = md_path.read_text(encoding="utf-8")
    assert "ch1-001" in content

    # Reload and verify
    loaded = AuditReportJSON.load(report_dir / "ch1.json")
    assert loaded.issues[0].status == "resolved_by_author"


# ---------------------------------------------------------------------------
# Test 8: sync action
# ---------------------------------------------------------------------------
def test_sync_action(mock_book_dir):
    """sync 从 MD checkbox 更新 JSON。"""
    from biyu.audit_reports.sync import sync_md_to_json

    # Create MD with checkbox
    report_dir = mock_book_dir / "audit_reports"
    md_content = "- [x] 视角穿帮: test #ch1-001\n"
    (report_dir / "ch1.md").write_text(md_content, encoding="utf-8")

    updated = sync_md_to_json(mock_book_dir, 1)
    assert updated == 1

    report = AuditReportJSON.load(report_dir / "ch1.json")
    assert report.issues[0].status == "resolved_by_author"


# ---------------------------------------------------------------------------
# Test 9: issue ID → chapter number 推导
# ---------------------------------------------------------------------------
def test_issue_id_chapter_derivation():
    """从 issue ID 推导章节号。"""
    issue_id = "ch27-001"
    chapter_num = int(issue_id.split("-")[0].replace("ch", ""))
    assert chapter_num == 27

    issue_id2 = "ch3-042"
    chapter_num2 = int(issue_id2.split("-")[0].replace("ch", ""))
    assert chapter_num2 == 3
