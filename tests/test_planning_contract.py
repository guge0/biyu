"""④写章左栏契约：锁定状态与必检项以后端为准（整改清单 #1/#6）。"""
from __future__ import annotations

from pathlib import Path

from biyu.ui.workbench import _planning_contract

FULL = """status: 已批
source: 导演产出
## 本章方案
张今空夜巡与暗探交手。

## 必检项
**必须发生**
- 张今空与巡城司暗探正面接触
**必须不发生**
- 张今空不暴露回溯能力
**结尾状态**
- 钟楼报时比往常提前一刻
**信息层级**
- 读者知道暗探在试探；张今空只觉可疑
"""

PENDING_NO_CHECKLIST = "status: 待批\nsource: 作者手写\n本章方案：张今空夜巡与暗探交手。\n"


def test_unapproved_plan_is_not_locked_and_lists_missing_groups():
    # S-3C 截图 08/A04 的场景：方案有文字但没确认、没有必检项块。
    c = _planning_contract(PENDING_NO_CHECKLIST, PENDING_NO_CHECKLIST, "待批", has_draft=False, skipped=False)
    assert c["locked"] is False
    assert c["has_text"] is True
    assert c["missing"] == ["必须发生", "必须不发生", "结尾状态", "信息层级"]
    assert c["groups"] == []


def test_approved_plan_is_locked_and_items_are_plain_text():
    c = _planning_contract(FULL, FULL, "已批", has_draft=False, skipped=False)
    assert c["locked"] is True
    assert c["missing"] == []
    labels = [g["label"] for g in c["groups"]]
    assert labels == ["必须发生", "必须不发生", "结尾状态", "信息层级"]
    items = [item for g in c["groups"] for item in g["items"]]
    assert items[0] == "张今空与巡城司暗探正面接触"
    # 作者不再看到 markdown 标记
    assert not any("**" in item or item.startswith("- ") for item in items)


def test_locked_contract_shows_approved_version_not_pending_draft():
    draft = FULL.replace("status: 已批", "status: 待批").replace("正面接触", "在茶楼偶遇")
    c = _planning_contract(FULL, draft, "已批", has_draft=True, skipped=False)
    assert c["locked"] is True
    assert c["has_draft"] is True
    assert c["groups"][0]["items"] == ["张今空与巡城司暗探正面接触"]


def test_no_plan_text_is_not_locked():
    c = _planning_contract("", "", "无", has_draft=False, skipped=False)
    assert c["locked"] is False
    assert c["has_text"] is False
    assert c["missing"] == []


def test_skipped_director_counts_as_locked():
    c = _planning_contract("", "", "无", has_draft=False, skipped=True)
    assert c["locked"] is True
    assert c["skipped"] is True


def test_frontend_no_longer_infers_lock_from_plan_text():
    js = (Path(__file__).resolve().parents[1] / "src" / "biyu" / "ui" / "static" / "workbench.js").read_text(encoding="utf-8")
    assert "Boolean(current.planning || current.planning_skipped)" not in js
    assert "current.planning_contract" in js
