"""S-4A — 各适配器 tool_calls 解析与透传测试(mock httpx,不真实调用任何模型 API)。

覆盖(工单测试节):
- tools / tool_choice 透传进请求 payload;
- message.tool_calls 解析进 LLMResponse.tool_calls;
- content 为 None 时 text 置 "",且有 tool_calls 不算空内容(detect_failure /
  generate_guarded 不抛 EmptyContentError);
- messages 中 assistant(tool_calls) / tool(tool_call_id) 原样发出。
"""
from __future__ import annotations

import json

import pytest

from biyu.llm.base import LLMAdapter, LLMResponse
from biyu.llm.deepseek import DeepSeekAdapter
from biyu.llm.doubao import DoubaoAdapter
from biyu.llm.glm import GLMAdapter
from biyu.llm.kimi import KimiAdapter
from biyu.llm.openai_compatible import OpenAICompatibleAdapter

TOOLS = [{
    "type": "function",
    "function": {
        "name": "read_chapter",
        "description": "读一章正文",
        "parameters": {"type": "object", "properties": {"chapter": {"type": "integer"}}},
    },
}]

RAW_CALL = {
    "id": "call_1",
    "type": "function",
    "function": {"name": "read_chapter", "arguments": "{\"chapter\": 1}"},
}

MESSAGES = [
    {"role": "system", "content": "你是责编"},
    {"role": "user", "content": "读第 1 章"},
    {"role": "assistant", "content": "", "tool_calls": [dict(RAW_CALL)]},
    {"role": "tool", "tool_call_id": "call_1", "content": "第一章正文"},
]


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


def _tool_call_payload() -> dict:
    """OpenAI 格式:只有 tool_calls、content 为 None 的响应。"""
    return {
        "model": "some-model",
        "choices": [{
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [dict(RAW_CALL)],
            },
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


@pytest.fixture
def capture() -> dict:
    return {}


def _install(monkeypatch: pytest.MonkeyPatch, payload: dict, capture: dict, module: str) -> None:
    """把适配器模块里的 httpx.AsyncClient 换成假客户端(记录 payload,返回 canned 响应)。"""

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None, **kwargs):
            capture["url"] = url
            capture["payload"] = json
            return _FakeResponse(payload)

    monkeypatch.setattr(module + ".httpx.AsyncClient", FakeAsyncClient)


def _adapters() -> list[tuple[str, object]]:
    return [
        ("biyu.llm.deepseek", DeepSeekAdapter(model_name="deepseek-chat", api_key="sk-test")),
        ("biyu.llm.glm", GLMAdapter(model_name="glm-4", api_key="sk-test")),
        ("biyu.llm.kimi", KimiAdapter(model_name="kimi-k2.5", api_key="sk-test")),
        (
            "biyu.llm.doubao",
            DoubaoAdapter(model_name="doubao", api_key="sk-test", endpoint_id="ep-123"),
        ),
        (
            "biyu.llm.openai_compatible",
            OpenAICompatibleAdapter(model_name="gpt-x", api_key="sk-test", base_url="https://example.com"),
        ),
    ]


@pytest.mark.parametrize("module,adapter", [pair for pair in _adapters()])
@pytest.mark.asyncio
async def test_adapter_parses_tool_calls(module, adapter, monkeypatch, capture):
    _install(monkeypatch, _tool_call_payload(), capture, module)
    response = await adapter.generate(MESSAGES, tools=TOOLS, tool_choice="auto")

    assert response.tool_calls == [RAW_CALL]
    assert response.text == ""  # content=None → text 置 ""
    assert response.finish_reason == "tool_calls"
    # 透传
    assert capture["payload"]["tools"] == TOOLS
    assert capture["payload"]["tool_choice"] == "auto"
    # messages 原样发出(含 assistant.tool_calls 与 role=tool/tool_call_id)
    assert capture["payload"]["messages"] == MESSAGES


@pytest.mark.parametrize("module,adapter", [pair for pair in _adapters()])
@pytest.mark.asyncio
async def test_adapter_without_tools_kwarg_unchanged(module, adapter, monkeypatch, capture):
    """不带 tools 调用时,payload 不出现 tools 键(行为与改动前一致)。"""
    payload = _tool_call_payload()
    payload["choices"][0]["message"] = {"role": "assistant", "content": "普通回复"}
    _install(monkeypatch, payload, capture, module)
    response = await adapter.generate([{"role": "user", "content": "你好"}])
    assert response.text == "普通回复"
    assert response.tool_calls is None
    assert "tools" not in capture["payload"]


@pytest.mark.asyncio
async def test_detect_failure_passes_with_tool_calls():
    assert LLMAdapter.detect_failure(LLMResponse(text="", model="m", tool_calls=[RAW_CALL])) is None
    assert LLMAdapter.detect_failure(LLMResponse(text="  ", model="m")) == "empty"


@pytest.mark.asyncio
async def test_generate_guarded_does_not_raise_on_tool_calls_only(monkeypatch, capture):
    """只回 tool_calls(无文本)时,空内容守卫不得抛 EmptyContentError。"""
    adapter = DeepSeekAdapter(model_name="deepseek-chat", api_key="sk-test")
    _install(monkeypatch, _tool_call_payload(), capture, "biyu.llm.deepseek")
    response = await adapter.generate_guarded(
        [{"role": "user", "content": "读第 1 章"}], tools=TOOLS,
    )
    assert response.tool_calls == [RAW_CALL]
    assert response.text == ""
