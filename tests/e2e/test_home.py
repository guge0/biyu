"""T2 首页 e2e(P8-M2.5)— 验证 nav + 书架渲染 + 空态。

P-1 后首页只保留 MVP 导航，已摘入口仍可通过直接 URL 测试实现。

本文件验证首页部分:
- nav 含"书架"和"工作台"链接，不含五个摘除入口
- 书架默认渲染(无 mock 时返真实 data/ 下书;若空则显 empty-shelf)
- 页面其他链接也不指向五个摘除页面

E2E marker 默认 deselect;显式跑 `pytest tests/e2e/ -m e2e`。
"""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.e2e


def test_homepage_nav_keeps_mvp_and_hides_pruned_entries(page, base_url):
    """首页导航保留书架/工作台，不再展示五个摘除入口。"""
    page.goto("/")
    page.wait_for_load_state("networkidle", timeout=10_000)

    nav_links = page.locator(".top-nav .nav-links a")
    texts = [nav_links.nth(i).text_content() or "" for i in range(nav_links.count())]
    assert "书架" in texts, f"nav 缺'书架'链接,实际:{texts}"
    assert "工作台" in texts, f"nav 缺'工作台'链接,实际:{texts}"
    assert not ({"立项", "编辑部", "提示词", "偏好", "审读"} & set(texts))


def test_homepage_has_no_link_to_pruned_pages(page, base_url):
    """首页所有链接均不得指向五个摘除页面。"""
    page.goto("/")
    page.wait_for_load_state("networkidle", timeout=10_000)

    hrefs = page.locator("a").evaluate_all(
        "els => els.map(a => a.getAttribute('href') || '')"
    )
    assert not any(
        href.startswith(target)
        for href in hrefs
        for target in (
            "/propose.html",
            "/editor.html",
            "/prompts.html",
            "/preferences.html",
            "/reviews.html",
        )
    )


def test_homepage_renders_bookshelf_with_mock_books(page, base_url):
    """Mock /api/books 返 2 本假书,首页应渲染 2 张书卡。"""
    # 用 page.route 拦截 /api/books
    fake_books = [
        {"name": "TestBook1", "title": "测试书一", "genre": "xuanhuan",
         "last_chapter": 5, "last_reviewed": 3},
        {"name": "TestBook2", "title": "测试书二", "genre": "scifi",
         "last_chapter": None, "last_reviewed": None},
    ]

    def _handle(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"books": fake_books, "count": 2}))

    page.route("**/api/books", _handle)

    page.goto("/")
    page.wait_for_load_state("networkidle", timeout=10_000)

    # 等 JS 渲染书卡
    page.wait_for_selector(".book-card", timeout=5_000)
    cards = page.locator(".book-card")
    assert cards.count() == 2, f"应渲染 2 张书卡,实际:{cards.count()}"

    # 第一张书卡按 last_chapter 排序，TestBook1 优先
    first_title = cards.nth(0).locator(".book-title").text_content() or ""
    assert "测试书一" in first_title, f"第一张书卡应是 TestBook1,实际:{first_title!r}"

    # 书架只展示现役工作台的写作进度，不展示已删除审读页进度
    card1_text = cards.nth(0).inner_text()
    assert "已写到第 5 章 · 其中 0 章已定稿" in card1_text
    assert "已审到" not in card1_text

    # TestBook2 空态 chip
    card2_text = cards.nth(1).inner_text()
    assert "立项完成,未开写" in card2_text


def test_homepage_renders_empty_shelf_when_no_books(page, base_url):
    """Mock /api/books 返空 list,首页应显示 empty-shelf 邀请文案。"""
    page.route("**/api/books", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({"books": [], "count": 0})
    ))

    page.goto("/")
    page.wait_for_load_state("networkidle", timeout=10_000)

    # 等空态显示
    empty = page.locator("#empty-shelf")
    empty.wait_for(state="visible", timeout=5_000)
    assert empty.is_visible(), "空书架时 empty-shelf 应可见"

    # 空态仍给出状态说明，但不再提供立项入口
    empty_text = empty.inner_text()
    assert "书架是空的" in empty_text, f"空态缺状态文案:{empty_text!r}"
    assert empty.locator('a[href^="/propose.html"]').count() == 0

    # 不应有书卡
    assert page.locator(".book-card").count() == 0


