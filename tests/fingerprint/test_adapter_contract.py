"""adapter 契约测试 — D-39/D-40 教训，验证 adapter 包装层行为."""
import json
from unittest.mock import patch, AsyncMock

import pytest

from biyu.fingerprint.adapter import generate, generate_json, generate_sync


def _mock_api_response(text: str, cost: float = 0.01):
    """构建 mock 直接 API 返回."""
    return (
        text,
        {
            "prompt_tokens": 100,
            "completion_tokens": 200,
            "total_tokens": 300,
            "cost": cost,
            "model": "deepseek-v4-pro",
        },
    )


class TestGenerateContract:
    """契约 1: messages 完整传递"""

    @patch("biyu.fingerprint.adapter._direct_generate")
    def test_messages_passed_intact(self, mock_direct):
        mock_direct.return_value = _mock_api_response("hello")

        import asyncio
        result_text, usage = asyncio.run(
            generate(
                messages=[
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": "usr"},
                ],
                max_tokens=1000,
            )
        )

        assert result_text == "hello"
        assert usage["prompt_tokens"] == 100
        assert usage["completion_tokens"] == 200

        # 验证 messages 被完整传递
        call_args = mock_direct.call_args
        assert call_args[0][0] == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "usr"},
        ]
        assert call_args[0][1] == 1000  # max_tokens 作为位置参数传递

    """契约 2: max_tokens 传递"""

    @patch("biyu.fingerprint.adapter._direct_generate")
    def test_max_tokens_forwarded(self, mock_direct):
        mock_direct.return_value = _mock_api_response("text")

        import asyncio
        asyncio.run(generate(messages=[], max_tokens=5000))

        assert mock_direct.call_args[0][1] == 5000  # max_tokens 位置参数


class TestGenerateJsonContract:
    """契约 3: JSON 模式返回结构"""

    @patch("biyu.fingerprint.adapter._direct_generate")
    def test_json_parsed(self, mock_direct):
        json_text = json.dumps({"key": "value", "num": 42})
        mock_direct.return_value = _mock_api_response(json_text)

        import asyncio
        result, usage = asyncio.run(generate_json("test prompt"))

        assert result == {"key": "value", "num": 42}

    """契约 4: markdown 代码块剥离"""

    @patch("biyu.fingerprint.adapter._direct_generate")
    def test_markdown_wrapper_stripped(self, mock_direct):
        json_text = "```json\n" + json.dumps({"key": "value"}) + "\n```"
        mock_direct.return_value = _mock_api_response(json_text)

        import asyncio
        result, usage = asyncio.run(generate_json("test"))
        assert result == {"key": "value"}

    """契约 5: token usage 能被提取（成本追踪）"""

    @patch("biyu.fingerprint.adapter._direct_generate")
    def test_usage_extracted(self, mock_direct):
        mock_direct.return_value = _mock_api_response("{}")

        import asyncio
        _, usage = asyncio.run(generate_json("test"))

        assert "prompt_tokens" in usage
        assert "completion_tokens" in usage
        assert "cost" in usage
        assert "model" in usage
        assert isinstance(usage["cost"], float)

    """契约 5 补充: generate_sync 同步包装"""

    @patch("biyu.fingerprint.adapter._direct_generate")
    def test_generate_sync_works(self, mock_direct):
        mock_direct.return_value = _mock_api_response("sync result")

        text, usage = generate_sync(messages=[{"role": "user", "content": "hi"}])

        assert text == "sync result"
        assert usage["cost"] == 0.01
