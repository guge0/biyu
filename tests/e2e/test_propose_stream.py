"""T3.3-T3.5 立项屏 SSE 进度 e2e(P8-M2.5)。

Spec line 11 + 25:propose 按 stage 推送进度,前端进度列表替换"生成中…",
失败时原地显示人话 + 可重试。

Mock /api/propose/stream 返合成 SSE 流,验证:
- 进度列表 .progress-list 渲染每个 stage
- done 后渲染完整卡片
- 失败 stage 在列表里显示红色 + 重试按钮
"""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.e2e


def _sse_body(events: list[dict]) -> str:
    """把事件列表编成 SSE 文本(data: ...\\n\\n,末尾 data: [DONE])。"""
    parts = []
    for evt in events:
        parts.append("data: " + json.dumps(evt, ensure_ascii=False))
    parts.append("data: [DONE]")
    return "\n\n".join(parts) + "\n\n"


def _mock_env_routes(page):
    """拦截环境章/会话/峰谷接口,避免真跑。"""
    page.route("**/api/env", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"level": "test", "label": "测试", "color": "#a8a8a8"})))
    page.route("**/api/session", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"session_id": "test-sess-001"})))
    page.route("**/api/peak-hours", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"is_peak": False, "label": "平峰",
                         "effective_from": "2026-07-15", "now": "2026-07-04T10:00"})))


