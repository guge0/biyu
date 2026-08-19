"""Tests for biyu.ui.routes — FastAPI 路由层(P8-M1 T5).

覆盖:
- GET /api/env → 环境章字典
- GET /api/session → 新 session_id
- POST /api/propose 三路径(SPECIFIC/DIRECTIONAL/EMPTY)→ 200 + ProposeUiResult
- POST /api/propose 软顶拦截 → 200(不 4xx)+ status="softcap_reached"
- POST /api/propose orchestrator 异常 → 500 + 一句人话

orchestrator 通过 monkeypatch mock,不真跑 propose(零烧钱)。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from biyu.ui.app import app
from biyu.ui.orchestrator import ProposeUiResult
from biyu.ui.session import SessionCosts


@pytest.fixture
def client_and_costs(monkeypatch: pytest.MonkeyPatch):
    """提供 TestClient + 新的 SessionCosts 实例(避免跨测试污染)。"""
    fresh_costs = SessionCosts(softcap=2.0)
    # routes.py 用模块级 _costs 单例,这里替换成新实例
    from biyu.ui import routes as routes_mod
    monkeypatch.setattr(routes_mod, "_costs", fresh_costs)
    client = TestClient(app)
    return client, fresh_costs


def _fake_result(path: str = "specific", status: str = "ok") -> ProposeUiResult:
    """构造一个最小可用的 ProposeUiResult(mock 用)。"""
    return ProposeUiResult(
        status=status,
        path=path,
        router={"decision": path, "source": "llm", "cost_cny": 0.001, "latency_s": 0.5},
        analysis={
            "hot_genres": [], "hot_tropes": [], "market_summary": "测试行情。",
            "source": "llm", "cost_cny": 0.001, "latency_s": 0.5,
        },
        redblue={"supply_crowding": "x", "demand_weak_signal": "y", "quadrant": "红海",
                 "source": "llm", "cost_cny": 0.001, "latency_s": 0.5} if path == "specific" else None,
        craft={"markdown": "## ...", "source": "llm", "cost_cny": 0.001, "latency_s": 0.5},
        honesty_note="测试声明。",
        markdown="# 测试立项书",
        out_path="/tmp/test.md",
        total_cost_cny=0.004,
        elapsed_seconds=2.0,
        model_alias="test-model",
    )


# ---------------------------------------------------------------------------
# GET /api/env
# ---------------------------------------------------------------------------


def test_get_env_returns_dict(client_and_costs):
    client, _ = client_and_costs
    resp = client.get("/api/env")
    assert resp.status_code == 200
    body = resp.json()
    assert body["level"] in ("test", "prod")
    assert "label" in body
    assert "color" in body
    assert body["color"].startswith("#")


# ---------------------------------------------------------------------------
# GET /api/session
# ---------------------------------------------------------------------------


def test_get_session_returns_id(client_and_costs):
    client, _ = client_and_costs
    resp = client.get("/api/session")
    assert resp.status_code == 200
    sid = resp.json()["session_id"]
    # UUID hex 长 32,或允许其他形式 —— 关键是非空字符串
    assert isinstance(sid, str) and len(sid) >= 8
    # 再取一次,应是不同的 session_id
    sid2 = client.get("/api/session").json()["session_id"]
    assert sid != sid2


# ---------------------------------------------------------------------------
# POST /api/propose 三路径
# ---------------------------------------------------------------------------


def test_post_propose_specific_path(client_and_costs, monkeypatch):
    from biyu.ui import routes as routes_mod
    monkeypatch.setattr(
        routes_mod, "run_propose_for_ui",
        lambda **kwargs: _fake_result(path="specific"),
    )
    client, _ = client_and_costs
    resp = client.post("/api/propose", json={"idea": "校车", "name": "t5_specific"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["path"] == "specific"
    assert body["redblue"] is not None


def test_post_propose_empty_path(client_and_costs, monkeypatch):
    from biyu.ui import routes as routes_mod
    monkeypatch.setattr(
        routes_mod, "run_propose_for_ui",
        lambda **kwargs: _fake_result(path="empty"),
    )
    client, _ = client_and_costs
    resp = client.post("/api/propose", json={"idea": "", "name": "t5_empty"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == "empty"
    assert body["redblue"] is None


# ---------------------------------------------------------------------------
# 软顶拦截(返回 200,不 4xx —— 前端要拿数据渲染确认弹窗)
# ---------------------------------------------------------------------------


def test_post_propose_softcap_reached_returns_200_with_status(client_and_costs, monkeypatch):
    from biyu.ui import routes as routes_mod
    monkeypatch.setattr(
        routes_mod, "run_propose_for_ui",
        lambda **kwargs: ProposeUiResult(
            status="softcap_reached", cumulative_cost_cny=2.05, softcap_cny=2.0,
        ),
    )
    client, _ = client_and_costs
    resp = client.post("/api/propose", json={"idea": "校车"})
    # 关键:200 而非 4xx,前端要读 body 弹确认框
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "softcap_reached"
    assert body["cumulative_cost_cny"] >= body["softcap_cny"]


# ---------------------------------------------------------------------------
# orchestrator 异常 → 500 + 人话
# ---------------------------------------------------------------------------


def test_post_propose_orchestrator_exception_returns_500(client_and_costs, monkeypatch):
    from biyu.ui import routes as routes_mod

    def boom(**kwargs):
        raise RuntimeError("simulated registry outage")

    monkeypatch.setattr(routes_mod, "run_propose_for_ui", boom)
    client, _ = client_and_costs
    resp = client.post("/api/propose", json={"idea": "校车"})
    assert resp.status_code == 500
    body = resp.json()
    # 一句人话(detail 字段),不暴露堆栈
    assert "detail" in body
    assert isinstance(body["detail"], str) and body["detail"]
