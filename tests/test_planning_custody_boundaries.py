from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from biyu.ui import workbench


VALID_PLAN = """# 第四章方案

## 必检项

**必须发生**
- 主角进入旧站

**必须不发生**
- 不揭晓幕后人

**结尾状态**
- 门在身后锁死

**信息层级**
- 主角只知道车站废弃
"""


@pytest.fixture
def plan_book(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    book = tmp_path / "j1"
    (book / "outlines").mkdir(parents=True)
    (book / "outlines" / "ch4.md").write_text("outline", encoding="utf-8")
    monkeypatch.setattr(workbench, "_book_dir", lambda _book: book)
    monkeypatch.setattr(workbench, "chapter_snapshot", lambda *_args: {"ok": True})
    return book


def test_author_can_create_save_and_confirm_planning(plan_book: Path) -> None:
    workbench.save_planning_body("j1", 4, {"content": VALID_PLAN, "base_sha": "", "confirm": False})
    path = plan_book / "logs" / "ch4" / "planning.md"
    draft = path.read_text(encoding="utf-8")
    assert draft.startswith("status: 待批\nsource: 作者手写\n")

    workbench.save_planning_body(
        "j1", 4,
        {"content": VALID_PLAN, "base_sha": workbench._sha(draft), "confirm": True},
    )
    approved = path.read_text(encoding="utf-8")
    assert approved.startswith("status: 已批\nsource: 作者手写\n")


def test_author_edit_of_director_plan_is_traced(plan_book: Path) -> None:
    path = plan_book / "logs" / "ch4" / "planning.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"status: 草稿\nsource: 导演产出\n{VALID_PLAN}", encoding="utf-8")
    original = path.read_text(encoding="utf-8")

    workbench.save_planning_body(
        "j1", 4,
        {"content": VALID_PLAN + "\n补充一个近景。", "base_sha": workbench._sha(original)},
    )
    assert "source: 作者改过" in path.read_text(encoding="utf-8")


def test_confirm_reports_missing_checklist_category_in_chinese(plan_book: Path) -> None:
    incomplete = VALID_PLAN.replace("**信息层级**\n- 主角只知道车站废弃\n", "")
    with pytest.raises(HTTPException) as caught:
        workbench.save_planning_body(
            "j1", 4, {"content": incomplete, "base_sha": "", "confirm": True},
        )
    assert caught.value.status_code == 409
    assert "信息层级" in str(caught.value.detail)
    assert not (plan_book / "logs" / "ch4" / "planning.md").exists()


def test_manual_plan_actions_do_not_require_director_file() -> None:
    actions = workbench._state_actions(
        "planning", "idle", stale=False, has_outline=True, has_planning=False,
    )
    assert actions["save_planning"]["enabled"] is True
    assert actions["approve_planning"]["enabled"] is True


def test_planning_source_legacy_and_explicit() -> None:
    assert workbench._planning_source("status: 草稿\n方案") == "导演产出"
    assert workbench._planning_source("status: 待批\nsource: 作者改过\n方案") == "作者改过"


def test_author_edit_of_approved_plan_stays_draft_until_confirmed(plan_book: Path) -> None:
    active = plan_book / "logs/ch4/planning.md"
    active.parent.mkdir(parents=True)
    active.write_text(f"status: 已批\nsource: 导演产出\n{VALID_PLAN}", encoding="utf-8")
    approved = active.read_text(encoding="utf-8")

    workbench.save_planning_body(
        "j1", 4,
        {"content": VALID_PLAN + "\n补充近景。", "base_sha": workbench._sha(approved)},
    )

    draft = plan_book / "logs/ch4/planning_draft.md"
    assert active.read_text(encoding="utf-8") == approved
    assert "补充近景" in draft.read_text(encoding="utf-8")

    workbench.save_planning_body(
        "j1", 4,
        {"content": VALID_PLAN + "\n补充近景。", "base_sha": workbench._sha(draft.read_text(encoding="utf-8")), "confirm": True},
    )
    assert "补充近景" in active.read_text(encoding="utf-8")
    assert not draft.exists()


def test_selecting_approved_plan_discards_unconfirmed_draft(plan_book: Path, monkeypatch) -> None:
    active = plan_book / "logs/ch4/planning.md"
    active.parent.mkdir(parents=True)
    active.write_text(f"status: 已批\nsource: 导演产出\n{VALID_PLAN}", encoding="utf-8")
    draft = plan_book / "logs/ch4/planning_draft.md"
    draft.write_text(f"status: 待批\nsource: 导演产出\n{VALID_PLAN}\n新稿", encoding="utf-8")
    monkeypatch.setattr(workbench, "select_plan_version", lambda *_args: VALID_PLAN)

    workbench.choose_plan_version("j1", 4, 1)

    assert not draft.exists()
