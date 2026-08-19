"""Tests for biyu.ui.session — 会话成本累计 + 软顶(P8-M1 T2).

覆盖:
- 新 session 累计 = 0
- add_cost 后累加
- 累计 + 估算 ≥ softcap(默认 2.0)且无 confirm → softcap_reached
- confirm=True → confirmed(放行)
- 两 session 进程内隔离
"""
from __future__ import annotations

import pytest

from biyu.ui.session import SessionCosts


@pytest.fixture
def costs() -> SessionCosts:
    """每个测试独立实例,避免共享状态污染(P7-8 类型教训)。"""
    return SessionCosts(softcap=2.0)


class TestSessionCosts:
    def test_new_session_has_zero_cumulative(self, costs: SessionCosts):
        sid = costs.new_session()
        assert costs.get_cumulative(sid) == pytest.approx(0.0)

    def test_add_cost_accumulates(self, costs: SessionCosts):
        sid = costs.new_session()
        costs.add_cost(sid, 0.04)
        costs.add_cost(sid, 0.10)
        assert costs.get_cumulative(sid) == pytest.approx(0.14)

    def test_softcap_reached_when_projected_exceeds_without_confirm(
        self, costs: SessionCosts
    ):
        sid = costs.new_session()
        costs.add_cost(sid, 1.95)  # 已花 1.95
        # 再花 0.10 估算 → 投影 2.05 ≥ 2.0,未 confirm → 拦截
        st = costs.check_softcap(sid, next_cost_estimate=0.10)
        assert st.status == "softcap_reached"
        assert st.cumulative == pytest.approx(1.95)
        assert st.softcap == pytest.approx(2.0)
        assert st.projected == pytest.approx(2.05)

    def test_confirm_bypasses_softcap(self, costs: SessionCosts):
        sid = costs.new_session()
        costs.add_cost(sid, 1.95)
        st = costs.check_softcap(sid, next_cost_estimate=0.10, confirm=True)
        assert st.status == "confirmed"

    def test_below_softcap_returns_ok(self, costs: SessionCosts):
        sid = costs.new_session()
        costs.add_cost(sid, 0.10)
        st = costs.check_softcap(sid, next_cost_estimate=0.10)
        assert st.status == "ok"
        assert st.projected == pytest.approx(0.20)

    def test_two_sessions_isolated(self, costs: SessionCosts):
        a = costs.new_session()
        b = costs.new_session()
        costs.add_cost(a, 1.50)
        costs.add_cost(b, 0.10)
        assert costs.get_cumulative(a) == pytest.approx(1.50)
        assert costs.get_cumulative(b) == pytest.approx(0.10)
        assert a != b
