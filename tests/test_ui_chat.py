"""T1 会话基座(P8-M3):会话持久化 JSONL + CRUD + API + 成本累计。

Spec(specs/P8-M3.md line 10):
   会话持久化(补 B4 缺口)——逐消息 JSONL 落
   data/<书>/consults/<会话id>.jsonl(role / content / tool_call / cost / ts);
   会话列表、断点续聊、软删除;会话级成本累计接现有护栏。

预答决策:
   - 会话存储 = JSONL + 纪要 md,不引数据库
   - 会话 id = 日期 + 短随机

零烧钱,纯逻辑测试。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from biyu.ui.app import app
from biyu.ui.chat import ChatManager


@pytest.fixture
def chat_mgr(tmp_path: Path) -> ChatManager:
    """ChatManager 挂载 tmp 数据根,测试间隔离。"""
    data_root = tmp_path / "data"
    data_root.mkdir()
    return ChatManager(data_root=data_root)


# ---------------------------------------------------------------------------
# 新建会话
# ---------------------------------------------------------------------------


def test_new_session_returns_valid_id(chat_mgr: ChatManager):
    """新建会话返有效 session_id(含日期 + 短随机,无路径穿越字符)。"""
    sid = chat_mgr.new_session("BookA", "editor")
    assert sid, "session_id 不应为空"
    assert "/" not in sid, f"session_id 不应含路径分隔符:{sid!r}"
    assert sid.startswith(datetime.now(timezone.utc).strftime("%Y%m%d")), \
        f"session_id 应以日期开头:{sid!r}"


def test_new_session_creates_jsonl_file(chat_mgr: ChatManager):
    """JSONL 文件应创建在 data/<书>/consults/<sid>.jsonl。"""
    sid = chat_mgr.new_session("BookA", "editor")
    mgr_root = chat_mgr._data_root  # type: ignore[attr-defined]
    jsonl_path = mgr_root / "BookA" / "consults" / f"{sid}.jsonl"
    assert jsonl_path.exists(), f"JSONL 文件未创建:{jsonl_path}"
    assert jsonl_path.read_text(encoding="utf-8") == "", "新会话 JSONL 应为空"


def test_new_session_stores_metadata(chat_mgr: ChatManager):
    """会话元数据(book / role / created_at / deleted)可检索。"""
    sid = chat_mgr.new_session("BookB", "director")
    session = chat_mgr.get_session(sid)
    assert session["book"] == "BookB"
    assert session["role"] == "director"
    assert "created_at" in session
    assert session["deleted"] is False


# ---------------------------------------------------------------------------
# 消息持久化
# ---------------------------------------------------------------------------


def test_add_message_appends_to_jsonl(chat_mgr: ChatManager):
    """逐消息追加 JSONL,role/content/ts 字段齐全。"""
    sid = chat_mgr.new_session("BookA", "editor")
    msg = chat_mgr.add_message(sid, "user", "你好")
    assert msg["role"] == "user"
    assert msg["content"] == "你好"
    assert "ts" in msg

    # 读 JSONL 确认
    mgr_root = chat_mgr._data_root
    lines = (mgr_root / "BookA" / "consults" / f"{sid}.jsonl") \
        .read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["role"] == "user"
    assert entry["content"] == "你好"


def test_add_message_retrieval(chat_mgr: ChatManager):
    """多条消息可完整召回,顺序不乱。"""
    sid = chat_mgr.new_session("BookA", "editor")
    chat_mgr.add_message(sid, "user", "q1")
    chat_mgr.add_message(sid, "assistant", "a1")
    chat_mgr.add_message(sid, "user", "q2")

    session = chat_mgr.get_session(sid)
    msgs = session["messages"]
    assert len(msgs) == 3
    assert msgs[0]["content"] == "q1"
    assert msgs[1]["content"] == "a1"
    assert msgs[2]["content"] == "q2"


def test_add_message_with_tool_call(chat_mgr: ChatManager):
    """消息可附带 tool_call 信息。"""
    sid = chat_mgr.new_session("BookA", "editor")
    tc = {"name": "look_up_truth", "args": {"key": "陈凡"}, "result": "虚构角色"}
    chat_mgr.add_message(sid, "assistant", "查到:陈凡", tool_call=tc)
    msgs = chat_mgr.get_session(sid)["messages"]
    assert msgs[0]["tool_call"] == tc


def test_add_message_with_cost(chat_mgr: ChatManager):
    """消息可附带 cost 信息。"""
    sid = chat_mgr.new_session("BookA", "editor")
    chat_mgr.add_message(sid, "assistant", "ok", cost=0.05)
    msgs = chat_mgr.get_session(sid)["messages"]
    assert msgs[0]["cost"] == 0.05


# ---------------------------------------------------------------------------
# 会话列表
# ---------------------------------------------------------------------------


def test_list_sessions_by_book(chat_mgr: ChatManager):
    """list_sessions(book) 只返该书的会话。"""
    chat_mgr.new_session("BookA", "editor")
    chat_mgr.new_session("BookB", "director")
    chat_mgr.new_session("BookA", "naming")

    book_a = chat_mgr.list_sessions("BookA")
    assert len(book_a) == 2
    for s in book_a:
        assert s["book"] == "BookA"

    all_ = chat_mgr.list_sessions()
    assert len(all_) == 3


def test_list_sessions_excludes_deleted(chat_mgr: ChatManager):
    """软删除的会话不出现在 list_sessions 结果中。"""
    sid = chat_mgr.new_session("BookA", "editor")
    chat_mgr.new_session("BookA", "editor")
    chat_mgr.soft_delete(sid)

    sessions = chat_mgr.list_sessions("BookA")
    assert len(sessions) == 1
    assert sessions[0]["id"] != sid


def test_list_sessions_ordered_by_created_at(chat_mgr: ChatManager):
    """会话列表按创建时间降序(最新在前)。"""
    s1 = chat_mgr.new_session("BookA", "editor")
    s2 = chat_mgr.new_session("BookA", "director")
    s3 = chat_mgr.new_session("BookA", "editor")
    sessions = chat_mgr.list_sessions("BookA")
    ids = [s["id"] for s in sessions]
    # 默认创建顺序 1→2→3 → 降序: 3,2,1
    assert ids == [s3, s2, s1], f"应最新在前:{ids}"


def test_list_sessions_book_branch_uses_meta_created_at_not_mtime(
    chat_mgr: ChatManager,
) -> None:
    """book 分支排序须基于 meta.created_at(time.time 微秒精度),
    不能靠文件 mtime(秒级精度 → 同秒创建会话排序歧义 = flaky)。

    治:tests/test_ui_chat.py::test_list_sessions_ordered_by_created_at 全套 run 时偶发 fail。
    根因:chat.py book 分支用 f.stat().st_mtime 排序,与 docstring "按创建时间降序" 不符。
    其他两个分支(book_id / 无 book)已用 meta.created_at,本测试让 book 分支对齐。
    """
    import os
    import time as _time

    s1 = chat_mgr.new_session("BookA", "editor")
    s2 = chat_mgr.new_session("BookA", "director")
    s3 = chat_mgr.new_session("BookA", "editor")

    # 强制三个会话 .json 文件 mtime 同值(模拟同秒创建,暴露 mtime 排序的歧义)
    consults_dir = chat_mgr._consults_dir("BookA")
    fixed = _time.time()
    for f in consults_dir.glob("*.json"):
        os.utime(f, (fixed, fixed))

    sessions = chat_mgr.list_sessions("BookA")
    ids = [s["id"] for s in sessions]
    assert ids == [s3, s2, s1], (
        f"book 分支应按 meta.created_at 降序(微秒精度),"
        f"不该靠文件 mtime(秒级精度→歧义): {ids}"
    )


def test_new_session_created_at_strictly_increasing(chat_mgr: ChatManager) -> None:
    """同进程内连续 new_session 的 meta.created_at 须严格递增。

    治 flaky 根因 #2:Windows 默认 time.time() 精度可能 ~15ms,
    三次紧挨着的 new_session 调用可能落在同精度窗口 → created_at 同值
    → list_sessions 排序仍歧义(即便用 created_at 排序,id tiebreaker 是随机的与顺序无关)。
    保证严格递增 → 排序稳定。
    """
    s1 = chat_mgr.new_session("BookA", "editor")
    s2 = chat_mgr.new_session("BookA", "editor")
    s3 = chat_mgr.new_session("BookA", "editor")
    m1 = chat_mgr.get_session(s1)["created_at"]
    m2 = chat_mgr.get_session(s2)["created_at"]
    m3 = chat_mgr.get_session(s3)["created_at"]
    assert m1 < m2 < m3, (
        f"created_at 应严格递增(治 Windows 时钟精度 flaky): {m1}, {m2}, {m3}"
    )


# ---------------------------------------------------------------------------
# 软删除
# ---------------------------------------------------------------------------


def test_soft_delete_marks_deleted(chat_mgr: ChatManager):
    """get_session 返 deleted=True,文件不删。"""
    sid = chat_mgr.new_session("BookA", "editor")
    chat_mgr.add_message(sid, "user", "留下证据")

    chat_mgr.soft_delete(sid)
    session = chat_mgr.get_session(sid)
    assert session["deleted"] is True
    assert len(session["messages"]) == 1  # 消息不丢

    # 文件还在
    jsonl = chat_mgr._data_root / "BookA" / "consults" / f"{sid}.jsonl"
    assert jsonl.exists(), "软删除不应删文件"


def test_soft_delete_idempotent(chat_mgr: ChatManager):
    """重复软删除不报错。"""
    sid = chat_mgr.new_session("BookA", "editor")
    chat_mgr.soft_delete(sid)
    chat_mgr.soft_delete(sid)  # 不应抛异常


# ---------------------------------------------------------------------------
# 会话成本
# ---------------------------------------------------------------------------


def test_session_cost_basic(chat_mgr: ChatManager):
    """会话累计成本 = 各消息 cost 之和。"""
    sid = chat_mgr.new_session("BookA", "editor")
    chat_mgr.add_message(sid, "assistant", "a", cost=0.03)
    chat_mgr.add_message(sid, "assistant", "b", cost=0.05)
    assert chat_mgr.get_session_cost(sid) == pytest.approx(0.08)


def test_session_cost_empty_session(chat_mgr: ChatManager):
    """无消息的会话成本 = 0。"""
    sid = chat_mgr.new_session("BookA", "editor")
    assert chat_mgr.get_session_cost(sid) == 0.0


def test_session_cost_none_cost_ignored(chat_mgr: ChatManager):
    """cost=None 的消息不计入成本。"""
    sid = chat_mgr.new_session("BookA", "editor")
    chat_mgr.add_message(sid, "user", "q")
    chat_mgr.add_message(sid, "assistant", "a", cost=0.02)
    assert chat_mgr.get_session_cost(sid) == pytest.approx(0.02)


# ---------------------------------------------------------------------------
# 健壮性
# ---------------------------------------------------------------------------


def test_get_nonexistent_session_returns_none(chat_mgr: ChatManager):
    """不存在的 session_id 返 None,不崩。"""
    assert chat_mgr.get_session("nonexistent") is None
    assert chat_mgr.get_session_cost("nonexistent") == 0.0


def test_add_message_nonexistent_session(chat_mgr: ChatManager):
    """向不存在的会话加消息应抛异常。"""
    with pytest.raises(ValueError, match="not found"):
        chat_mgr.add_message("non_existent_sid", "user", "hello")


def test_soft_delete_nonexistent_session(chat_mgr: ChatManager):
    """删除不存在的会话应抛异常。"""
    with pytest.raises(ValueError, match="not found"):
        chat_mgr.soft_delete("non_existent_sid")


def test_book_name_with_special_chars(chat_mgr: ChatManager):
    """书名含特殊字符时应安全存储(不路径穿越)。"""
    sid = chat_mgr.new_session("../evil", "editor")
    session = chat_mgr.get_session(sid)
    assert session["book"] == "../evil"
    # 验证文件路径:目录名即使含 ../ 也应被安全处理
    jsonl = chat_mgr._data_root / "../evil" / "consults" / f"{sid}.jsonl"
    # 预期:路径被安全化
    actual_jsonl = chat_mgr._data_root / "evil" / "consults" / f"{sid}.jsonl"
    assert not jsonl.exists()  # 不穿越到上级
    assert actual_jsonl.exists() or not any(
        (chat_mgr._data_root / d / "consults" / f"{sid}.jsonl").exists()
        for d in ("evil", "safe")
    ), "特殊字符应被安全处理"


# ===================================================================
# API 端点测试 (TestClient)
# ===================================================================


@pytest.fixture
def tmp_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Monkeypatch data_root → tmp_path,测试间隔离。"""
    monkeypatch.setattr("biyu.config.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.web.routes.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.ui.routes.get_data_root", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def client(tmp_data_root: Path) -> TestClient:
    """TestClient with isolated data_root。"""
    return TestClient(app)


# --- CRUD ---


def test_api_create_session(client: TestClient):
    """POST /api/chat/sessions 创建会话,返元数据。"""
    resp = client.post("/api/chat/sessions", json={"book": "BookA", "role": "editor"})
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["book"] == "BookA"
    assert data["role"] == "editor"


def test_api_list_sessions(client: TestClient):
    """GET /api/chat/sessions 列会话,支持 book 过滤。"""
    s1 = client.post("/api/chat/sessions", json={"book": "BookA", "role": "editor"}).json()
    client.post("/api/chat/sessions", json={"book": "BookA", "role": "director"}).json()
    client.post("/api/chat/sessions", json={"book": "BookB", "role": "editor"}).json()

    all_ = client.get("/api/chat/sessions").json()
    assert len(all_["sessions"]) == 3

    filtered = client.get("/api/chat/sessions?book=BookA").json()
    assert len(filtered["sessions"]) == 2


def test_api_get_session(client: TestClient):
    """GET /api/chat/sessions/{id} 返含消息列表的会话。"""
    created = client.post("/api/chat/sessions", json={"book": "BookA", "role": "editor"}).json()
    sid = created["id"]

    resp = client.get(f"/api/chat/sessions/{sid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == sid
    assert data["messages"] == []


def test_api_get_nonexistent_session_returns_404(client: TestClient):
    """不存在的 session_id → 404。"""
    resp = client.get("/api/chat/sessions/nonexistent")
    assert resp.status_code == 404


def test_api_soft_delete(client: TestClient):
    """DELETE → 软删除,会话不出现在列表但可单独检索。"""
    created = client.post("/api/chat/sessions", json={"book": "BookA", "role": "editor"}).json()
    sid = created["id"]

    resp = client.delete(f"/api/chat/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # 不出现在列表
    all_ = client.get("/api/chat/sessions").json()
    assert len(all_["sessions"]) == 0

    # 单独检索仍有 deleted 标记
    session = client.get(f"/api/chat/sessions/{sid}").json()
    assert session["deleted"] is True


def test_api_delete_nonexistent_returns_404(client: TestClient):
    """删除不存在的会话 → 404。"""
    resp = client.delete("/api/chat/sessions/nonexistent")
    assert resp.status_code == 404


# --- SSE 消息 ---


def _parse_sse(text: str) -> list[dict]:
    """把 SSE 文本切成事件列表。"""
    events: list[dict] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if block.startswith("data: "):
            payload = block[len("data: "):]
            if payload == "[DONE]":
                events.append({"_done_marker": True})
                continue
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                events.append({"_raw": payload})
    return events


def test_api_send_message_sse(client: TestClient):
    """POST .../messages 占位模式:回 token + tool_call + cost + done。"""
    created = client.post("/api/chat/sessions", json={"book": "BookA", "role": "editor"}).json()
    sid = created["id"]

    resp = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "你好"})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)

    assert any(e.get("type") == "token" for e in events), f"缺 token 事件:{events}"
    assert any(e.get("type") == "tool_call" for e in events), f"缺 tool_call 事件:{events}"
    assert any(e.get("type") == "cost" for e in events), f"缺 cost 事件:{events}"

    # 消息应持久化
    session = client.get(f"/api/chat/sessions/{sid}").json()
    msgs = session["messages"]
    assert len(msgs) == 2  # user + assistant
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "你好"


def test_api_send_message_no_session_404(client: TestClient):
    """不存在的 session 发消息 → 404。"""
    resp = client.post("/api/chat/sessions/nonexistent/messages", json={"content": "hi"})
    assert resp.status_code == 404
