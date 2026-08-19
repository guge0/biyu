"""GLMAdapter tools 透传测试(P8-M3R 白名单修复)。

核查日志 2026-07-08 夜 §3 异常 4:
  "GLMAdapter tools 不透传(src/biyu/llm/glm.py generate()):实测 GLM API 本身支持
   function-calling,只是 adapter 没打通;GLM 充值后补跑 GLM-1 任务甲前必须先修此项,
   否则 editor 多轮工具跑不通;挂账 code 修。"

零烧钱,纯 mock httpx 验证 payload 透传。
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from biyu.llm.glm import GLMAdapter


def _make_adapter() -> GLMAdapter:
    """建一个 GLMAdapter 测试实例(假 key,不真调 API)。"""
    return GLMAdapter(
        model_name="glm-4.6",
        api_key="test-fake-key",
        base_url="https://fake-glm.test/api",
        max_tokens=1000,
    )


def _mock_response_data() -> dict[str, Any]:
    """模拟 GLM API 成功响应 body。"""
    return {
        "id": "fake-id",
        "model": "glm-4.6",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "fake reply"},
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _capture_payload() -> tuple[dict, Any]:
    """建一个 mock httpx.AsyncClient,返 (captured_payload, mock_client)。

    httpx.AsyncClient 调用模式:
        async with httpx.AsyncClient(...) as client:
            resp = await client.post(url, headers=..., json=...)
            data = resp.json()
    所以 mock 需要:
        - __aenter__/__aexit__ 满足 async with
        - post(url, ...) 是 async 方法,返回带 .json() 和 .status_code 的对象
    """
    captured: dict = {}

    class _FakeResponse:
        def __init__(self, data):
            self._data = data
            self.status_code = 200

        def json(self):
            return self._data

        def raise_for_status(self):
            pass

    fake_resp = _FakeResponse(_mock_response_data())

    class _FakeClient:
        def __init__(self, captured_dict, resp):
            self._captured = captured_dict
            self._resp = resp

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            self._captured["url"] = url
            self._captured["headers"] = headers
            self._captured["json"] = json
            return self._resp

    mock_client = _FakeClient(captured, fake_resp)
    return captured, mock_client


# ---------------------------------------------------------------------------
# 测试 1:不带 tools 时,payload 不应含 tools 字段(向后兼容)
# ---------------------------------------------------------------------------


def test_glm_generate_without_tools_does_not_include_tools_in_payload():
    """不带 tools 参数时,payload 不应含 tools key(避免无意义空字段)。"""
    adapter = _make_adapter()
    captured, mock_client = _capture_payload()

    with patch("biyu.llm.glm.httpx.AsyncClient", return_value=mock_client):
        asyncio.run(adapter.generate(messages=[{"role": "user", "content": "hi"}]))

    payload = captured["json"]
    assert "model" in payload
    assert "messages" in payload
    assert "tools" not in payload, "不带 tools 时不应有 tools key"


# ---------------------------------------------------------------------------
# 测试 2(主修复目标):带 tools 时,payload 应透传 tools 字段
# ---------------------------------------------------------------------------


def test_glm_generate_with_tools_passes_tools_through_to_payload():
    """带 tools 参数时,payload 应包含 tools 字段透传给 GLM API。

    这是核查日志 2026-07-08 夜 §3 异常 4 的修复目标:
    GLM API 支持 function-calling,但 adapter 没把 tools 加到 payload。
    """
    adapter = _make_adapter()
    captured, mock_client = _capture_payload()

    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_chapter",
                "description": "读章节正文",
                "parameters": {"type": "object", "properties": {"n": {"type": "integer"}}},
            },
        }
    ]

    with patch("biyu.llm.glm.httpx.AsyncClient", return_value=mock_client):
        asyncio.run(
            adapter.generate(
                messages=[{"role": "user", "content": "看第 1 章"}],
                tools=tools,
            )
        )

    payload = captured["json"]
    assert "tools" in payload, "GLMAdapter 未透传 tools 到 payload(挂账 bug 未修)"
    assert payload["tools"] == tools, "tools 内容应原样透传"


# ---------------------------------------------------------------------------
# 测试 3:tools=[] 空列表时,不透传(避免 API 误判)
# ---------------------------------------------------------------------------


def test_glm_generate_with_empty_tools_list_does_not_include_tools():
    """tools=[] 空列表时,payload 不应含 tools key(与 deepseek adapter 行为一致)。"""
    adapter = _make_adapter()
    captured, mock_client = _capture_payload()

    with patch("biyu.llm.glm.httpx.AsyncClient", return_value=mock_client):
        asyncio.run(
            adapter.generate(
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
            )
        )

    payload = captured["json"]
    assert "tools" not in payload, "空 tools 列表不应透传"


# ---------------------------------------------------------------------------
# 测试 4:tool_choice 透传(可选,GLM 支持)
# ---------------------------------------------------------------------------


def test_glm_generate_with_tool_choice_passes_through():
    """tool_choice 参数也应透传("auto" / "none" / 具体 tool)。"""
    adapter = _make_adapter()
    captured, mock_client = _capture_payload()

    with patch("biyu.llm.glm.httpx.AsyncClient", return_value=mock_client):
        asyncio.run(
            adapter.generate(
                messages=[{"role": "user", "content": "hi"}],
                tools=[{"type": "function", "function": {"name": "x"}}],
                tool_choice="auto",
            )
        )

    payload = captured["json"]
    assert payload.get("tool_choice") == "auto", "tool_choice 未透传"
