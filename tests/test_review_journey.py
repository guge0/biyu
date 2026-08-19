from __future__ import annotations

import json
from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_revision_round_counting(tmp_path: Path) -> None:
    from biyu.ui.diagnosis import revision_round_count

    for number, status in enumerate(("complete", "ready", "failed", "complete"), 1):
        _write(tmp_path / f"logs/ch1/revisions/round_{number}/manifest.json", json.dumps({"status": status}))
    assert revision_round_count(tmp_path, 1) == 2


def test_problem_line_dual_purpose_separated(tmp_path: Path) -> None:
    from biyu.audit_reports.revisions import create_revision_package
    from biyu.audit_reports.revisions import text_sha

    _write(tmp_path / "chapters/_pending/ch1.md", "正文")
    _write(tmp_path / "logs/ch1/planning.md", "status: 已批\n方案")
    _write(tmp_path / "audit_reports/ch1.json", '{"issues":[]}')
    package = create_revision_package(
        tmp_path, 1, selected_issue_ids=[], issue_comments={},
        general_comment="整体返修", candidate_sha=text_sha("正文"),
        sample_problem_ids=["bad-1"], revision_problem_ids=["bad-1", "bad-2"],
    )
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sample_problem_ids"] == ["bad-1"]
    assert manifest["revision_problem_ids"] == ["bad-1", "bad-2"]


def test_frontend_contract_uses_independent_scroll_and_existing_floor() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
    css = Path("src/biyu/ui/static/styles.css").read_text(encoding="utf-8")
    assert 'id="diagnosis-card"' in html
    assert 'id="review-position"' in html
    assert 'class="progress-list"' in html
    assert "MiniMd.render" in js
    assert "scrollIntoView(" not in js
    assert "reading-column" in css and "review-column" in css
    assert ".review-column #issue-list" not in css


def test_followup_product_path_contracts() -> None:
    app_js = Path("src/biyu/ui/static/app.js").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
    revision_css = Path("src/biyu/ui/static/workbench-revision.css").read_text(encoding="utf-8")
    assert 'book.kind === "real"' in app_js
    assert '"/book.html?book="' in app_js
    assert '"/workbench.html?book="' in app_js
    assert "diagnosisClosedForSha" in js
    assert "已进入本轮返修" in js
    assert ".issue-list { display: grid; gap: 8px; }" in revision_css
    assert "max-height" not in revision_css.split(".issue-list", 1)[1].split(".issue-card", 1)[0]
