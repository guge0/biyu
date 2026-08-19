from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from biyu.ui import workbench


CHECKLIST = """## 必检项

**必须发生**
- 林舟拿到蓝皮册子

**必须不发生**
- 不揭晓册子来源

**结尾状态**
- 林舟离开旧书店

**信息层级**
- 只知道册子会改写
"""


def _plan(*, people: str | None, setting: str | None) -> str:
    rows = ["# 本章方案"]
    if people is not None:
        rows.append(f"- **人物**：{people}")
    if setting is not None:
        rows.append(f"- **道具**：{setting}")
    rows.append(CHECKLIST)
    return "\n\n".join(rows)


@pytest.fixture
def book(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "book"
    (root / "outlines").mkdir(parents=True)
    (root / "outlines" / "ch1.md").write_text("细纲", encoding="utf-8")
    (root / "characters.yaml").write_text(
        yaml.safe_dump({"characters": [{"name": "林舟", "aliases": {}}]}, allow_unicode=True),
        encoding="utf-8",
    )
    (root / "worldbook.yaml").write_text(
        yaml.safe_dump({"facts": ["蓝皮册子：会改写记录"]}, allow_unicode=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(workbench, "_book_dir", lambda _book: root)
    return root


def test_plan_confirm_reports_missing_people_and_worldbook_without_blocking(book: Path) -> None:
    characters_before = (book / "characters.yaml").read_bytes()
    worldbook_before = (book / "worldbook.yaml").read_bytes()

    snapshot = workbench.save_planning_body(
        "book", 1,
        {"content": _plan(people="林舟、苏遥、陌生人", setting="蓝皮册子、红木匣"), "base_sha": "", "confirm": True},
    )

    assert (book / "logs/ch1/planning.md").read_text(encoding="utf-8").startswith("status: 已批")
    notice = snapshot["planning_asset_notice"]
    assert notice["blocking"] is False
    assert notice["character_names"] == ["苏遥", "陌生人"]
    assert notice["worldbook_names"] == ["红木匣"]
    assert "这一章点到 2 个名字没有人物卡：苏遥、陌生人" in notice["message"]
    assert "1 个设定在世界观里查不到：红木匣" in notice["message"]
    assert "也可以就这么写" in notice["message"]
    assert (book / "characters.yaml").read_bytes() == characters_before
    assert (book / "worldbook.yaml").read_bytes() == worldbook_before


def test_plan_confirm_has_no_missing_notice_when_all_assets_exist(book: Path) -> None:
    snapshot = workbench.save_planning_body(
        "book", 1,
        {"content": _plan(people="林舟", setting="蓝皮册子"), "base_sha": "", "confirm": True},
    )

    notice = snapshot["planning_asset_notice"]
    assert notice["character_names"] == []
    assert notice["worldbook_names"] == []
    assert notice["message"] == ""
    assert notice["character_check"] == "checked"
    assert notice["worldbook_check"] == "checked"


def test_plan_without_structured_fields_is_unchecked_and_does_not_guess(book: Path) -> None:
    narrative = "林舟和苏遥拿着蓝皮册子走进旧书店。\n\n" + CHECKLIST

    snapshot = workbench.save_planning_body(
        "book", 1, {"content": narrative, "base_sha": "", "confirm": True},
    )

    notice = snapshot["planning_asset_notice"]
    assert notice["character_check"] == "unchecked"
    assert notice["worldbook_check"] == "unchecked"
    assert notice["character_names"] == [] and notice["worldbook_names"] == []
    assert "没有结构化人物/设定清单，本次未核" in notice["message"]


def test_unconfirmed_plan_does_not_show_asset_notice(book: Path) -> None:
    snapshot = workbench.save_planning_body(
        "book", 1,
        {"content": _plan(people="林舟、苏遥", setting="蓝皮册子、红木匣"), "base_sha": "", "confirm": False},
    )

    notice = snapshot["planning_asset_notice"]
    assert notice["message"] == ""
    assert notice["character_check"] == "not_applicable"
    assert notice["worldbook_check"] == "not_applicable"


def test_workbench_renders_plan_notice_without_disabling_confirmation() -> None:
    script = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")

    assert "planning_asset_notice" in script
    function_body = script.split("function renderPlanningAssetNotice", 1)[1].split("async function", 1)[0]
    assert "message" in function_body
    assert ".disabled" not in function_body
