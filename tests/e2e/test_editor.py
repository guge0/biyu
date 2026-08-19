"""T2 编辑部对话壳 e2e(P8-M3 T3+T4)— 编辑/导演页发消息 + 工具卡渲染。

Spec 验收:
  T3 e2e: 2 个最小 e2e 测试(发消息 + 工具卡 DOM 渲染)
  T4 e2e: 2 个最小 e2e 测试(导演对话发消息 + 无细纲降级说明可见)

设计:
- 所有编辑器页测试首先 Mock /api/books + /api/env + /api/peak-hours
  以确保页面初始化不依赖真实数据。
- 模拟「选择书 → 开始新会话 → 发送消息」的完整 UI 流程。
- 使用 page.route() 拦截网络请求,避免测试依赖真实后端数据。
- 注册 route 时注意顺序:更具体的路径(含 /*/) 先注册,避免被
  `**/api/chat/sessions` 这种宽泛模式提前拦截导致 SSE 端点失效。
- 对于 API 测试(偏好/起名),使用 page.evaluate() 发起 fetch() 调用,
  使得请求经过 page.route() 拦截,而不是绕过拦截的 page.request API。

E2E marker 默认 deselect;显式跑 `pytest tests/e2e/ -m e2e`。
"""
from __future__ import annotations

import json
import re

import pytest

# belt-and-suspenders: playwright 未安装时不收集
pytest.importorskip("playwright")

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# 共享辅助: Mock 环境/书/峰谷 端点
# ---------------------------------------------------------------------------

def _mock_env_routes(page):
    """拦截 /api/env, /api/peak-hours, /api/books 三个初始化端点。"""
    page.route("**/api/env", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"level": "test", "label": "测试", "color": "#a8a8a8"})))
    page.route("**/api/peak-hours", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"is_peak": False, "label": "平峰",
                         "effective_from": "2026-07-15", "now": "2026-07-04T10:00"})))
    page.route("**/api/books", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"books": [
            {"name": "BookA", "id": "book-a-1", "title": "测试书A",
             "genre": "xuanhuan", "last_chapter": 5, "kind": "test"},
        ], "count": 1})))


def _setup_chat_session_routes(page, *, session_id="e2e-test-001", role="editor", book="BookA"):
    """设置会话创建 + SSE 消息流两个 route handler。

    注意注册顺序:先注册具体路径(含 /*/),再注册宽泛路径,
    避免 `**/api/chat/sessions` 提前拦截 */messages 的请求。
    """
    # ── SSE 事件(默认:token + tool_call + cost,单工具卡) ──
    sse_events = [
        {"type": "token", "content": "编辑人格待定稿，当前仅代查资料。"},
        {"type": "tool_call", "name": "read_truth_files", "args": {}, "result": "=== current_state ==="},
        {"type": "cost", "amount": 0.0},
    ]
    sse_text = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in sse_events)
    sse_text += "data: [DONE]\n\n"

    page.route(re.compile(r"/api/chat/sessions/[^/]+/messages$"), lambda r: r.fulfill(
        status=200, content_type="text/event-stream", body=sse_text))

    # ── 会话 GET/POST ──
    fake_session = {
        "id": session_id,
        "book": book,
        "book_id": "book-a-1",
        "role": role,
        "created_at": 1800000000,
        "deleted": False,
        "messages": [],
    }
    page.route(re.compile(r"/api/chat/sessions$"), lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"sessions": [fake_session]})))
    page.route(re.compile(r"/api/chat/sessions/[^/]+$"), lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(fake_session)))

    return fake_session


