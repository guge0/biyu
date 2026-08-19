"""T4.2 扫榜缓存徽标 + 重新扫榜 e2e(P8-M2.5)。

Spec line 12:页面常显「榜单数据 · X月X日」+「重新扫榜」按钮;缓存缺失/损坏
→ 现扫并 WARNING 出声(D-70)。
"""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.e2e


def _mock_env_routes(page):
    page.route("**/api/env", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"level": "test", "label": "测试", "color": "#a8a8a8"})))
    page.route("**/api/session", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"session_id": "t4-sess"})))
    page.route("**/api/peak-hours", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"is_peak": False, "label": "平峰",
                         "effective_from": "2026-07-15", "now": "2026-07-04T10:00"})))


def _sse_body(events: list[dict]) -> str:
    parts = ["data: " + json.dumps(e, ensure_ascii=False) for e in events]
    parts.append("data: [DONE]")
    return "\n\n".join(parts) + "\n\n"


def _fulfill(events):
    return lambda r: r.fulfill(
        status=200, content_type="text/event-stream", body=_sse_body(events))


def test_rescan_button_visible_on_propose_page(page, base_url):
    """propose.html 应含 #rescan-btn「重新扫榜」按钮。"""
    _mock_env_routes(page)
    page.goto("/propose.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    btn = page.locator("#rescan-btn")
    btn.wait_for(state="visible", timeout=5_000)
    assert "重新扫榜" in (btn.text_content() or "")


def test_cache_hit_renders_badge(page, base_url):
    """scan 事件 cached=True + cache_date → 显示「榜单数据 · 日期 · 缓存」。"""
    _mock_env_routes(page)
    events = [
        {"type": "progress", "stage": "scan", "status": "start"},
        {"type": "progress", "stage": "scan", "status": "done",
         "cached": True, "cache_date": "2026-07-04"},
        {"type": "result", "status": "ok", "path": "empty",
         "total_cost_cny": 0.001, "elapsed_seconds": 0.5,
         "model_alias": "x",
         "router": {"decision": "empty", "source": "llm",
                    "cost_cny": 0.001, "latency_s": 0.1},
         "analysis": {"hot_genres": [], "hot_tropes": [],
                      "market_summary": "x", "source": "llm",
                      "cost_cny": 0.0, "latency_s": 0.0},
         "craft": {"markdown": "## x", "source": "llm",
                   "cost_cny": 0.0, "latency_s": 0.0},
         "honesty_note": "x",
         "markdown": "# x",
         "out_path": "/tmp/x.md",
         "cumulative_cost_cny": 0.001,
         "softcap_cny": 2.0,
         "scan_cache": {"cached": True, "cache_date": "2026-07-04",
                        "warning": None, "cache_path": "/tmp/scan.json"}},
    ]
    page.route("**/api/propose/stream", _fulfill(events))

    page.goto("/propose.html")
    page.wait_for_load_state("networkidle", timeout=10_000)
    page.fill("#idea-input", "")
    page.click("#submit-btn")

    badge = page.locator("#scan-cache-badge")
    badge.wait_for(state="visible", timeout=5_000)
    text = badge.inner_text()
    assert "2026-07-04" in text, f"缓存徽标缺日期:{text!r}"
    assert "缓存" in text, f"徽标缺'缓存'标记:{text!r}"


def test_cache_warning_renders_red_badge(page, base_url):
    """缓存损坏 → WARNING 徽标红色(D-70 出声)。"""
    _mock_env_routes(page)
    events = [
        {"type": "progress", "stage": "scan", "status": "done",
         "cached": False, "cache_date": "2026-07-04"},
        {"type": "result", "status": "ok", "path": "empty",
         "total_cost_cny": 0.0, "elapsed_seconds": 0.5,
         "model_alias": "x",
         "router": {"decision": "empty", "source": "llm",
                    "cost_cny": 0.0, "latency_s": 0.0},
         "analysis": {"hot_genres": [], "hot_tropes": [],
                      "market_summary": "x", "source": "llm",
                      "cost_cny": 0.0, "latency_s": 0.0},
         "craft": {"markdown": "## x", "source": "llm",
                   "cost_cny": 0.0, "latency_s": 0.0},
         "honesty_note": "x",
         "markdown": "# x",
         "out_path": "/tmp/x.md",
         "cumulative_cost_cny": 0.0,
         "softcap_cny": 2.0,
         "scan_cache": {"cached": False, "cache_date": "2026-07-04",
                        "warning": "缓存损坏(2026-07-04),已现扫",
                        "cache_path": "/tmp/scan.json"}},
    ]
    page.route("**/api/propose/stream", _fulfill(events))

    page.goto("/propose.html")
    page.wait_for_load_state("networkidle", timeout=10_000)
    page.fill("#idea-input", "")
    page.click("#submit-btn")

    badge = page.locator("#scan-cache-badge.cache-warn")
    badge.wait_for(state="visible", timeout=5_000)
    text = badge.inner_text()
    assert "损坏" in text, f"WARNING 徽标缺'损坏':{text!r}"
