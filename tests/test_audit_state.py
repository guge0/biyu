"""audit_reports state machine + sync 单测 — T-P3-D-3 Part B+C。"""
import json
import pytest
from pathlib import Path
from biyu.audit_reports.state import (
    AuditIssue, AuditReportJSON, SuggestionVersion, StatusTransition,
    VALID_TRANSITIONS, TERMINAL_STATES,
    build_report_from_editor_result,
)
from biyu.audit_reports.sync import sync_md_to_json
from biyu.audit_reports.builder import build_audit_md_from_json
from biyu.editor.parser import EditorIssue


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_issue() -> AuditIssue:
    return AuditIssue(
        id="ch27-001",
        type="视角穿帮",
        paragraph=42,
        description="曹操说了元叙事内容",
        suggestion="改为符合三国时代的措辞",
        severity="high",
    )


@pytest.fixture
def sample_report() -> AuditReportJSON:
    issue1 = AuditIssue(
        id="ch27-001", type="视角穿帮", paragraph=42,
        description="曹操说了元叙事内容",
        suggestion="改为符合时代的措辞",
        severity="high",
    )
    issue2 = AuditIssue(
        id="ch27-002", type="逻辑漏洞", paragraph=88,
        description="水中布上画图",
        suggestion="改为在岸边用石头画",
        severity="medium",
    )
    return AuditReportJSON(
        chapter=27,
        generated_at="2026-05-12 10:00:00",
        editor_mode="single",
        editor_cost_yuan=0.03,
        issues=[issue1, issue2],
    )


@pytest.fixture
def report_dir(tmp_path) -> Path:
    return tmp_path / "audit_reports"


# ---------------------------------------------------------------------------
# Test 1: JSON schema 校验
# ---------------------------------------------------------------------------
def test_json_roundtrip(sample_report, report_dir):
    """Save + load 应保持一致。"""
    path = sample_report.save(report_dir)
    assert path.exists()

    loaded = AuditReportJSON.load(path)
    assert loaded.chapter == 27
    assert loaded.editor_mode == "single"
    assert len(loaded.issues) == 2
    assert loaded.issues[0].id == "ch27-001"
    assert loaded.issues[0].type == "视角穿帮"
    assert loaded.issues[1].severity == "medium"


# ---------------------------------------------------------------------------
# Test 2: 状态机合法转换
# ---------------------------------------------------------------------------
def test_valid_transitions(sample_issue):
    """open → resolved_by_author / resolved_by_biyu / dismissed。"""
    # open → resolved_by_author
    assert sample_issue.transition("resolved_by_author", note="作者手修")
    assert sample_issue.status == "resolved_by_author"
    assert sample_issue.resolved_at is not None
    assert len(sample_issue.status_history) == 1

    # Terminal: cannot transition further
    assert not sample_issue.transition("open")


def test_valid_transition_resolved_by_biyu():
    """open → resolved_by_biyu。"""
    issue = AuditIssue(id="t-001", type="逻辑漏洞", paragraph=1,
                       description="test", suggestion="fix", severity="medium")
    assert issue.transition("resolved_by_biyu", note="Reviser 修复")
    assert issue.status == "resolved_by_biyu"
    assert issue.resolved_at is not None


def test_valid_transition_dismissed():
    """open → dismissed。"""
    issue = AuditIssue(id="t-001", type="人设守恒", paragraph=1,
                       description="test", suggestion="fix", severity="low")
    assert issue.transition("dismissed", note="误报")
    assert issue.status == "dismissed"


# ---------------------------------------------------------------------------
# Test 3: 非法转换拒绝
# ---------------------------------------------------------------------------
def test_invalid_transition():
    """Terminal 状态不能再转换。"""
    issue = AuditIssue(id="t-001", type="视角穿帮", paragraph=1,
                       description="test", suggestion="fix", severity="high")
    issue.transition("resolved_by_author")
    # terminal → anything
    assert not issue.transition("open")
    assert not issue.transition("resolved_by_biyu")
    assert issue.status == "resolved_by_author"


def test_invalid_transition_from_nonexistent():
    """无效 from_status → 不能转换。"""
    issue = AuditIssue(id="t-001", type="视角穿帮", paragraph=1,
                       description="test", suggestion="fix", severity="high")
    issue.status = "nonexistent"
    assert not issue.transition("open")


# ---------------------------------------------------------------------------
# Test 4: finalize 条件
# ---------------------------------------------------------------------------
def test_is_chapter_finalized(sample_report):
    """所有 issue 终态 → finalized。"""
    assert not sample_report.is_chapter_finalized()
    sample_report.issues[0].transition("resolved_by_author")
    assert not sample_report.is_chapter_finalized()
    sample_report.issues[1].transition("dismissed")
    assert sample_report.is_chapter_finalized()