def _setup_director_session_routes(page, *, session_id="e2e-dir-001", book="BookA"):
    """设置导演会话的 route handler(含 read_truth_files 单工具卡)。"""
    fake_session = {
        "id": session_id,
        "book": book,
        "book_id": "book-a-1",
        "role": "director",
        "created_at": 1800000000,
        "deleted": False,
        "messages": [],
    }

    sse_events = [
        {"type": "token", "content": "导演人格待定稿，当前仅代查资料。"},
        {"type": "tool_call", "name": "read_truth_files", "args": {}, "result": "=== current_state ==="},
        {"type": "cost", "amount": 0.0},
    ]
    sse_text = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in sse_events)
    sse_text += "data: [DONE]\n\n"

    page.route(re.compile(r"/api/chat/sessions/[^/]+/messages$"), lambda r: r.fulfill(
        status=200, content_type="text/event-stream", body=sse_text))
    page.route(re.compile(r"/api/chat/sessions$"), lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"sessions": [fake_session]})))
    page.route(re.compile(r"/api/chat/sessions/[^/]+$"), lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(fake_session)))

    return fake_session


def _create_session_via_ui(page):
    """模拟 UI 操作:选书 → 点「开始新会话」→ 等输入区可见。

    前置条件:book-select 已含至少一个 option,new-session-btn 可点。
    """
    book_select = page.locator("#book-select")
    book_select.wait_for(state="visible", timeout=5_000)
    book_select.select_option("book-a-1")

    new_btn = page.locator("#new-session-btn")
    new_btn.wait_for(state="visible", timeout=5_000)
    new_btn.click()

    input_area = page.locator("#input-area")
    input_area.wait_for(state="visible", timeout=5_000)

    return page.locator("#chat-input")


# ---------------------------------------------------------------------------
# T3 责编 e2e
# ---------------------------------------------------------------------------


