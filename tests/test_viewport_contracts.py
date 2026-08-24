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
