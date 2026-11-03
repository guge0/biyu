"""S-4A — 确认闸(confirmations.py)单测:登记/列表/确认/取消流转。

零烧钱,纯本地 JSONL。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from biyu.agent.confirmations import RUN_ACTION_IDS, PendingActionError, PendingActionStore


@pytest.fixture
def store(tmp_path: Path) -> PendingActionStore:
    return PendingActionStore(tmp_path)


def test_add_persists_full_record(store: PendingActionStore, tmp_path: Path):
    record = store.add(book="书A", chapter=3, action_id="write", session_id="s1")
    assert record == {
        "id": record["id"],
        "session_id": "s1",
        "book": "书A",
        "chapter": 3,
        "action_id": "write",
        "estimate": "按本书历史记录预估",
        "status": "pending",
        "created_at": record["created_at"],
    }
    # 落在约定路径
    path = tmp_path / "书A" / "consults" / "pending_actions.jsonl"
    assert path.exists()
    # 新实例读回同一份数据
    assert PendingActionStore(tmp_path).list_actions(book="书A") == [record]


def test_add_rejects_non_run_action(store: PendingActionStore):
    for action_id in ("approve_planning", "revoke_planning", "approve_chapter", "adopt", "shell", "rm"):
        with pytest.raises(PendingActionError):
            store.add(book="书A", chapter=1, action_id=action_id)


def test_add_rejects_traversal_book(store: PendingActionStore):
    with pytest.raises(PendingActionError):
        store.add(book="../别的书", chapter=1, action_id="write")


def test_run_action_ids_match_registry(store: PendingActionStore):
    from biyu.ui.action_registry import action_for

    assert RUN_ACTION_IDS == ("write", "rewrite", "review", "diagnose")
    for action_id in RUN_ACTION_IDS:  # 且都真实存在于 action_registry
        action_for(action_id, book="书A", chapter=1)


def test_confirm_flow(store: PendingActionStore):
    record = store.add(book="书A", chapter=2, action_id="review")
    confirmed = store.mark(record["id"], "confirmed")
    assert confirmed["status"] == "confirmed"
    # 已确认的不能再取消/再确认
    with pytest.raises(PendingActionError):
        store.mark(record["id"], "cancelled")
    with pytest.raises(PendingActionError):
        store.mark(record["id"], "confirmed")


def test_cancel_flow(store: PendingActionStore):
    record = store.add(book="书A", chapter=2, action_id="diagnose")
    cancelled = store.mark(record["id"], "cancelled")
    assert cancelled["status"] == "cancelled"
    with pytest.raises(PendingActionError):
        store.mark(record["id"], "confirmed")


def test_mark_rejects_bad_target_status(store: PendingActionStore):
    record = store.add(book="书A", chapter=2, action_id="write")
    with pytest.raises(PendingActionError):
        store.mark(record["id"], "pending")


def test_mark_missing_id_raises_lookup_error(store: PendingActionStore):
    with pytest.raises(LookupError):
        store.mark("pa-19700101-deadbeef", "cancelled")
    assert store.get("pa-19700101-deadbeef") is None


def test_list_filters_and_scans_all_books(store: PendingActionStore):
    store.add(book="书A", chapter=1, action_id="write")
    store.add(book="书B", chapter=2, action_id="review")
    cancelled = store.add(book="书A", chapter=5, action_id="diagnose")
    store.mark(cancelled["id"], "cancelled")

    assert len(store.list_actions()) == 3
    assert len(store.list_actions(book="书A")) == 2
    assert [r["action_id"] for r in store.list_actions(book="书A", status="pending")] == ["write"]
    assert [r["action_id"] for r in store.list_actions(status="cancelled")] == ["diagnose"]


def test_id_unique_per_record(store: PendingActionStore):
    first = store.add(book="书A", chapter=1, action_id="write")
    second = store.add(book="书A", chapter=1, action_id="write")
    assert first["id"] != second["id"]
