"""S-7a — 内测授权与责编开关契约。

licensing 单元:到期前/当天/次日的免费与付费判定、未知功能名拒绝+记日志。
路由:到期后 /api/zhuque/fix 与 /fix-blind 回 402、/api/zhuque/check 不受影响;
features.zebian 关时 /api/agent/* 与 workbench 责编接口拒绝,开时正常。
日期与外部 client 全部注入/打桩,零真实模型与朱雀调用。
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from biyu import licensing
from biyu.ui.app import app

from tests.test_agent_tools import make_book

EXPIRED_MESSAGE = licensing.EXPIRED_MESSAGE


# ---------------------------------------------------------------------------
# licensing 单元
# ---------------------------------------------------------------------------


def test_free_features_allowed_before_and_after_expiry():
    for today in (date(2026, 11, 19), date(2027, 1, 31), date(2027, 5, 1)):
        for name in licensing.FREE_FEATURES:
            decision = licensing.check_feature(name, today=today)
            assert decision.allowed is True, f"{name}@{today}"
            assert decision.message == ""


def test_paid_allowed_before_expiry():
    for name in licensing.PAID_FEATURES:
        decision = licensing.check_feature(name, today=date(2026, 11, 19))
        assert decision.allowed is True
        assert decision.reason == "beta_active"


def test_paid_allowed_on_expiry_day():
    """到期日当天仍可用(2027-01-31),次日起才算到期。"""
    decision = licensing.check_feature("zhuque_fix", today=date(2027, 1, 31))
    assert decision.allowed is True
    assert licensing.is_expired(date(2027, 1, 31)) is False


def test_paid_rejected_from_day_after_expiry():
    decision = licensing.check_feature("zhuque_fix", today=date(2027, 2, 1))
    assert decision.allowed is False
    assert decision.reason == "beta_expired"
    assert decision.message == EXPIRED_MESSAGE
    assert "写作和体检仍可继续使用" in decision.message


def test_unknown_feature_rejected_and_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="biyu.licensing"):
        decision = licensing.check_feature("no_such_feature", today=date(2026, 11, 19))
    assert decision.allowed is False
    assert decision.reason == "unknown_feature"
    assert any("no_such_feature" in record.message for record in caplog.records)


def test_status_payload_shape():
    fresh = licensing.status(today=date(2026, 11, 19))
    assert fresh["edition"] == "beta"
    assert fresh["expires"] == "2027-01-31"
    assert fresh["days_left"] == (date(2027, 1, 31) - date(2026, 11, 19)).days
    assert fresh["expired"] is False
    assert fresh["features"] == {name: True for name in licensing.ALL_FEATURES}

    expired = licensing.status(today=date(2027, 2, 1))
    assert expired["expired"] is True
    assert expired["days_left"] == -1
    assert expired["features"]["zhuque_fix"] is False
    assert expired["features"]["writing_pipeline"] is True


# ---------------------------------------------------------------------------
# 路由:授权闸
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_zhuque_state():
    from biyu.ui import zhuque_routes

    zhuque_routes._JOBS.clear()
    zhuque_routes._RUNNING = False
    zhuque_routes._LAST_CHECK.update(red=None, fixable=None, chars=None)
    yield
    zhuque_routes._JOBS.clear()
    zhuque_routes._RUNNING = False


def test_zhuque_fix_returns_402_after_expiry(client: TestClient, monkeypatch):
    monkeypatch.setattr(licensing, "_today", lambda: date(2027, 2, 1))
    resp = client.post("/api/zhuque/fix", json={"text": "测试文本"})
    assert resp.status_code == 402
    assert resp.json() == {"detail": EXPIRED_MESSAGE, "code": "license_required"}


def test_zhuque_fix_estimate_stays_free_after_expiry(client: TestClient, monkeypatch):
    """S-7c：到期后仍可看预估金额，只拦真正的改写。"""
    monkeypatch.setattr(licensing, "_today", lambda: date(2027, 2, 1))
    resp = client.post("/api/zhuque/fix", json={"text": "测试文本", "estimate_only": True})
    assert resp.status_code == 200
    assert "estimate" in resp.json()


def test_zhuque_fix_blind_returns_402_after_expiry(client: TestClient, monkeypatch):
    monkeypatch.setattr(licensing, "_today", lambda: date(2027, 2, 1))
    resp = client.post("/api/zhuque/fix-blind", json={"text": "测试文本"})
    assert resp.status_code == 402
    assert resp.json()["code"] == "license_required"


def test_zhuque_fix_allowed_before_expiry_reaches_length_guard(client: TestClient):
    """未到期时授权闸放行;走到原有的长度/Key 校验(证明闸不在最前面拦死)。"""
    resp = client.post(
        "/api/zhuque/fix", json={"text": "长" * 200_001, "estimate_only": True},
    )
    assert resp.status_code == 413  # 超长被原有 _guard_length 拦下,而非 402


def test_zhuque_check_unaffected_after_expiry(client: TestClient, monkeypatch):
    monkeypatch.setattr(licensing, "_today", lambda: date(2027, 2, 1))

    class FakeZhuqueClient:
        used_tokens = 5

        async def windows(self, text):
            return [{"order": 1, "start": 0, "end": len(text), "text": text, "conf": 0.1, "label": 0}]

        async def verdict(self, text):
            return {"labels_ratio": {"0": 1.0, "1": 0.0, "2": 0.0}, "softmax_confidence": 0.01}

    from biyu.ui import zhuque_routes

    monkeypatch.setattr(zhuque_routes, "_client_or_error", lambda: FakeZhuqueClient())
    resp = client.post("/api/zhuque/check", json={"text": "测试文本"})
    assert resp.status_code == 200
    assert resp.json()["red"] == 0


def test_license_status_endpoint(client: TestClient):
    resp = client.get("/api/license/status")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["edition"] == "beta"
    assert payload["expires"] == "2027-01-31"
    assert payload["expired"] is False  # 2026-11 未到期
    assert set(payload["features"]) == set(licensing.ALL_FEATURES)


def test_features_endpoint_reflects_zebian_flag(client: TestClient, monkeypatch):
    resp = client.get("/api/features")
    assert resp.status_code == 200
    assert resp.json()["features"]["zebian"] is False  # 内测默认关(缺省同 false)

    monkeypatch.setattr("biyu.config.feature_enabled", lambda name: name == "zebian")
    resp_on = client.get("/api/features")
    assert resp_on.json()["features"]["zebian"] is True


# ---------------------------------------------------------------------------
# 路由:责编开关
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    make_book(tmp_path)
    monkeypatch.setattr("biyu.config.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.web.routes.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.ui.routes.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.ui.agent_routes.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.ui.workbench.get_data_root", lambda: tmp_path)
    return tmp_path


def test_agent_routes_rejected_when_zebian_off(client: TestClient, tmp_data_root: Path):
    """配置缺省(features 无 zebian 项)按关处理:整组 /api/agent/* 一刀切 404。"""
    for method, path in (
        ("post", "/api/agent/sessions"),
        ("get", "/api/agent/pending?book=MyBook"),
        ("post", "/api/agent/sessions/nope/messages"),
    ):
        resp = getattr(client, method)(path, **({"json": {"book": "MyBook"}} if method == "post" else {}))
        assert resp.status_code == 404, f"{method} {path}"
        assert "内测版暂未开放此功能" in resp.json()["detail"]


def test_workbench_zebian_routes_rejected_when_off(client: TestClient, tmp_data_root: Path):
    resp = client.get("/api/workbench/books/MyBook/zebian/sessions")
    assert resp.status_code == 404
    assert "内测版暂未开放此功能" in resp.json()["detail"]
    # 启动 Claude Code 的责编接口同样拒绝(闸在端口校验之前)
    launch = client.post("/api/workbench/books/MyBook/zebian")
    assert launch.status_code == 404


def test_agent_session_normal_when_zebian_on(
    client: TestClient, tmp_data_root: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("biyu.ui.agent_routes.feature_enabled", lambda _name: True)
    monkeypatch.setattr("biyu.ui.workbench.feature_enabled", lambda _name: True)
    created = client.post("/api/agent/sessions", json={"book": "MyBook"})
    assert created.status_code == 200
    assert created.json()["role"] == "agent"

    listed = client.get("/api/workbench/books/MyBook/zebian/sessions")
    assert listed.status_code == 200
    assert listed.json()["sessions"] == []

    # 启动接口过了授权闸后,走到原有的端口校验(TestClient 无端口 → 400,不会真拉起)
    launch = client.post("/api/workbench/books/MyBook/zebian")
    assert launch.status_code == 400
    assert "端口" in launch.json()["detail"]
