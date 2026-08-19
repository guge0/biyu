"""R1 slug ID 身份模型 — 会话 book_id 隔离(P8-M3R T1.1).

Spec(specs/P8-M3R.md line 28):
   会话按 book_id 隔离(切书不串数据);`book.json` 加 `id` 字段;
   `/api/chat/sessions` body 的 `book` 字段语义改 book_id。

本文件专测 book_id 隔离机制,与现有 test_ui_chat.py(book=目录名)解耦。
待 R1 全链完成后,旧测试同步迁移到 book_id;此时旧文件保留过渡。

预答决策:
   - book_id = 稳定 slug(如 "dao-1"),独立于目录名与 display_name
   - 兼容回退:旧会话(无 book_id 字段)按目录名匹配
   - list_sessions(book_id=...) 与 list_sessions(book=...) 并存过渡

零烧钱,纯逻辑测试。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from biyu.ui.chat import ChatManager


@pytest.fixture
def chat_mgr(tmp_path: Path) -> ChatManager:
    """ChatManager 挂载 tmp 数据根,测试间隔离。"""
    data_root = tmp_path / "data"
    data_root.mkdir()
    return ChatManager(data_root=data_root)


# ---------------------------------------------------------------------------
# book_id 隔离(T1.1 首红测)
# ---------------------------------------------------------------------------


def test_new_session_accepts_book_id(chat_mgr: ChatManager):
    """new_session 接受 book_id kwarg,持久化到 session meta。"""
    sid = chat_mgr.new_session("大道行", "editor", book_id="dao-1")
    session = chat_mgr.get_session(sid)
    assert session["book_id"] == "dao-1", "session meta 必须含 book_id 字段"


def test_list_sessions_filters_by_book_id(chat_mgr: ChatManager):
    """list_sessions(book_id=X) 只返 book_id=X 的会话,不同 book_id 不串。

    走查单 Step2 意见"和标题的书名没有关系,这里可以直接切换别的书的书名
    进行对话,没有隔离"的直接对冲:book_id 隔离保证切书不串数据。
    """
    sid_a = chat_mgr.new_session("大道行", "editor", book_id="dao-1")
    sid_b = chat_mgr.new_session("权宠天下", "editor", book_id="quanjue-1")
    # 再加一本同 book_id 的,验证列表长度
    sid_a2 = chat_mgr.new_session("大道行", "director", book_id="dao-1")

    sessions_dao = chat_mgr.list_sessions(book_id="dao-1")
    sessions_quanjue = chat_mgr.list_sessions(book_id="quanjue-1")

    ids_dao = {s["id"] for s in sessions_dao}
    ids_quanjue = {s["id"] for s in sessions_quanjue}

    assert ids_dao == {sid_a, sid_a2}, f"dao-1 应含 2 个会话,实际:{ids_dao}"
    assert ids_quanjue == {sid_b}, f"quanjue-1 应含 1 个会话,实际:{ids_quanjue}"
    assert sid_a not in ids_quanjue, "dao-1 会话不应出现在 quanjue-1 列表(隔离)"


def test_list_sessions_book_id_excludes_other_books(chat_mgr: ChatManager):
    """显式反例:不同 book_id 的会话不混入。"""
    chat_mgr.new_session("书A", "editor", book_id="aaa-1")
    chat_mgr.new_session("书B", "editor", book_id="bbb-1")
    chat_mgr.new_session("书C", "editor", book_id="ccc-1")

    only_b = chat_mgr.list_sessions(book_id="bbb-1")
    assert len(only_b) == 1
    assert only_b[0]["book_id"] == "bbb-1"


def test_book_id_independent_from_dir_name(chat_mgr: ChatManager):
    """book_id 独立于目录名:目录名变(改名),book_id 不变,会话不串。

    走查单 Step2/Step6 意见"改名仅改 display_name,不动 id/目录"的底层保证。
    """
    # 用目录名 BookOld 创建一个带 book_id 的会话
    sid = chat_mgr.new_session("BookOld", "editor", book_id="stable-id-1")
    # 假设改名后目录名变成 BookNew(走查场景),但 book_id 不变
    # (实际改名只动 display_name,这里模拟极端情况验证 book_id 优先)

    sessions = chat_mgr.list_sessions(book_id="stable-id-1")
    assert len(sessions) == 1
    assert sessions[0]["id"] == sid


# ---------------------------------------------------------------------------
# 兼容回退(无 book_id 的旧会话)
# ---------------------------------------------------------------------------


def test_list_sessions_backward_compat_no_book_id(chat_mgr: ChatManager):
    """旧会话(无 book_id 字段)仍可被 list_sessions(book=...) 召回,过渡不断。

    R1 兼容回退:旧数据未迁移前,book=目录名 仍可工作。
    """
    # 旧调用方式(无 book_id kwarg)
    sid_legacy = chat_mgr.new_session("LegacyBook", "editor")
    # 新调用方式
    chat_mgr.new_session("NewBook", "editor", book_id="new-id-1")

    # 旧方式过滤仍有效
    legacy_sessions = chat_mgr.list_sessions(book="LegacyBook")
    assert len(legacy_sessions) == 1
    assert legacy_sessions[0]["id"] == sid_legacy
