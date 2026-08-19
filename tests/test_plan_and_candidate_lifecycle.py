from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_plan_versions_are_durable_and_can_be_selected(tmp_path: Path) -> None:
    from biyu.ui.workbench_versions import (
        current_plan_version,
        list_plan_versions,
        save_plan_version,
        select_plan_version,
    )

    assert save_plan_version(tmp_path, 1, "方案甲") == 1
    assert save_plan_version(tmp_path, 1, "方案乙") == 2
    assert save_plan_version(tmp_path, 1, "方案甲") == 1
    assert current_plan_version(tmp_path, 1) == 1
    assert [item["version"] for item in list_plan_versions(tmp_path, 1)] == [2, 1]

    select_plan_version(tmp_path, 1, 2)
    assert current_plan_version(tmp_path, 1) == 2
    assert (tmp_path / "logs/ch1/planning.md").read_text(encoding="utf-8") == "status: 已批\n方案乙"


def test_candidate_cards_record_plan_and_use_the_right_comparison_base(tmp_path: Path) -> None:
    from biyu.ui.workbench_versions import (
        list_candidate_versions,
        save_plan_version,
        snapshot_candidate,
    )

    save_plan_version(tmp_path, 1, "方案一")
    _write(tmp_path / "chapters/_pending/ch1.md", "甲乙丙")
    snapshot_candidate(tmp_path, 1, run_id="run-1", action="write")
    first = list_candidate_versions(tmp_path, 1)[0]
    assert first["from_plan"] == 1
    assert first["compare"] is None  # 新章第一版没有空基准比较

    _write(tmp_path / "chapters/_pending/ch1.md", "甲乙丙丁戊")
    snapshot_candidate(tmp_path, 1, run_id="run-2", action="rewrite")
    second = list_candidate_versions(tmp_path, 1)[0]
    assert second["compare"] == {"label": "第 1 版", "delta": 2}

    other = tmp_path / "other"
    _write(other / "chapters/ch1.md", "正式稿")
    _write(other / "chapters/_pending/ch1.md", "重写正式稿")
    snapshot_candidate(other, 1, run_id="run-3", action="write")
    assert list_candidate_versions(other, 1)[0]["compare"]["label"] == "正式稿"


def test_candidate_recycle_restore_and_confirmed_permanent_delete(tmp_path: Path) -> None:
    from biyu.ui.workbench_versions import (
        discard_current_candidate,
        list_candidate_versions,
        list_trash,
        purge_trash,
        restore_trash,
        snapshot_candidate,
    )

    _write(tmp_path / "chapters/_pending/ch1.md", "候选稿")
    snapshot_candidate(tmp_path, 1, run_id="run-1", action="write")
    entry = discard_current_candidate(tmp_path, 1)
    assert not (tmp_path / "chapters/_pending/ch1.md").exists()
    assert list_candidate_versions(tmp_path, 1)[0]["state"] == "trash"
    assert list_trash(tmp_path, 1)[0]["id"] == entry["id"]

    restore_trash(tmp_path, 1, entry["id"])
    assert (tmp_path / "chapters/_pending/ch1.md").read_text(encoding="utf-8") == "候选稿"
    assert list_candidate_versions(tmp_path, 1)[0]["state"] == "current"

    second = discard_current_candidate(tmp_path, 1)
    purge_trash(tmp_path, 1, second["id"])
    assert list_trash(tmp_path, 1) == []


def test_old_official_is_visible_in_recycle_bin_and_can_be_restored(tmp_path: Path) -> None:
    from biyu.ui.workbench_versions import list_trash, restore_trash

    _write(tmp_path / "chapters/ch1.md", "当前正式稿")
    recycled = _write(tmp_path / "logs/ch1/trash/official_20260723.md", "旧正式稿")
    entries = list_trash(tmp_path, 1)
    assert entries[0]["kind"] == "official"
    assert restore_trash(tmp_path, 1, recycled.stem) == "official"
    assert (tmp_path / "chapters/ch1.md").read_text(encoding="utf-8") == "旧正式稿"
    assert any(path.read_text(encoding="utf-8") == "当前正式稿" for path in (tmp_path / "logs/ch1/trash").glob("official_*_restore.md"))


def test_recycle_bin_expires_after_thirty_days(tmp_path: Path) -> None:
    from biyu.ui.workbench_versions import cleanup_expired_trash

    trash = tmp_path / "logs/ch1/trash"
    _write(trash / "old.md", "旧稿")
    _write(
        trash / "old.json",
        json.dumps({
            "id": "old",
            "kind": "candidate",
            "deleted_at": (datetime.now(timezone.utc) - timedelta(days=31)).isoformat(),
            "content_path": "old.md",
        }),
    )
    assert cleanup_expired_trash(tmp_path, 1) == 1
    assert not (trash / "old.json").exists()
    assert not (trash / "old.md").exists()


def test_excerpt_recycle_can_restore_or_permanently_remove(tmp_path: Path) -> None:
    import biyu.ui.workbench as wb

    original = {"id": "quote-1", "type": "good", "text": "这一句很好", "status": "候选"}
    tombstone = {"id": "trash-1", "tombstone_for": "quote-1", "status": "回收站", "created_at": datetime.now(timezone.utc).isoformat(), "snapshot": original}
    path = _write(tmp_path / "样本库/正例候选.md", "- " + json.dumps(original, ensure_ascii=False) + "\n- " + json.dumps(tombstone, ensure_ascii=False) + "\n")
    assert wb._sample_entries(path.read_text(encoding="utf-8")) == []
    assert wb._excerpt_trash_with_expiry(tmp_path)[0]["text"] == "这一句很好"

    wb._restore_excerpt(tmp_path, "trash-1")
    assert [item["id"] for item in wb._sample_entries(path.read_text(encoding="utf-8"))] == ["quote-1"]

    path.write_text("- " + json.dumps(original, ensure_ascii=False) + "\n- " + json.dumps(tombstone, ensure_ascii=False) + "\n", encoding="utf-8")
    wb._purge_excerpt(tmp_path, "trash-1")
    assert "这一句很好" not in path.read_text(encoding="utf-8")


def test_author_ui_has_no_git_or_old_delete_euphemism() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
    author_ui = html + js
    assert "历史记录仍保留" not in author_ui
    assert "Git" not in author_ui
    assert "回收站保留 30 天" in author_ui
    assert "purgeTrash" not in author_ui


def test_issue_and_excerpt_anchors_are_wired_both_directions() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
    assert "completed-check-list" in html
    assert "function focusAnchor" in js
    assert "container.scrollTo(" in js
    assert "scrollIntoView" not in js
    assert "selectedAnchor" in js
    assert "anchor:String(selectedAnchor)" in js
