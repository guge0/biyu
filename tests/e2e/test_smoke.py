"""E2E smoke test — 验证基建可用(ui 首页加载)。

T6 父 spec(M2.5 spec)的"冒烟集"在 T1-T5 完成后写;本文件只验证基建可跑。
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


def test_homepage_loads(page, base_url):
    """访问 / 后,页面应能加载,标题或 h1 含'笔驭'。"""
    page.goto("/")
    page.wait_for_load_state("networkidle", timeout=10_000)

    title = page.title() or ""
    # 静态 index.html 的 <h1> 是"笔驭作者工作台(立项屏)"或类似
    h1_text = page.locator("h1").first.text_content(timeout=2_000) or ""

    combined = title + h1_text
    assert "笔驭" in combined, f"首页未含'笔驭':title={title!r}, h1={h1_text!r}"


def test_env_endpoint_mocked(page, base_url):
    """/api/env 应返 JSON,默认 level=test(灰章)。"""
    response = page.request.get("/api/env")
    assert response.ok, f"/api/env 返 {response.status}"
    body = response.json()
    assert "level" in body, f"/api/env body 缺 level: {body}"
    # 默认 test(无 BIYU_ENV=prod),level 应是 test
    assert body["level"] == "test", f"默认环境应是 test,实际: {body['level']}"


def test_session_endpoint_returns_id(page, base_url):
    """/api/session 应返 session_id(非空字符串)。"""
    response = page.request.get("/api/session")
    assert response.ok, f"/api/session 返 {response.status}"
    body = response.json()
    assert "session_id" in body and body["session_id"], f"session_id 空: {body}"