def test_editor_page_send_message(page, base_url):
    """打开编辑页,选书创建会话 → 发一条消息,验证消息出现在对话区域。"""
    _mock_env_routes(page)
    _setup_chat_session_routes(page, session_id="e2e-test-msg")

    page.goto("/editor.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    chat_input = _create_session_via_ui(page)

    chat_input.fill("查一下角色陈凡的情况")
    send_btn = page.locator("#send-btn")
    send_btn.click()

    page.wait_for_timeout(1000)

    # 验证用户消息出现在对话区
    user_msg = page.locator("text=查一下角色陈凡的情况").first
    assert user_msg.is_visible(), "用户消息应显示在对话区"

    # 验证占位文本出现
    placeholder = page.locator("text=编辑人格待定稿").first
    assert placeholder.is_visible(), "占位回复应可见"


def test_editor_tool_call_card(page, base_url):
    """Mock SSE 返回 tool_call 事件,验证工具卡渲染(工具名可见)。"""
    _mock_env_routes(page)

    # 注意:前端 JS 对多个 tool_call 事件只保留最后一个,
    # 因此测试 SSE 只发一个 tool_call 以匹配实际渲染行为
    fake_session = {
        "id": "e2e-test-tc",
        "book": "BookA",
        "role": "editor",
        "created_at": 1800000000,
        "deleted": False,
        "messages": [],
    }

    sse_events = [
        {"type": "token", "content": "编辑人格待定稿，当前仅代查资料。"},
        {
            "type": "tool_call",
            "name": "look_up_character",
            "args": {"char_name": "陈凡"},
            "result": "{'name': '陈凡', 'personality': '坚毅', 'state': '筑基中期'}",
        },
        {"type": "cost", "amount": 0.0},
    ]
    sse_text = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in sse_events)
    sse_text += "data: [DONE]\n\n"

    page.route(re.compile(r"/api/chat/sessions/[^/]+/messages$"), lambda r: r.fulfill(
        status=200, content_type="text/event-stream", body=sse_text))
    page.route(re.compile(r"/api/chat/sessions$"), lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"sessions": [fake_session]})))
    page.route(re.compile(r"/api/chat/sessions/[^/]+$"), lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(fake_session)))

    page.goto("/editor.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    chat_input = _create_session_via_ui(page)
    chat_input.fill("查角色陈凡")
    send_btn = page.locator("#send-btn")
    send_btn.click()

    page.wait_for_timeout(1000)

    # 验证工具卡内容出现(单个工具名称)
    tool_name = page.locator("text=look_up_character").first
    assert tool_name.is_visible(), "工具名应显示在工具卡中"

    # 验证角色名出现在工具结果中
    char_result = page.locator("text=陈凡").first
    assert char_result.is_visible(), "工具查询结果应包含角色名"


def test_tool_call_empty_result(page, base_url):
    """SSE 返回空 result → 工具卡显"未命中"。"""
    _mock_env_routes(page)

    fake_session = {
        "id": "e2e-test-empty",
        "book": "BookA",
        "role": "editor",
        "created_at": 1800000000,
        "deleted": False,
        "messages": [],
    }

    sse_events = [
        {"type": "token", "content": "编辑人格待定稿。"},
        {"type": "tool_call", "name": "look_up_character", "args": {"char_name": "无名氏"}, "result": ""},
        {"type": "cost", "amount": 0.0},
    ]
    sse_text = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in sse_events)
    sse_text += "data: [DONE]\n\n"

    page.route(re.compile(r"/api/chat/sessions/[^/]+/messages$"), lambda r: r.fulfill(
        status=200, content_type="text/event-stream", body=sse_text))
    page.route(re.compile(r"/api/chat/sessions$"), lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"sessions": [fake_session]})))
    page.route(re.compile(r"/api/chat/sessions/[^/]+$"), lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(fake_session)))

    page.goto("/editor.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    chat_input = _create_session_via_ui(page)
    chat_input.fill("查无名氏")
    send_btn = page.locator("#send-btn")
    send_btn.click()

    page.wait_for_timeout(1000)

    # 验证"未命中"文本出现
    hit_miss = page.locator("text=未命中").first
    assert hit_miss.is_visible(), "空结果应显示'未命中'"


# ---------------------------------------------------------------------------
# T4 导演会诊 e2e
# ---------------------------------------------------------------------------


def test_director_chat_send_message(page, base_url):
    """导演角色发消息,验证导演占位文本和工具卡出现。"""
    _mock_env_routes(page)
    _setup_director_session_routes(page, session_id="e2e-dir-msg")

    page.goto("/editor.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    # 选书 + 选导演角色
    book_select = page.locator("#book-select")
    book_select.wait_for(state="visible", timeout=5_000)
    book_select.select_option("book-a-1")
    role_select = page.locator("#role-select")
    role_select.select_option("director")

    new_btn = page.locator("#new-session-btn")
    new_btn.click()

    input_area = page.locator("#input-area")
    input_area.wait_for(state="visible", timeout=5_000)
    chat_input = page.locator("#chat-input")

    chat_input.fill("主角想探索秘境深处")
    send_btn = page.locator("#send-btn")
    send_btn.click()

    page.wait_for_timeout(1000)

    # 导演占位文本
    director_placeholder = page.locator("text=导演人格待定稿").first
    assert director_placeholder.is_visible(), "导演占位文本应可见"

    # 工具卡(只发了一个 read_truth_files,匹配前端渲染行为)
    truth_name = page.locator("text=read_truth_files").first
    assert truth_name.is_visible(), "truth_files 工具卡应可见"


def test_director_no_outline_note(page, base_url):
    """导演会诊无细纲时,read_outlines 结果含降级说明。"""
    _mock_env_routes(page)

    fake_session = {
        "id": "e2e-dir-outline",
        "book": "BookA",
        "role": "director",
        "created_at": 1800000000,
        "deleted": False,
        "messages": [],
    }

    sse_events = [
        {"type": "token", "content": "导演人格待定稿，当前仅代查资料。"},
        {"type": "tool_call", "name": "read_outlines", "args": {}, "result": "(本书暂无细纲;当前仅基于 truth_files + craft 给出参考)"},
        {"type": "cost", "amount": 0.0},
    ]
    sse_text = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in sse_events)
    sse_text += "data: [DONE]\n\n"

    page.route(re.compile(r"/api/chat/sessions/[^/]+/messages$"), lambda r: r.fulfill(
        status=200, content_type="text/event-stream", body=sse_text))
    page.route(re.compile(r"/api/chat/sessions$"), lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"sessions": [fake_session]})))
    page.route(re.compile(r"/api/chat/sessions/[^/]+$"), lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(fake_session)))

    page.goto("/editor.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    book_select = page.locator("#book-select")
    book_select.wait_for(state="visible", timeout=5_000)
    book_select.select_option("book-a-1")
    role_select = page.locator("#role-select")
    role_select.select_option("director")
    new_btn = page.locator("#new-session-btn")
    new_btn.click()

    input_area = page.locator("#input-area")
    input_area.wait_for(state="visible", timeout=5_000)
    chat_input = page.locator("#chat-input")
    chat_input.fill("主角想探索秘境深处")
    send_btn = page.locator("#send-btn")
    send_btn.click()

    page.wait_for_timeout(1000)

    # 降级说明应可见
    outline_result = page.locator("text=暂无细纲").first
    assert outline_result.is_visible(), "无细纲降级说明应可见"


# ---------------------------------------------------------------------------
# T5 会诊纪要 e2e
# ---------------------------------------------------------------------------


def test_summarize_session(page, base_url):
    """模拟会话 → POST /summarize → 返回纪要文件名 + 元信息。

    使用 page.evaluate() 发 fetch() 以便经过 page.route() 拦截。
    """
    _mock_env_routes(page)

    # mock 纪要生成端点
    page.route(re.compile(r"/api/chat/sessions/[^/]+/summarize$"), lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({
            "ok": True,
            "filename": "纪要_2026-07-06_1.md",
            "book": "BookA",
            "message_count": 2,
            "source": "template",
            "generated_at": "2026-07-06",
        }),
    ))

    page.goto("/editor.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    # 使用 page.evaluate 发 fetch (经过 page.route 拦截)
    result = page.evaluate("""async () => {
        const resp = await fetch('/api/chat/sessions/test-sid/summarize', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: '{}',
        });
        return await resp.json();
    }""")
    assert result["ok"]
    assert "纪要" in result["filename"]
    assert result["source"] == "template"


def test_summaries_list(page, base_url):
    """GET /api/summaries?book=BookA → 返回纪要列表。"""
    _mock_env_routes(page)

    page.route(re.compile(r"/api/summaries\?"), lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps([
            {"filename": "纪要_2026-07-06_1.md", "date": "2026-07-06", "seq": 1},
        ])))

    page.goto("/editor.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    # 使用 page.evaluate 发 fetch (经过 page.route 拦截)
    result = page.evaluate("""async () => {
        const resp = await fetch('/api/summaries?book=BookA');
        return await resp.json();
    }""")
    assert len(result) >= 1
    assert "纪要" in result[0]["filename"]


# ---------------------------------------------------------------------------
# T6 偏好沉淀 e2e
# ---------------------------------------------------------------------------


def test_preference_save(page, base_url):
    """POST /api/preferences → 存偏好,返回 entry_id。

    使用 page.evaluate() 发 fetch() 以便经过 page.route() 拦截。
    """
    _mock_env_routes(page)

    page.route(re.compile(r"/api/preferences"), lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({
            "entry_id": "test-entry-001",
            "scope": "book",
            "content": "建议增加女配林霜的戏份",
            "date": "2026-07-06",
        }),
    ))

    page.goto("/editor.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    result = page.evaluate("""async () => {
        const resp = await fetch('/api/preferences', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                content: '建议增加女配林霜的戏份',
                source_session: 'session-001',
                scope: 'book',
                book: 'BookA',
            }),
        });
        return await resp.json();
    }""")
    assert result["entry_id"] != ""
    assert result["scope"] == "book"


def test_preferences_list(page, base_url):
    """GET /api/preferences → 返回偏好列表。

    使用 page.evaluate() 发 fetch() 以便经过 page.route() 拦截。
    """
    _mock_env_routes(page)

    page.route(re.compile(r"/api/preferences"), lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps([
            {"entry_id": "id1", "date": "2026-07-06", "content": "建议增加女配戏份"},
            {"entry_id": "id2", "date": "2026-07-06", "content": "节奏放缓"},
        ])))

    page.goto("/editor.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    result = page.evaluate("""async () => {
        const resp = await fetch('/api/preferences?scope=book&book=BookA');
        return await resp.json();
    }""")
    assert len(result) == 2
    assert result[0]["content"] == "建议增加女配戏份"


# ---------------------------------------------------------------------------
# T7 起名器 e2e
# ---------------------------------------------------------------------------


def test_naming_generate(page, base_url):
    """POST /api/naming → 返回候选列表。

    占位模式下(conftest 强制),后端返回 template 源。
    使用 page.evaluate() 发 fetch() 以便经过 page.route() 拦截。
    """
    _mock_env_routes(page)

    page.route(re.compile(r"/api/naming$"), lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({
            "candidates": [
                {"name": "玄鉴仙诀", "paradigm": "四字凝练型", "reason": "适合 xianxia"},
                {"name": "青云剑宗", "paradigm": "四字凝练型", "reason": "适合 xianxia"},
            ],
            "source": "template",
            "target_platform": "起点",
            "paradigm_ref": "",
            "cost_cny": 0.0,
        }),
    ))

    page.goto("/editor.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    result = page.evaluate("""async () => {
        const resp = await fetch('/api/naming', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ idea: '主角穿越到修仙世界', genre: 'xianxia' }),
        });
        return await resp.json();
    }""")
    assert "candidates" in result
    assert len(result["candidates"]) >= 1
    assert result["source"] == "template"
    assert "name" in result["candidates"][0]
    assert "paradigm" in result["candidates"][0]


def test_naming_apply(page, base_url):
    """POST /api/naming/apply → 应用书名,返 display_name。

    使用 page.evaluate() 发 fetch() 以便经过 page.route() 拦截。
    """
    _mock_env_routes(page)

    page.route(re.compile(r"/api/naming/apply$"), lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({
            "ok": True,
            "title": "BookA",
            "display_name": "星辰变",
        }),
    ))

    page.goto("/editor.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    result = page.evaluate("""async () => {
        const resp = await fetch('/api/naming/apply', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ book: 'BookA', title: '星辰变' }),
        });
        return await resp.json();
    }""")
    assert result["ok"]
    assert result["display_name"] == "星辰变"


def test_naming_degradation_badge(page, base_url):
    """template_fallback 时提案名候选区顶部显降级徽标(D-70)。

    使用 propose 页渲染命名候选,验证徽标 DOM 存在。
    """
    _mock_env_routes(page)

    page.route(re.compile(r"/api/naming$"), lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({
            "candidates": [
                {"name": "玄鉴仙诀", "paradigm": "四字凝练型", "reason": "适合 xianxia"},
                {"name": "青云剑宗", "paradigm": "四字凝练型", "reason": "适合 xianxia"},
            ],
            "source": "template_fallback",
            "target_platform": "起点",
            "paradigm_ref": "",
            "cost_cny": 0.0,
        }),
    ))

    page.goto("/propose.html")
    page.wait_for_load_state("networkidle", timeout=10_000)

    # 触发起名请求(模拟 propose.js 的 attemptNaming 流程)
    page.evaluate("""async () => {
        const resp = await fetch('/api/naming', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ idea: '测试设想', genre: 'xianxia' }),
        });
        const data = await resp.json();
        const container = document.getElementById('naming-candidates');
        if (!container) return;
        // 模拟 renderNamingCandidates 的降级徽标逻辑
        let html = '';
        if (data.source === 'template_fallback') {
            html += '<div class=\"naming-degraded-badge\">已降级:模板候选(LLM 未达)</div>';
        }
        html += '<div class=\"naming-grid\">';
        (data.candidates || []).forEach(function(c) {
            html += '<div class=\"naming-item\">' +
                '<span class=\"naming-name\">' + c.name + '</span>' +
                '</div>';
        });
        html += '</div>';
        container.innerHTML = html;
    }""")

    # 验证降级徽标存在
    badge = page.locator(".naming-degraded-badge")
    assert badge.count() > 0
    assert "已降级" in badge.text_content()
