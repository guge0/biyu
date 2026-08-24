import re
from pathlib import Path

from tests.support.viewport_contracts import VIEWPORT_ASSERTIONS_JS, required_viewport_assertion_names


def test_viewport_checker_contains_all_four_machine_rules() -> None:
    for name in required_viewport_assertion_names():
        assert name in VIEWPORT_ASSERTIONS_JS


def test_author_facing_pages_have_no_internal_role_terms() -> None:
    static = Path("src/biyu/ui/static")
    for path in (static / "workbench.html", static / "settings.html"):
        text = path.read_text(encoding="utf-8")
        assert "中枢裁定" not in text
        assert "读稿层" not in text


def test_workbench_and_settings_boundary_contracts_are_encoded() -> None:
    static = Path("src/biyu/ui/static")
    workbench = (static / "workbench.html").read_text(encoding="utf-8")
    workbench_js = (static / "workbench.js").read_text(encoding="utf-8")
    styles = (static / "styles.css").read_text(encoding="utf-8")
    paper = (static / "biyu-paper.css").read_text(encoding="utf-8")
    settings = (static / "settings.js").read_text(encoding="utf-8")

    assert 'id="workbench-book-link"' in workbench
    assert "← 回到这本书" in workbench
    assert "bookLink.href=`/book.html?book=" in workbench_js
    compact = styles.split("@media (max-width:1280px)", 1)[1]
    actions_rule = re.search(r"\.workbench-actions-row\{(?P<body>[^}]*)\}", compact).group("body")
    assert "flex-direction:row" in actions_rule
    assert ":focus-visible{outline:2px solid var(--ink-solid)" in paper
    assert "outline:2px solid var(--mark-bg)" not in paper
    assert "input:focus-visible+.backup-switch-track{outline:2px solid var(--ink-solid)" in styles
    assert "newCharacterButton(true)" in settings
    assert "primary?'b1':'b2'" in settings