def test_homepage_empty_shelf_offers_independent_create_book(page, base_url):
    """books 为空时展示 Q-1 独立建书入口，不回到已摘除立项页。

    派发单 2026-07-04 [P8-M3-pre] T0 第②项:首页去重复「立项新书」按钮。
    Q-1 恢复的是只收书名和题材的独立建书入口。
    """
    page.route("**/api/books", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({"books": [], "count": 0})
    ))

    page.goto("/")
    page.wait_for_load_state("networkidle", timeout=10_000)

    empty = page.locator("#empty-shelf")
    empty.wait_for(state="visible", timeout=5_000)

    # 独立建书入口可见，章节继续入口仍隐藏。
    qa_empty = page.locator("#quick-actions-empty")
    assert qa_empty.is_visible()
    assert qa_empty.locator("#create-book-empty-button").is_visible()
    assert qa_empty.locator('a[href^="/propose.html"]').count() == 0
    # quick-actions 也应隐藏(books 空时没有 continue 可言)
    qa = page.locator("#quick-actions")
    assert not qa.is_visible(), "books 空时 #quick-actions 应隐藏"


def test_homepage_continue_link_ignores_removed_review_progress(page, base_url):
    """继续入口只使用 last_chapter，不再使用已删除审读页的进度。"""
    fake_books = [
        {"name": "RecentBook", "title": "最近读的书", "genre": "xuanhuan",
         "last_chapter": 10, "last_reviewed": 7},
    ]
    page.route("**/api/books", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({"books": fake_books, "count": 1})
    ))

    page.goto("/")
    page.wait_for_load_state("networkidle", timeout=10_000)

    continue_link = page.locator("#continue-link")
    continue_link.wait_for(state="visible", timeout=5_000)
    text = continue_link.text_content() or ""
    assert "最近读的书" in text
    assert "写到第 10 章" in text, f"快捷链接文案不对:{text!r}"
    assert "审到" not in text


def test_homepage_continue_link_uses_last_chapter(page, base_url):
    """有 last_chapter 时，快捷显示“上次写到第 N 章”。"""
    fake_books = [
        {"name": "WritingOnly", "title": "只写未审", "genre": "xuanhuan",
         "last_chapter": 4, "last_reviewed": None},
    ]
    page.route("**/api/books", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({"books": fake_books, "count": 1})
    ))

    page.goto("/")
    page.wait_for_load_state("networkidle", timeout=10_000)

    # quick-actions 应可见,quick-actions-empty 应隐藏
    qa = page.locator("#quick-actions")
    qa.wait_for(state="visible", timeout=5_000)
    text = qa.text_content() or ""
    assert "只写未审" in text
    assert "写到第 4 章" in text, f"继续入口写作进度不对:{text!r}"


def test_homepage_archived_section_hides_test_kind_books(page, base_url):
    """P8-M3-pre T0.1: kind='test' 的书不出现在主网格,收折叠区。"""
    mock_books = [
        {"name": "RealBook", "title": "真书", "genre": "xuanhuan",
         "last_chapter": 5, "kind": "real"},
        {"name": "TestBook", "title": "测试书", "genre": "scifi",
         "last_chapter": None, "kind": "test"},
    ]
    page.route("**/api/books", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({"books": mock_books, "count": 2})
    ))
    page.goto("/")
    page.wait_for_load_state("networkidle", timeout=10_000)

    # 主网格应是 1 张 real 书卡
    main_cards = page.locator("#book-list .book-card")
    assert main_cards.count() == 1, f"主网格应为 1 张卡,实际:{main_cards.count()}"
    main_text = main_cards.first.text_content() or ""
    assert "真书" in main_text, f"real 书卡内容不对:{main_text!r}"

    # 折叠区可见,summary 含计数
    arch = page.locator("#archived-section")
    assert arch.is_visible(), "有 kind!='real' 书时折叠区应可见"
    summary = page.locator("#archived-section summary")
    assert "测试" in (summary.text_content() or ""), "summary 应含'测试'"
    assert "1" in (summary.text_content() or ""), "summary 应显示计数 1"

    # 展开折叠区,test 书应在其中
    summary.click()
    page.wait_for_timeout(300)
    arch_cards = page.locator("#archived-book-list .book-card")
    assert arch_cards.count() == 1, f"折叠区应为 1 张卡,实际:{arch_cards.count()}"
    arch_text = arch_cards.first.text_content() or ""
    assert "测试书" in arch_text, f"test 书卡内容不对:{arch_text!r}"