# ---------------------------------------------------------------------------
# Test 5: MD ↔ JSON sync
# ---------------------------------------------------------------------------
def test_sync_md_to_json(tmp_path):
    """MD checkbox → JSON resolved_by_author。"""
    report_dir = tmp_path / "audit_reports"
    report_dir.mkdir()

    # Create JSON report
    issue = AuditIssue(id="ch27-001", type="视角穿帮", paragraph=42,
                       description="test", suggestion="fix it", severity="high")
    report = AuditReportJSON(
        chapter=27, generated_at="2026-05-12 10:00:00",
        issues=[issue],
    )
    report.save(report_dir)

    # Create MD with checkbox checked
    md_content = (
        "# CH27 Issue 追踪\n\n"
        "- [x] 视角穿帮: test #ch27-001\n"
        "- [ ] 逻辑漏洞: other #ch27-002\n"
    )
    md_path = report_dir / "ch27.md"
    md_path.write_text(md_content, encoding="utf-8")

    updated = sync_md_to_json(tmp_path, 27)
    assert updated == 1

    # Verify JSON updated
    loaded = AuditReportJSON.load(report_dir / "ch27.json")
    assert loaded.issues[0].status == "resolved_by_author"
    assert loaded.issues[0].resolution_note == "MD checkbox 勾选"


def test_sync_md_no_checked(tmp_path):
    """No checkboxes checked → no updates。"""
    report_dir = tmp_path / "audit_reports"
    report_dir.mkdir()

    issue = AuditIssue(id="ch27-001", type="视角穿帮", paragraph=42,
                       description="test", suggestion="fix it", severity="high")
    report = AuditReportJSON(
        chapter=27, generated_at="2026-05-12 10:00:00",
        issues=[issue],
    )
    report.save(report_dir)

    md_content = (
        "# CH27\n"
        "- [ ] 视角穿帮: test #ch27-001\n"
    )
    (report_dir / "ch27.md").write_text(md_content, encoding="utf-8")

    updated = sync_md_to_json(tmp_path, 27)
    assert updated == 0


# ---------------------------------------------------------------------------
# Test 6: build_report_from_editor_result
# ---------------------------------------------------------------------------
def test_build_report_from_editor_result():
    """EditorResult → AuditReportJSON 转换。"""
    editor_issues = [
        EditorIssue(
            line=42, quote="曹操说了", type="视角穿帮",
            subtype=None, explanation="穿帮",
            fix_suggestion="改为符合三国时代措辞",
            auto_fixable=False, severity="high",
        ),
        EditorIssue(
            line=88, quote="布画图", type="逻辑漏洞",
            subtype=None, explanation="布会散",
            fix_suggestion="改为在岸边画图",
            auto_fixable=False, severity="medium",
        ),
    ]
    from biyu.editor.parser import EditorResult
    editor_result = EditorResult(issues=editor_issues)

    report = build_report_from_editor_result(
        chapter_num=27,
        editor_result=editor_result,
        editor_cost_yuan=0.03,
    )
    assert report.chapter == 27
    assert len(report.issues) == 2
    assert report.issues[0].id == "ch27-001"
    assert report.issues[0].severity == "high"
    assert report.issues[0].suggestions_history[0].source == "editor"
    assert report.issues[1].id == "ch27-002"


# ---------------------------------------------------------------------------
# Test 7: MD 渲染 from JSON
# ---------------------------------------------------------------------------
def test_build_audit_md_from_json(sample_report, tmp_path):
    """AuditReportJSON → MD 渲染。"""
    path = build_audit_md_from_json(sample_report, tmp_path)
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "CH27" in content
    assert "视角穿帮" in content
    assert "ch27-001" in content
    assert "biyu revise" in content
    assert "逻辑漏洞" in content


# ---------------------------------------------------------------------------
# Test 8: add_suggestion / reviser_call_count
# ---------------------------------------------------------------------------
def test_add_suggestion():
    """add_suggestion 追加版本并更新当前 suggestion。"""
    issue = AuditIssue(id="t-001", type="逻辑漏洞", paragraph=1,
                       description="test", suggestion="original", severity="medium")
    assert issue.reviser_call_count == 0

    issue.add_suggestion("new fix", source="reviser", cost_yuan=0.001)
    assert issue.suggestion == "new fix"
    assert issue.reviser_call_count == 1
    assert len(issue.suggestions_history) == 1

    issue.add_suggestion("another fix", source="reviser", cost_yuan=0.002)
    assert issue.suggestion == "another fix"
    assert issue.reviser_call_count == 2


# ---------------------------------------------------------------------------
# Test 9: 兼容旧格式 (results 字段)
# ---------------------------------------------------------------------------
def test_legacy_format_compatibility(tmp_path):
    """JSON 只有 results 没有 issues → 能正常加载。"""
    legacy_data = {
        "chapter": 5,
        "results": [
            {"checker": "dedup", "severity": "PASS", "message": "OK"},
        ],
    }
    path = tmp_path / "ch5.json"
    path.write_text(json.dumps(legacy_data, ensure_ascii=False), encoding="utf-8")

    report = AuditReportJSON.load(path)
    assert report.chapter == 5
    assert len(report.results) == 1
    assert len(report.issues) == 0
