"""Tests for biyu.ui.routes POST /api/propose/stream — T3.2 SSE endpoint.

Spec line 11 — propose 按 stage(扫榜→套路→红蓝海→craft)进度可见。

覆盖:
- SSE 文本流:每帧 data: {...}\\n\\n
- 阶段事件:s scan / router / tropes / redblue / craft(依 SPECIFIC 路径触发)
- done 帧:含 final result,前端据此渲染卡片
- 失败状态:redblue 失败时事件 status=failed,sse 整体仍 200(不 4xx)
- 软顶拦截:SSE 第一帧 status=softcap_reached(直接回退,不进编排)
- on_progress 透传:orchestrator 异常时 SSE 错误帧
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from biyu.ui.app import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    """提供 TestClient + 新的 SessionCosts。"""
    from biyu.ui.session import SessionCosts
    from biyu.ui import routes as routes_mod

    fresh = SessionCosts(softcap=2.0)
    monkeypatch.setattr(routes_mod, "_costs", fresh)
    return TestClient(app)


def _read_sse(resp) -> str:
    """从 TestClient 流响应读完整 SSE 文本(stream 上下文里调)。"""
    return resp.read().decode("utf-8", errors="replace")


def _parse_sse(text: str) -> list[dict]:
    """把 SSE 文本切成事件列表。每帧之间用空行分隔;data: 前缀剥掉。"""
    events: list[dict] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        # 形如 "data: {...}" 或 "data: [DONE]"
        if block.startswith("data: "):
            payload = block[len("data: "):]
            if payload == "[DONE]":
                events.append({"_done_marker": True})
                continue
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                events.append({"_raw": payload})
        # 心跳 ": heartbeat" 忽略
    return events


# ---------------------------------------------------------------------------
# 正常 SPECIFIC 流:全 stage 事件 + done
# ---------------------------------------------------------------------------


def test_propose_stream_specific_returns_all_stages(client, monkeypatch):
    """mock orchestrator 触发所有 stage 事件(含 redblue),SSE 应推送完整序列。"""
    from biyu.ui import routes as routes_mod
    from biyu.ui.orchestrator import ProposeUiResult

    def fake_run(**kwargs):
        cb = kwargs.get("on_progress")
        if cb:
            cb({"stage": "scan", "status": "start"})
            cb({"stage": "scan", "status": "done"})
            cb({"stage": "router", "status": "start"})
            cb({"stage": "router", "status": "done", "cost_cny": 0.001, "decision": "specific"})
            cb({"stage": "tropes", "status": "start"})
            cb({"stage": "tropes", "status": "done", "cost_cny": 0.001})
            cb({"stage": "redblue", "status": "start"})
            cb({"stage": "redblue", "status": "done", "cost_cny": 0.001})
            cb({"stage": "craft", "status": "start"})
            cb({"stage": "craft", "status": "done", "cost_cny": 0.001})
        return ProposeUiResult(
            status="ok",
            path="specific",
            total_cost_cny=0.004,
            cumulative_cost_cny=0.004,
        )

    monkeypatch.setattr(routes_mod, "run_propose_for_ui", fake_run)
    with client.stream("POST", "/api/propose/stream", json={"idea": "x"}) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        text = _read_sse(resp)

    events = _parse_sse(text)
    stages = {e.get("stage") for e in events if isinstance(e, dict)}
    assert "scan" in stages
    assert "router" in stages
    assert "tropes" in stages
    assert "redblue" in stages
    assert "craft" in stages


def test_propose_stream_done_event_has_result(client, monkeypatch):
    """SSE 最后一帧(在 [DONE] 之前)应是 done type + 含 result。"""
    from biyu.ui import routes as routes_mod
    from biyu.ui.orchestrator import ProposeUiResult

    def fake_run(**kwargs):
        cb = kwargs.get("on_progress")
        if cb:
            cb({"stage": "scan", "status": "done"})
        return ProposeUiResult(
            status="ok", path="specific", total_cost_cny=0.01,
            cumulative_cost_cny=0.01,
        )

    monkeypatch.setattr(routes_mod, "run_propose_for_ui", fake_run)
    with client.stream("POST", "/api/propose/stream", json={"idea": "x"}) as resp:
        text = _read_sse(resp)

    events = _parse_sse(text)
    # 应该有 type=result 的帧(携带 ProposeUiResult 字段)
    result_events = [e for e in events if isinstance(e, dict) and e.get("type") == "result"]
    assert len(result_events) >= 1
    assert result_events[-1].get("status") == "ok"
    assert result_events[-1].get("path") == "specific"
    # 最后应是 [DONE]
    assert events[-1].get("_done_marker") is True


# ---------------------------------------------------------------------------
# 失败状态(D-70 出声)
# ---------------------------------------------------------------------------


def test_propose_stream_failure_event_passes_through(client, monkeypatch):
    """redblue failed 事件应透传到 SSE,前端据此渲染失败提示。"""
    from biyu.ui import routes as routes_mod
    from biyu.ui.orchestrator import ProposeUiResult

    def fake_run(**kwargs):
        cb = kwargs.get("on_progress")
        if cb:
            cb({"stage": "scan", "status": "done"})
            cb({"stage": "router", "status": "done"})
            cb({"stage": "tropes", "status": "done"})
            cb({"stage": "redblue", "status": "failed", "error": "simulated outage"})
            cb({"stage": "craft", "status": "done"})
        return ProposeUiResult(status="ok", path="specific", total_cost_cny=0.01)

    monkeypatch.setattr(routes_mod, "run_propose_for_ui", fake_run)
    with client.stream("POST", "/api/propose/stream", json={"idea": "x"}) as resp:
        assert resp.status_code == 200
        text = _read_sse(resp)

    events = _parse_sse(text)
    failed_events = [
        e for e in events
        if isinstance(e, dict) and e.get("status") == "failed"
    ]
    assert len(failed_events) >= 1
    assert "error" in failed_events[0]


def test_propose_stream_orchestrator_exception_returns_error_event(client, monkeypatch):
    """orchestrator 抛异常 → SSE 推 type=error 帧 + 一句人话,不 4xx。"""
    from biyu.ui import routes as routes_mod

    def boom(**kwargs):
        raise RuntimeError("registry outage")

    monkeypatch.setattr(routes_mod, "run_propose_for_ui", boom)
    with client.stream("POST", "/api/propose/stream", json={"idea": "x"}) as resp:
        assert resp.status_code == 200  # 不 4xx —— SSE 流不中断
        text = _read_sse(resp)

    events = _parse_sse(text)
    error_events = [
        e for e in events
        if isinstance(e, dict) and e.get("type") == "error"
    ]
    assert len(error_events) >= 1
    assert "message" in error_events[0] or "error" in error_events[0]


# ---------------------------------------------------------------------------
# 软顶拦截:SSE 流首帧 softcap_reached(不进编排)
# ---------------------------------------------------------------------------


def test_propose_stream_softcap_reached_short_circuits(client, monkeypatch):
    """软顶触发 → SSE 直接推 softcap 帧 + [DONE],不触发任何 stage 事件。"""
    from biyu.ui import routes as routes_mod
    from biyu.ui.orchestrator import ProposeUiResult

    def fake_run(**kwargs):
        cb = kwargs.get("on_progress")
        if cb:
            cb({"stage": "scan", "status": "done"})  # 不应发生
        return ProposeUiResult(
            status="softcap_reached",
            cumulative_cost_cny=2.05,
            softcap_cny=2.0,
        )

    monkeypatch.setattr(routes_mod, "run_propose_for_ui", fake_run)
    with client.stream("POST", "/api/propose/stream", json={"idea": "x"}) as resp:
        assert resp.status_code == 200
        text = _read_sse(resp)

    events = _parse_sse(text)
    # 应有 softcap 帧
    softcap_events = [
        e for e in events
        if isinstance(e, dict) and e.get("type") in ("result", "softcap_reached")
        and e.get("status") == "softcap_reached"
    ]
    assert len(softcap_events) >= 1