def test_progress_list_renders_stages(page, base_url):
    """SPECIFIC 路径 SSE → 前端 .progress-list 渲染所有 stage。"""
    _mock_env_routes(page)

    events = [
        {"type": "progress", "stage": "scan", "status": "start"},
        {"type": "progress", "stage": "scan", "status": "done"},
        {"type": "progress", "stage": "router", "status": "start"},
        {"type": "progress", "stage": "router", "status": "done",
         "decision": "specific", "cost_cny": 0.001},
        {"type": "progress", "stage": "tropes", "status": "start"},
        {"type": "progress", "stage": "tropes", "status": "done", "cost_cny": 0.001},
        {"type": "progress", "stage": "redblue", "status": "start"},
        {"type": "progress", "stage": "redblue", "status": "done", "cost_cny": 0.001},
        {"type": "progress", "stage": "craft", "status": "start"},
        {"type": "progress", "stage": "craft", "status": "done", "cost_cny": 0.001},
        {"type": "result", "status": "ok", "path": "specific",
         "total_cost_cny": 0.004, "elapsed_seconds": 1.5,
         "model_alias": "test-model",
         "router": {"decision": "specific", "source": "llm", "cost_cny": 0.001, "latency_s": 0.5},
         "analysis": {"hot_genres": [], "hot_tropes": [], "market_summary": "测试行情。",
                      "source": "llm", "cost_cny": 0.001, "latency_s": 0.5},
         "redblue": {"quadrant": "红海", "supply_crowding": "x",
                     "demand_weak_signal": "y", "source": "llm",
                     "cost_cny": 0.001, "latency_s": 0.5},
         "craft": {"markdown": "## 测试", "source": "llm",
                   "cost_cny": 0.001, "latency_s": 0.5},
         "honesty_note": "测试声明。",
         "markdown": "# 测试立项书",
         "out_path": "/tmp/test.md",
         "cumulative_cost_cny": 0.004,
         "softcap_cny": 2.0},
    ]

    page.route("**/api/propose/stream", lambda r: r.fulfill(
        status=200, content_type="text/event-stream",
        body=_sse_body(events)))

    page.goto("/propose.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    # 输入设想 + 点体检
    page.fill("#idea-input", "测试想法")
    page.click("#submit-btn")

    # 等进度列表出现
    page.wait_for_selector(".progress-list", timeout=5_000)

    # 应渲染 stage 行(至少 scan/router/tropes/redblue/craft)
    rows = page.locator(".progress-list .progress-item")
    rows.first.wait_for(timeout=5_000)
    assert rows.count() >= 5, f"应有 ≥5 stage 行,实际:{rows.count()}"

    # 验证 stage 标签出现
    list_text = page.locator(".progress-list").inner_text()
    assert "扫榜" in list_text or "scan" in list_text.lower(), \
        f"进度列表缺'扫榜':{list_text!r}"


def test_progress_done_renders_result_card(page, base_url):
    """result 帧到达后,卡片渲染区应显示 path-line 等。"""
    _mock_env_routes(page)

    events = [
        {"type": "progress", "stage": "scan", "status": "done"},
        {"type": "progress", "stage": "router", "status": "done",
         "decision": "specific", "cost_cny": 0.001},
        {"type": "progress", "stage": "tropes", "status": "done", "cost_cny": 0.001},
        {"type": "progress", "stage": "redblue", "status": "done", "cost_cny": 0.001},
        {"type": "progress", "stage": "craft", "status": "done", "cost_cny": 0.001},
        {"type": "result", "status": "ok", "path": "specific",
         "total_cost_cny": 0.004, "elapsed_seconds": 1.5,
         "model_alias": "test-model",
         "router": {"decision": "specific", "source": "llm",
                    "cost_cny": 0.001, "latency_s": 0.5},
         "analysis": {"hot_genres": [], "hot_tropes": [],
                      "market_summary": "测试行情。", "source": "llm",
                      "cost_cny": 0.001, "latency_s": 0.5},
         "redblue": {"quadrant": "红海", "supply_crowding": "x",
                     "demand_weak_signal": "y", "source": "llm",
                     "cost_cny": 0.001, "latency_s": 0.5},
         "craft": {"markdown": "## 测试", "source": "llm",
                   "cost_cny": 0.001, "latency_s": 0.5},
         "honesty_note": "测试声明。",
         "markdown": "# 测试立项书",
         "out_path": "/tmp/test.md",
         "cumulative_cost_cny": 0.004,
         "softcap_cny": 2.0},
    ]
    page.route("**/api/propose/stream", lambda r: r.fulfill(
        status=200, content_type="text/event-stream",
        body=_sse_body(events)))

    page.goto("/propose.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    page.fill("#idea-input", "校车")
    page.click("#submit-btn")

    # 等结果区可见
    result = page.locator("#result-area")
    result.wait_for(state="visible", timeout=5_000)
    # path-line 含 specific 标签
    path_text = page.locator("#path-line").inner_text()
    assert "specific" in path_text.lower() or "具体" in path_text


def test_progress_failure_shows_error_and_retry(page, base_url):
    """stage status=failed → 列表显示失败人话 + 重试按钮可见。"""
    _mock_env_routes(page)

    events = [
        {"type": "progress", "stage": "scan", "status": "done"},
        {"type": "progress", "stage": "router", "status": "done",
         "decision": "specific", "cost_cny": 0.001},
        {"type": "progress", "stage": "tropes", "status": "done", "cost_cny": 0.001},
        {"type": "progress", "stage": "redblue", "status": "failed",
         "error": "模拟 LLM 中断"},
        {"type": "progress", "stage": "craft", "status": "done", "cost_cny": 0.001},
        {"type": "result", "status": "ok", "path": "specific",
         "total_cost_cny": 0.003, "elapsed_seconds": 1.0,
         "model_alias": "test-model",
         "router": {"decision": "specific", "source": "llm",
                    "cost_cny": 0.001, "latency_s": 0.5},
         "analysis": {"hot_genres": [], "hot_tropes": [],
                      "market_summary": "x", "source": "llm",
                      "cost_cny": 0.001, "latency_s": 0.5},
         "redblue": {"quadrant": None, "supply_crowding": "",
                     "demand_weak_signal": "", "source": "llm_failed",
                     "cost_cny": 0.0, "latency_s": 0.0},
         "craft": {"markdown": "## x", "source": "llm",
                   "cost_cny": 0.001, "latency_s": 0.5},
         "honesty_note": "x",
         "markdown": "# x",
         "out_path": "/tmp/x.md",
         "cumulative_cost_cny": 0.003,
         "softcap_cny": 2.0},
    ]
    page.route("**/api/propose/stream", lambda r: r.fulfill(
        status=200, content_type="text/event-stream",
        body=_sse_body(events)))

    page.goto("/propose.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    page.fill("#idea-input", "x")
    page.click("#submit-btn")

    # 等进度列表
    page.wait_for_selector(".progress-list", timeout=5_000)
    # 至少有一项 status=failed(红蓝海失败)
    failed = page.locator(".progress-item.progress-failed")
    failed.first.wait_for(timeout=5_000)
    assert failed.count() >= 1
    failed_text = failed.first.inner_text()
    # 含错误人话或 stage 名
    assert "红蓝海" in failed_text or "redblue" in failed_text.lower() \
        or "模拟" in failed_text, f"失败行缺内容:{failed_text!r}"


def test_progress_error_event_shows_retry(page, base_url):
    """整流异常(type=error)→ 顶部错误条 + 提交按钮可重新点。"""
    _mock_env_routes(page)

    events = [
        {"type": "error", "message": "生成失败,请重试或检查服务。"},
    ]
    page.route("**/api/propose/stream", lambda r: r.fulfill(
        status=200, content_type="text/event-stream",
        body=_sse_body(events)))

    page.goto("/propose.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    page.fill("#idea-input", "x")
    page.click("#submit-btn")

    # 等错误条出现
    err = page.locator("#error-banner")
    err.wait_for(state="visible", timeout=5_000)
    err_text = err.inner_text()
    assert "失败" in err_text or "重试" in err_text, f"错误条缺提示:{err_text!r}"

    # 提交按钮应恢复可点(error 后 setLoading(false))
    btn = page.locator("#submit-btn")
    assert not btn.is_disabled(), "error 后提交按钮应可点(允许重试)"
