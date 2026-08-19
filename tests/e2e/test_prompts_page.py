"""T5 提示词页 e2e(P8-M2.5)— spec line 13。

只读渲染:prompt_texts_<date>.md 全文(主体)+ inventory 索引(辅)+ source(辅)。
严格只读;nav 含「提示词」。
"""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.e2e


def _mock_env_routes(page):
    page.route("**/api/env", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"level": "test", "label": "测试", "color": "#a8a8a8"})))
    page.route("**/api/peak-hours", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"is_peak": False, "label": "平峰",
                         "effective_from": "2026-07-15", "now": "2026-07-04T10:00"})))


def _mock_texts_and_inventory(page, *, texts_md="# prompt 全文\n", texts_date="2026-07-01",
                              inventory_md="# inventory\n"):
    """统一 mock texts + inventory 两个端点。"""
    page.route("**/api/prompts/texts", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"markdown": texts_md, "date": texts_date})))
    page.route("**/api/prompts/inventory", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"markdown": inventory_md})))


def test_prompts_page_has_readonly_notice(page, base_url):
    """页头应显示「严格只读」声明 + 「修改走 spec 流程」。"""
    _mock_env_routes(page)
    _mock_texts_and_inventory(page)
    page.goto("/prompts.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    notice = page.locator(".readonly-notice")
    notice.wait_for(state="visible", timeout=5_000)
    text = notice.inner_text()
    assert "严格只读" in text, f"只读声明缺'严格只读':{text!r}"
    assert "spec 流程" in text, f"缺 spec 流程提示:{text!r}"


def test_prompts_page_renders_texts_as_main_body(page, base_url):
    """主体应渲染 prompt_texts 全文(中枢裁定),不是 inventory。"""
    _mock_env_routes(page)
    _mock_texts_and_inventory(
        page,
        texts_md=("# 三层现役 prompt 全文\n\n"
                  "## 1. Architect\n"
                  "build_planning_prompt at v3_opening.py:303\n"),
        texts_date="2026-07-01",
        inventory_md="# 仅 inventory 索引,不该是主体\n",
    )

    page.goto("/prompts.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    main = page.locator("#texts-body")
    main.wait_for(timeout=5_000)
    html = main.inner_html()
    assert "Architect" in html
    assert "build_planning_prompt" in html


def test_prompts_page_shows_export_date_in_header(page, base_url):
    """页头应显示「导出于 YYYY-MM-DD · 本地中枢定期刷新」。"""
    _mock_env_routes(page)
    _mock_texts_and_inventory(page, texts_date="2026-07-01")

    page.goto("/prompts.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    header = page.locator("#texts-export-date")
    header.wait_for(timeout=5_000)
    text = header.inner_text()
    assert "2026-07-01" in text, f"页头应含日期 2026-07-01:{text!r}"
    assert "本地中枢" in text or "定期刷新" in text, f"页头应含本地中枢定期刷新:{text!r}"


def test_prompts_page_renders_inventory_as_auxiliary(page, base_url):
    """inventory 索引应保留为辅(可折叠 details,点开后可见)。"""
    _mock_env_routes(page)
    _mock_texts_and_inventory(
        page,
        texts_md="# prompt 全文\n",
        inventory_md="# 索引\n## Architect\n- src/biyu/prompts/v3_opening.py\n",
    )

    page.goto("/prompts.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    # inventory 在折叠 details 里,先点开
    summary = page.locator(".prompts-aux > summary")
    summary.wait_for(timeout=5_000)
    summary.click()
    inv = page.locator("#inventory-body")
    inv.wait_for(state="visible", timeout=5_000)
    html = inv.inner_html()
    assert "v3_opening.py" in html


def test_home_nav_does_not_link_to_prompts_page(page, base_url):
    """提示词实现保留，但首页导航不再提供入口。"""
    _mock_env_routes(page)
    _mock_texts_and_inventory(page)
    page.goto("/")
    page.wait_for_load_state("networkidle", timeout=10_000)

    link = page.locator('.top-nav .nav-links a[href^="/prompts.html"]')
    assert link.count() == 0


def test_prompts_page_has_no_write_inputs(page, base_url):
    """页面严格只读:无 input、textarea、button[type=submit] 等可写元素。"""
    _mock_env_routes(page)
    _mock_texts_and_inventory(page)
    page.goto("/prompts.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    # 不应有可写表单元素
    inputs = page.locator("input, textarea, button[type='submit']").count()
    assert inputs == 0, f"提示词页应无表单元素,实际有 {inputs} 个"
