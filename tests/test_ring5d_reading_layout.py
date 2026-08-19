from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
JS = (ROOT / "src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
CSS = (ROOT / "src/biyu/ui/static/styles.css").read_text(encoding="utf-8")
WORKBENCH_CSS = (ROOT / "src/biyu/ui/static/workbench.css").read_text(encoding="utf-8")


def test_no_cli_in_author_text():
    assert "sanitizeAuthorReport" in JS
    report_assignment = re.search(r"\$\('report'\)\.innerHTML\s*=\s*md\((.*?)\);", JS)
    assert report_assignment
    assert "sanitizeAuthorReport" in report_assignment.group(1)
    assert re.search(r"biyu\\s\+", JS)
    assert re.search(r"--", JS)


def test_version_label_is_human():
    assert "formatCandidateLabel" in JS
    assert "created_at" in JS
    assert re.search(r"第 \$\{item\.version\} 版 · \$\{time\} · \$\{item\.word_count\} 字", JS)
    assert "技术详情" in JS


def test_at_most_two_scroll_regions():
    assert re.search(
        r"\.reading-column,\.review-column\{[^}]*overflow-y:auto[^}]*\}",
        CSS,
    )
    assert ".reading-layout{overflow:hidden}" in CSS
    assert re.search(
        r"\.review-column \.report-pane\{[^}]*max-height:none[^}]*overflow:visible[^}]*\}",
        CSS,
    )
    assert ".report-pane{max-height:calc(100vh - 310px);overflow:auto}" in WORKBENCH_CSS


def test_diagnosis_card_not_above_prose():
    prose = HTML.index('id="chapter-read"')
    diagnosis = HTML.index('id="diagnosis-card"')
    assert prose < diagnosis


def test_mode_precedes_sticky_submit_block():
    # Revision mode scrolls with the review list; submit stays in the sticky footer.
    mode = HTML.index('id="revision-mode"')
    actions = HTML.index('class="revision-actions"')
    submit = HTML.index('id="submit-revision"')
    reason = HTML.index('data-reason="rewrite"')
    assert mode < actions < submit < reason
