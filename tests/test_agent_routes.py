"""S-4A — /api/agent/* 路由测试(TestClient + FakeAdapter,零真实调用)。

覆盖:建会话(role=agent)、SSE 事件顺序与会话历史落盘(含工具调用)、
待确认列表/确认/取消流转、无 Key 人话错误、非 agent 会话拒绝、路径穿越 400。
confirm 复用 cli_executor 的调用通过 monkeypatch 假执行器验证(不起子进程)。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from biyu.llm.base import LLMResponse
from biyu.ui.app import app

from tests.test_agent_tools import make_book


class FakeAdapter:
    def __init__(self, script: list):
        self.script = list(script)
        self.model_name = "fake-model"
        self.max_tokens = 1000
        self.calls: list[tuple[list[dict], dict]] = []

    async def generate(self, messages, **kwargs):
        self.calls.append(([dict(m) for m in messages], dict(kwargs)))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def resp(text="", tool_calls=None, cost=0.0):
    return LLMResponse(text=text, model="fake", cost=cost, tool_calls=tool_calls)


def tc(name: str, arguments: str, call_id: str = "call_1"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


@pytest.fixture(autouse=True)
def _zebian_enabled(monkeypatch: pytest.MonkeyPatch):
    """S-7a 责编开关内测默认关;本文件测的全是开关打开时的引擎行为。"""
    monkeypatch.setattr("biyu.ui.agent_routes.feature_enabled", lambda _name: True)


@pytest.fixture
def tmp_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    make_book(tmp_path)
    monkeypatch.setattr("biyu.config.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.web.routes.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.ui.routes.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.ui.agent_routes.get_data_root", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def client(tmp_data_root: Path) -> TestClient:
    return TestClient(app)


def parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if block.startswith("data: "):
            payload = block[len("data: "):]
            if payload == "[DONE]":
                break
            events.append(json.loads(payload))
    return events


def use_adapter(client: TestClient, monkeypatch: pytest.MonkeyPatch, script: list) -> FakeAdapter:
    adapter = FakeAdapter(script)
    monkeypatch.setattr("biyu.ui.agent_routes._get_chat_adapter", lambda: adapter)
    return adapter


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------


def test_create_agent_session(client: TestClient):
    created = client.post("/api/agent/sessions", json={"book": "MyBook"})
    assert created.status_code == 200
    meta = created.json()
    assert meta["role"] == "agent"
    assert meta["book"] == "MyBook"
    assert meta["book_id"] == "mb-1"


def test_create_agent_session_by_book_id(client: TestClient):
    created = client.post("/api/agent/sessions", json={"book": "mb-1"})
    assert created.status_code == 200
    assert created.json()["book"] == "MyBook"


def test_create_agent_session_rejects_traversal(client: TestClient):
    for bad in ("../evil", "a/b"):
        resp_ = client.post("/api/agent/sessions", json={"book": bad})
        assert resp_.status_code == 400


def test_message_rejects_non_agent_session(client: TestClient):
    created = client.post(
        "/api/chat/sessions", json={"book": "MyBook", "role": "editor"},
    )
    sid = created.json()["id"]
    resp_ = client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "你好"})
    assert resp_.status_code == 400


def test_message_unknown_session_404(client: TestClient):
    resp_ = client.post("/api/agent/sessions/nope/messages", json={"content": "你好"})
    assert resp_.status_code == 404


# ---------------------------------------------------------------------------
# 消息 SSE:事件顺序 + 历史落盘
# ---------------------------------------------------------------------------


def test_message_sse_event_order_and_history(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_data_root: Path):
    use_adapter(client, monkeypatch, [
        resp(tool_calls=[tc("read_chapter", '{"chapter": 1}', "call_a")], cost=0.5),
        resp(text="第一章:林砚推门。", cost=0.25),
    ])
    sid = client.post("/api/agent/sessions", json={"book": "MyBook"}).json()["id"]

    resp_ = client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "第 1 章讲了什么"})
    assert resp_.status_code == 200
    assert "text/event-stream" in resp_.headers.get("content-type", "")
    events = parse_sse(resp_.text)
    assert [e["type"] for e in events] == [
        "tool_start", "tool_result", "text", "done",
    ]
    assert events[-1]["cost"] == 0.75

    # 会话历史(含工具调用)写入 JSONL
    session = client.get(f"/api/chat/sessions/{sid}").json()
    roles = [m["role"] for m in session["messages"]]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assistant_tools = session["messages"][1]
    assert assistant_tools["tool_call"]["tool_calls"][0]["function"]["name"] == "read_chapter"
    tool_row = session["messages"][2]
    assert tool_row["tool_call"]["tool_call_id"] == "call_a"
    assert "林砚推门进来" in tool_row["content"]
    final = session["messages"][3]
    assert final["content"] == "第一章:林砚推门。"
    assert final["cost"] == 0.75


def test_message_sse_pending_action_event(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    use_adapter(client, monkeypatch, [
        resp(tool_calls=[tc("request_write", '{"chapter": 4}')]),
        resp(text="已提交。"),
    ])
    sid = client.post("/api/agent/sessions", json={"book": "MyBook"}).json()["id"]
    resp_ = client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "写第 4 章"})
    events = parse_sse(resp_.text)
    assert [e["type"] for e in events] == [
        "tool_start", "pending_action", "tool_result", "text", "done",
    ]
    pending = events[1]
    assert pending["action_id"] == "write"
    assert pending["status"] == "pending"
    assert pending["session_id"] == sid

    listed = client.get("/api/agent/pending", params={"book": "MyBook"}).json()["pending"]
    assert len(listed) == 1 and listed[0]["chapter"] == 4


def test_message_sse_error_humanized(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from biyu.llm.glm import LLMError

    use_adapter(client, monkeypatch, [LLMError(401, "Authentication Fails")])
    sid = client.post("/api/agent/sessions", json={"book": "MyBook"}).json()["id"]
    resp_ = client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "你好"})
    events = parse_sse(resp_.text)
    assert [e["type"] for e in events] == ["error"]
    assert "API Key 无效或已过期" in events[0]["message"]


def test_message_sse_no_adapter_humanized(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("biyu.ui.agent_routes._get_chat_adapter", lambda: None)
    sid = client.post("/api/agent/sessions", json={"book": "MyBook"}).json()["id"]
    resp_ = client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "你好"})
    events = parse_sse(resp_.text)
    assert [e["type"] for e in events] == ["error"]
    assert "没有可用的模型连接" in events[0]["message"]


def test_history_replayed_with_tool_messages(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """上一轮的工具调用历史,下一轮要原样(assistant.tool_calls + role=tool)发给模型。"""
    adapter = use_adapter(client, monkeypatch, [
        resp(tool_calls=[tc("read_chapter", '{"chapter": 1}', "call_a")]),
        resp(text="看完了。"),
        resp(text="继续聊。"),
    ])
    sid = client.post("/api/agent/sessions", json={"book": "MyBook"}).json()["id"]
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "读第 1 章"})
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "然后呢"})

    messages = adapter.calls[-1][0]
    roles = [m["role"] for m in messages]
    assert roles[:2] == ["system", "user"]
    assert roles.count("assistant") >= 2
    assert roles.count("tool") == 1
    assistant_with_calls = [m for m in messages if m.get("tool_calls")]
    assert assistant_with_calls[-1]["tool_calls"][0]["id"] == "call_a"
    tool_msg = [m for m in messages if m["role"] == "tool"][-1]
    assert tool_msg["tool_call_id"] == "call_a"


# ---------------------------------------------------------------------------
# 待确认动作
# ---------------------------------------------------------------------------


def _create_pending(client: TestClient, monkeypatch: pytest.MonkeyPatch, action_id: str = "write") -> dict:
    use_adapter(client, monkeypatch, [
        resp(tool_calls=[tc(f"request_{action_id}", '{"chapter": 2}')]),
        resp(text="已提交。"),
    ])
    sid = client.post("/api/agent/sessions", json={"book": "MyBook"}).json()["id"]
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "安排"})
    listed = client.get("/api/agent/pending", params={"book": "MyBook"}).json()["pending"]
    assert len(listed) == 1
    return listed[0]


def test_pending_list_rejects_traversal(client: TestClient):
    assert client.get("/api/agent/pending", params={"book": "../x"}).status_code == 400
    assert client.get("/api/agent/pending", params={"book": "a/b"}).status_code == 400


def test_pending_status_filter(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    _create_pending(client, monkeypatch)
    assert len(client.get("/api/agent/pending", params={"book": "MyBook", "status": "pending"}).json()["pending"]) == 1
    assert len(client.get("/api/agent/pending", params={"book": "MyBook", "status": "confirmed"}).json()["pending"]) == 0


def test_confirm_reuses_cli_executor_path(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    record = _create_pending(client, monkeypatch, action_id="diagnose")

    captured: dict = {}

    async def fake_execute(action_id, *, book, chapter, confirmed, extra):
        captured.update(action_id=action_id, book=book, chapter=chapter,
                        confirmed=confirmed, extra=extra)
        yield {"type": "started", "run_id": "run-1"}
        yield {"type": "done", "returncode": 0, "run_id": "run-1"}

    monkeypatch.setattr("biyu.ui.agent_routes.execute", fake_execute)
    resp_ = client.post(f"/api/agent/pending/{record['id']}/confirm")
    assert resp_.status_code == 200
    events = parse_sse(resp_.text)
    assert [e["type"] for e in events] == ["started", "done"]
    # 复用现有执行路径:动作/书/章一致,confirmed=True
    assert captured == {
        "action_id": "diagnose", "book": "MyBook", "chapter": 2,
        "confirmed": True, "extra": {},
    }
    # 状态已流转
    listed = client.get("/api/agent/pending", params={"book": "MyBook"}).json()["pending"]
    assert listed[0]["status"] == "confirmed"
    # 已确认的不能再确认/取消
    assert client.post(f"/api/agent/pending/{record['id']}/confirm").status_code == 409
    assert client.post(f"/api/agent/pending/{record['id']}/cancel").status_code == 409


def test_cancel_flow(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    record = _create_pending(client, monkeypatch)
    resp_ = client.post(f"/api/agent/pending/{record['id']}/cancel")
    assert resp_.status_code == 200
    assert resp_.json()["action"]["status"] == "cancelled"
    listed = client.get("/api/agent/pending", params={"book": "MyBook"}).json()["pending"]
    assert listed[0]["status"] == "cancelled"


def test_confirm_missing_404(client: TestClient):
    assert client.post("/api/agent/pending/pa-19700101-deadbeef/confirm").status_code == 404
    assert client.post("/api/agent/pending/pa-19700101-deadbeef/cancel").status_code == 404


def test_chat_keyword_router_untouched(client: TestClient):
    """现有 /api/chat/* 关键词路由不受影响(占位模式仍走 chat_tools)。"""
    sid = client.post("/api/chat/sessions", json={"book": "MyBook", "role": "editor"}).json()["id"]
    resp_ = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "看下人物 林砚"})
    assert resp_.status_code == 200
    assert parse_sse(resp_.text)  # 仍有事件流
