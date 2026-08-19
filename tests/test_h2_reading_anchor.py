from pathlib import Path


def test_issue_anchor_uses_the_actual_scroll_owners_and_returns_to_reading() -> None:
    script = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")

    assert "function focusAnchor" in script
    assert "setReadingView('review')" in script
    assert "const container=fromText?$('revision-list-shell'):readingScrollElement()" in script
    assert "$('chapter-read').scrollTop" not in script
    # v6:详情态保留动作位置；失效锚点明确禁用。
    assert "locate.disabled=!canLocate" in script
    assert "locate.textContent=canLocate?'定位正文':'定位不可用'" in script


def test_reading_layout_declares_both_scroll_owners() -> None:
    css = Path("src/biyu/ui/static/styles.css").read_text(encoding="utf-8")

    assert ".reading-column>#chapter-read" in css
    assert ".revision-list-shell{flex:1;min-height:0;overflow-y:auto" in css
