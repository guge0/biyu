"""T7-3 峰谷时段提示(P8-M2.5)— UI 成本条加时段提示。

D-81(全景图):DeepSeek 峰谷定价 7 月中旬起,北京 9:00-12:00 / 14:00-18:00 高峰 2x。
Spec(specs/P8-M2.5.md line 15):成本条加峰谷时段提示:
  - 北京 9-12 / 14-18 显示"高峰 2x"
  - 7 月中旬(15 日)生效前显示"即将生效"

本测试验证 GET /api/peak-hours 端点返时段状态。零烧钱,纯逻辑测试。
"""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from biyu.ui.app import app


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/peak-hours
# ---------------------------------------------------------------------------


def test_peak_hours_returns_200_with_fields(client):
    """T7-3 RED:GET /api/peak-hours 返 200 + 必备字段。"""
    resp = client.get("/api/peak-hours")
    assert resp.status_code == 200
    body = resp.json()
    # 必备字段:is_peak / label / effective_from / now
    assert "is_peak" in body
    assert "label" in body
    assert "effective_from" in body
    assert "now" in body


def test_peak_hours_before_effective_date_returns_pending(client, monkeypatch):
    """T7-3:7 月 15 日前应返"即将生效"状态(is_peak=False, label 含'即将生效')。"""
    from biyu.ui import routes as routes_mod

    # 模拟当前日期在 7 月 15 日之前
    fake_now = datetime(2026, 7, 10, 10, 0)  # 7 月 10 日 10:00(本来是高峰时段,但还没生效)
    monkeypatch.setattr(routes_mod, "_get_now", lambda: fake_now)

    resp = client.get("/api/peak-hours")
    body = resp.json()
    assert body["is_peak"] is False
    assert "即将生效" in body["label"]


def test_peak_hours_peak_morning_returns_peak(client, monkeypatch):
    """T7-3:7 月 15 日后,北京 09:00-12:00 应返 is_peak=True。"""
    from biyu.ui import routes as routes_mod

    fake_now = datetime(2026, 7, 20, 10, 0)  # 7 月 20 日(生效后)10:00(早高峰)
    monkeypatch.setattr(routes_mod, "_get_now", lambda: fake_now)

    resp = client.get("/api/peak-hours")
    body = resp.json()
    assert body["is_peak"] is True
    assert "高峰" in body["label"]


def test_peak_hours_peak_afternoon_returns_peak(client, monkeypatch):
    """T7-3:7 月 15 日后,北京 14:00-18:00 应返 is_peak=True。"""
    from biyu.ui import routes as routes_mod

    fake_now = datetime(2026, 7, 20, 16, 30)  # 7 月 20 日 16:30(下午高峰)
    monkeypatch.setattr(routes_mod, "_get_now", lambda: fake_now)

    resp = client.get("/api/peak-hours")
    body = resp.json()
    assert body["is_peak"] is True


def test_peak_hours_off_peak_returns_not_peak(client, monkeypatch):
    """T7-3:7 月 15 日后,但非 9-12 / 14-18 时段,应返 is_peak=False(平峰)。"""
    from biyu.ui import routes as routes_mod

    fake_now = datetime(2026, 7, 20, 20, 0)  # 7 月 20 日 20:00(晚间平峰)
    monkeypatch.setattr(routes_mod, "_get_now", lambda: fake_now)

    resp = client.get("/api/peak-hours")
    body = resp.json()
    assert body["is_peak"] is False
    assert "平峰" in body["label"] or "非高峰" in body["label"]
