from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
JS = (ROOT / "src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
CSS = (ROOT / "src/biyu/ui/static/styles.css").read_text(encoding="utf-8")


def test_all_known_auditor_and_editor_types_have_chinese_author_labels() -> None:
    import biyu.ui.workbench as wb
    from biyu.auditor import _CHECKER_REGISTRY
    from biyu.editor.schema import AGENT_VALID_TYPES

    auditor_types = set(_CHECKER_REGISTRY)
    editor_types = set().union(*AGENT_VALID_TYPES.values())
    assert auditor_types <= wb._AUDITOR_AUTHOR_LABELS.keys()
    assert editor_types <= wb._EDITOR_AUTHOR_LABELS.keys()
    for internal_name in auditor_types | editor_types:
        label = wb._author_type_label(internal_name)
        assert label != internal_name
        assert not re.search(r"[A-Za-z_]", label)
    assert wb._author_type_label("new_internal_checker") == "规则检查"


def test_style_repeat_projection_hides_regex_and_reports_real_lines(tmp_path: Path) -> None:
    import biyu.ui.workbench as wb

    pattern = "不是[^。，]*[，。](?:而)?是"
    text = "第一行。\n不是风停了，而是所有人都屏住了呼吸。\n第三行。\n不是门开了，是门后的人退了一步。"
    path = tmp_path / "ch1.json"
    path.write_text(json.dumps({"results": [{
        "checker": "style_repeat",
        "severity": "WARN",
        "message": f"发现 1 处句式重复: '{pattern}' 在本章出现 2 次（限制 1）",
        "details": {
            "current_counts": {pattern: 2},
            "recent_3ch_counts": {},
            "violations": [f"'{pattern}' 在本章出现 2 次（限制 1）"],
        },
    }]}, ensure_ascii=False), encoding="utf-8")

    card = wb._load_issue_cards(path, text)[0]
    visible = " · ".join(str(card[key]) for key in ("type", "severity_label", "judgment", "position_label"))
    assert card["type"] == "句式重复"
    assert card["severity_label"] == "建议修改"
    assert "『不是 X 而是 Y』这个句式出现 2 次" in card["judgment"]
    assert card["position_label"] == "第 2 行、第 4 行"
    assert card["line"] == 2
    assert card["quote"] == "不是风停了，而是"
    assert "[^" not in visible and "?:" not in visible and "style_repeat" not in visible


def test_unknown_auditor_result_never_leaks_identifier_or_raw_exception(tmp_path: Path) -> None:
    import biyu.ui.workbench as wb

    path = tmp_path / "ch1.json"
    path.write_text(json.dumps({"results": [{
        "checker": "new_internal_checker",
        "severity": "BLOCK",
        "message": "RuntimeError: field_name exploded",
        "details": {},
    }]}), encoding="utf-8")
    card = wb._load_issue_cards(path, "正文")[0]
    assert card["type"] == "规则检查"
    assert card["severity_label"] == "必须处理"
    assert card["judgment"] == "规则检查发现一处需要核对的问题。"
    assert card["position_label"] == "整章"
    visible = " · ".join(str(card[key]) for key in ("type", "severity_label", "judgment", "position_label"))
    assert "new_internal_checker" not in visible
    assert "RuntimeError" not in visible


def test_source_labels_are_explicit_in_every_author_surface() -> None:
    assert "const ISSUE_SOURCE_LABELS=Object.freeze" in JS
    for source, label in (
        ("editor", "编辑提出"),
        ("auditor", "规则检查"),
        ("checklist", "戏核核对"),
        ("author_selection", "我划的"),
    ):
        assert f"{source}:'{label}'" in JS
    assert "||'来源未识别'" in JS
    assert "card.source==='editor'?'编辑提出':'戏核核对'" not in JS


def test_review_toolbar_stays_visible_and_records_are_in_bottom_fold_group() -> None:
    assert re.search(r"\.workbench \.review-toolbar\{[^}]*position:sticky[^}]*top:0[^}]*z-index:", CSS)
    report = HTML.index('id="report"')
    records = HTML.index('id="sample-preview"')
    assert report < records
    assert "$('revision-list-shell').append($('diagnosis-card'));" in JS


def test_mid_desktop_review_uses_overlay_to_preserve_article_width() -> None:
    assert re.search(
        r"@media \(min-width:1200px\) and \(max-width:1299px\).*?"
        r"\.reading-layout\.reading-aside-open\{grid-template-columns:minmax\(0,1fr\)\}",
        CSS,
        re.S,
    )
