"""Tests for P8-M1 T4 — 软顶拦截集成到 orchestrator.

覆盖:
- 累计 ≥ softcap 且无 confirm → run_propose_for_ui 直接返 softcap_reached,
  **不调任何 LLM**(scan_all / decide_path_with_cost 等都不该被调用)
- confirm=True → 正常跑(status=ok)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from biyu.ui import orchestrator as orch_mod
from biyu.ui.orchestrator import run_propose_for_ui
from biyu.ui.session import SessionCosts


def test_softcap_blocks_and_no_llm_called(tmp_path: Path, monkeypatch):
    """累计 ≥ softcap 无 confirm → 返 softcap_reached,scan_all 不被调用。"""
    # 准备一个已超 softcap 的 session
    costs = SessionCosts(softcap=2.0)
    sid = costs.new_session()
    costs.add_cost(sid, 2.50)  # 已花 2.5 ≥ 2.0

    # 监视 scan_all_cached 是否被调
    scan_calls: list = []

    def spy_scan_all(**kwargs):
        scan_calls.append(kwargs)
        return {}, {"cached": False, "cache_date": None,
                    "warning": None, "cache_path": None}

    monkeypatch.setattr(orch_mod, "scan_all_cached", spy_scan_all)

    # 不传 llm_adapter;若 orchestrator 真去取 adapter,也会因为没有真实 registry 走 None
    result = run_propose_for_ui(
        idea="校车",
        name="t4_block",
        platforms=["qidian"],
        data_root=tmp_path,
        session_id=sid,
        costs=costs,
        confirm_over_softcap=False,
    )

    assert result.status == "softcap_reached"
    assert result.cumulative_cost_cny == pytest.approx(2.50)
    assert result.softcap_cny == pytest.approx(2.0)
    # 关键:任何 LLM / scan 都不该被调
    assert scan_calls == [], "softcap_reached 时不应调 scan_all_cached"
    # markdown 也未生成
    assert result.markdown == ""


def test_confirm_over_softcap_proceeds(tmp_path: Path, monkeypatch):
    """累计 ≥ softcap 但 confirm=True → 正常跑,status=ok。"""
    costs = SessionCosts(softcap=2.0)
    sid = costs.new_session()
    costs.add_cost(sid, 2.50)

    # 用一个会成功的 mock scan(T4.1 起 orchestrator 走 scan_all_cached)
    from biyu.propose.scanner import BookEntry, PlatformResult

    def mock_scan_all(platforms, fetchers=None, limit=20):
        return {
            p: PlatformResult(
                platform=p, success=True,
                books=[BookEntry(
                    rank=1, title="书1", author="a", category="玄幻",
                    word_count="100万字", url="https://x/1", abstract="s",
                )],
                fetched_at="2026-07-03T10:00:00+00:00",
                source_url=f"https://x/{p}",
            )
            for p in platforms
        }

    def mock_cached(**kwargs):
        return mock_scan_all(
            platforms=kwargs.get("platforms", []),
            fetchers=kwargs.get("fetchers"),
            limit=kwargs.get("limit", 20),
        ), {"cached": False, "cache_date": None,
            "warning": None, "cache_path": None}

    monkeypatch.setattr(orch_mod, "scan_all_cached", mock_cached)

    # mock LLM adapter(注入,不调 registry)
    from tests.test_ui_orchestrator import _MockAdapter
    adapter = _MockAdapter(router_response="specific")

    result = run_propose_for_ui(
        idea="校车",
        name="t4_confirm",
        platforms=["qidian"],
        llm_adapter=adapter,
        data_root=tmp_path,
        session_id=sid,
        costs=costs,
        confirm_over_softcap=True,
    )

    assert result.status == "ok"
    assert result.path == "specific"
