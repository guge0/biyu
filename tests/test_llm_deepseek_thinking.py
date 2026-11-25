"""S-8-3 · DeepSeekAdapter thinking 透传测试(TL 11-19 实测降分全失败的根因)。

deepseek-v4-pro/flash 默认开思考:降分每次 max_tokens=2000,思考把额度吃光,
content 为空 → 每稿守卫判「空」。请求体加 "thinking": {"type": "disabled"}
后正常(DeepSeek 接口接受这个字段)。glm 适配器的透传(S-6)没有单独测试条,
这里照 test_llm_glm_tools.py 的 mock httpx 方式给 DeepSeek 的 generate/stream
各补一条「给了就带、不给就不带」。

零烧钱,纯 mock httpx 验证 payload 透传。
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

from biyu.llm.deepseek import DeepSeekAdapter

THINKING_OFF = {"type": "disabled"}


def _make_adapter() -> DeepSeekAdapter:
    """建一个 DeepSeekAdapter 测试实例(假 key,不真调 API)。"""
    return DeepSeekAdapter(
        model_name="deepseek-v4-pro",
        api_key="test-fake-key",
        base_url="https://fake-deepseek.test/v1",
        max_tokens=2000,
    )


def _mock_response_data() -> dict[str, Any]:
    """模拟 DeepSeek API 成功响应 body(关思考后 content 正常有值)。"""
    return {
        "id": "fake-id",
        "model": "deepseek-v4-pro",
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
    """mock httpx.AsyncClient 的 generate 形态:记录 post 的 json,返回 canned 响应。"""
    captured: dict = {}

    class _FakeResponse:
        def __init__(self, data):
            self._data = data
            self.status_code = 200

        def json(self):
            return self._data

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
            self._captured["json"] = json
            return self._resp

    return captured, _FakeClient(captured, fake_resp)


def _capture_stream_payload(lines: list[str]) -> tuple[dict, Any]:
    """mock httpx.AsyncClient 的 stream 形态:记录 client.stream 的 json,回放 SSE 行。"""

    class _FakeStreamResponse:
        def __init__(self, sse_lines):
            self.status_code = 200
            self._lines = sse_lines

        async def aread(self) -> bytes:
            return b""

        async def aiter_lines(self):
            for line in self._lines:
                yield line

    captured: dict = {}
    resp = _FakeStreamResponse(lines)

    class _FakeStreamCtx:
        async def __aenter__(self):
            return resp

        async def __aexit__(self, *args):
            return False

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, method, url, headers=None, json=None, **kwargs):
            captured["url"] = url
            captured["json"] = json
            return _FakeStreamCtx()

    return captured, _FakeClient()


def test_generate_thinking_given_included_absent_omitted():
    """generate:给了 thinking 就原样进 payload;不给就不加(写章管线行为不变)。"""
    adapter = _make_adapter()

    captured, mock_client = _capture_payload()
    with patch("biyu.llm.deepseek.httpx.AsyncClient", return_value=mock_client):
        asyncio.run(adapter.generate(
            messages=[{"role": "user", "content": "改写这段"}],
            thinking=THINKING_OFF,
        ))
    assert captured["json"].get("thinking") == THINKING_OFF, "DeepSeekAdapter 未透传 thinking 到 payload"

    captured, mock_client = _capture_payload()
    with patch("biyu.llm.deepseek.httpx.AsyncClient", return_value=mock_client):
        asyncio.run(adapter.generate(messages=[{"role": "user", "content": "你好"}]))
    assert "thinking" not in captured["json"], "不给 thinking 时不应加该字段"


def test_stream_thinking_given_included_absent_omitted():
    """stream:给了 thinking 就原样进 payload;不给就不加。"""
    adapter = _make_adapter()
    lines = ['data: {"choices":[{"delta":{"content":"改好了"}}]}', "data: [DONE]"]

    async def _consume(**kwargs) -> list[str]:
        chunks: list[str] = []
        async for text in adapter.stream([{"role": "user", "content": "hi"}], **kwargs):
            chunks.append(text)
        return chunks

    captured, mock_client = _capture_stream_payload(lines)
    with patch("biyu.llm.deepseek.httpx.AsyncClient", return_value=mock_client):
        chunks = asyncio.run(_consume(thinking=THINKING_OFF))
    assert chunks == ["改好了"]  # 假流式打通,断言的不是空气
    assert captured["json"].get("thinking") == THINKING_OFF, "stream 未透传 thinking 到 payload"

    captured, mock_client = _capture_stream_payload(lines)
    with patch("biyu.llm.deepseek.httpx.AsyncClient", return_value=mock_client):
        asyncio.run(_consume())
    assert "thinking" not in captured["json"], "不给 thinking 时不应加该字段"
