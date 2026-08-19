"""biyu ask 主逻辑 — 调用 LLM + function calling 回答查询。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .prompts import ASK_SYSTEM_PROMPT
from biyu.editor.tools import TOOL_DEFINITIONS, execute_tool


@dataclass
class AskResult:
    """ask 查询结果。"""
    answer: str
    tool_calls: list[str] = field(default_factory=list)
    total_cost: float = 0.0


async def ask(question: str, book_dir: Path, adapter) -> AskResult:
    """和书对话查询。

    Args:
        question: 用户问题。
        book_dir: 书目录。
        adapter: LLMAdapter 实例。

    Returns:
        AskResult 包含答案、工具调用记录、累计成本。
    """
    messages = [
        {"role": "system", "content": ASK_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    queries_used: list[str] = []
    total_cost = 0.0
    final_text = ""
    max_tool_rounds = 5

    for round_num in range(max_tool_rounds + 1):
        # 前几轮传入 tools，最后一轮不传（让 LLM 给出最终答案）
        call_kwargs = {
            "temperature": 0.1,
            "max_tokens": 2048,
        }
        if round_num < max_tool_rounds:
            call_kwargs["tools"] = TOOL_DEFINITIONS
        else:
            # 最后一轮：提示模型直接回答
            messages.append({"role": "user", "content": "请直接根据已获取的信息回答原始问题。不要再调用工具。"})

        resp = await adapter.generate(messages, **call_kwargs)
        total_cost += getattr(resp, "cost", 0.0)
        resp_text = resp.text or ""

        # 检查是否有 tool_calls
        tool_calls = _extract_tool_calls(resp)

        if not tool_calls:
            final_text = resp_text
            break

        # 执行工具调用
        # DeepSeek API 要求 assistant message 包含 tool_calls 字段
        # 且如果返回了 reasoning_content，必须传回
        assistant_msg = {"role": "assistant", "content": resp_text, "tool_calls": tool_calls}
        if resp.reasoning_content:
            assistant_msg["reasoning_content"] = resp.reasoning_content
        messages.append(assistant_msg)

        for tc in tool_calls:
            tool_name = tc["function"]["name"]
            tc_id = tc.get("id", "")
            try:
                tool_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                tool_args = {}

            tool_result = execute_tool(tool_name, tool_args, book_dir)
            queries_used.append(f"{tool_name}({json.dumps(tool_args, ensure_ascii=False)})")

            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": tool_result,
            })
    else:
        final_text = resp_text

    return AskResult(
        answer=_clean_answer(final_text),
        tool_calls=queries_used,
        total_cost=total_cost,
    )


def _clean_answer(text: str) -> str:
    """清理 LLM 输出中的 DSML 标记和其他工具调用残留。"""
    # 移除 DeepSeek DSML 标记
    text = re.sub(r"<\|[^|]*\|>[^<]*</\|[^|]*\|>", "", text)
    text = re.sub(r"<\|[^|]*\|>[^<]*", "", text)
    # 移除多余空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_tool_calls(resp) -> list[dict]:
    """从 LLMResponse 中提取 tool_calls。"""
    if resp.raw is None:
        return []

    choices = resp.raw.get("choices", [])
    if not choices:
        return []

    message = choices[0].get("message", {})
    tool_calls = message.get("tool_calls")
    if tool_calls:
        return tool_calls

    return []
