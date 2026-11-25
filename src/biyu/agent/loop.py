"""S-4A 责编助手工具调用循环。

run_agent_turn(adapter, history, user_message, *, book, data_root, ...) 是一个
async 事件流生成器,产出工单规定的六类事件:
- {"type":"tool_start", name, args, ...}
- {"type":"tool_result", name, summary, ...}
- {"type":"pending_action", ...}(run 工具登记出的待确认动作,原样带记录字段)
- {"type":"text", content}
- {"type":"done", cost, steps}
- {"type":"error", message}

约定:
- 超过 max_steps 步(模型调用次数)强制收尾并告知用户;
- 未知工具名、参数 JSON 坏 → 转成 tool 结果回给模型,不崩;
- 模型层的异常(LLMError 等)→ error 事件收尾,由 API 层翻人话;
- 本模块不持久化、不调 UI;持久化由 API 层按事件做。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator

from biyu.agent.prompt import AGENT_SYSTEM_PROMPT
from biyu.agent.tools import build_tool_specs, execute_tool, openai_tools_payload

# tool_start/tool_result 附带的补写字段(供 API 层把会话历史写回 JSONL):
# - tool_call_id:对应 assistant.tool_calls[].id
# - step:第几次模型调用(一次调用的多个工具同 step;API 层按它分组写 assistant 消息)
# - content:tool_result 带完整结果文本(summary 是给前端看的短版)


def _parse_tool_args(raw: object) -> tuple[dict | None, str]:
    """解析 function.arguments(模型给的 JSON 字符串)。坏 JSON 返回 (None, 原因)。"""
    if raw is None or raw == "":
        return {}, ""
    if isinstance(raw, dict):
        return raw, ""
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError as exc:
        return None, str(exc)
    if not isinstance(parsed, dict):
        return None, "arguments 不是 JSON 对象"
    return parsed, ""


async def run_agent_turn(
    adapter,
    history: list[dict],
    user_message: str,
    *,
    book: str,
    data_root: Path,
    session_id: str | None = None,
    max_steps: int = 6,
) -> AsyncIterator[dict]:
    """跑一轮责编助手对话:模型 ↔ 工具循环,流式产出事件。"""
    data_root = Path(data_root)
    specs = build_tool_specs(book=book, data_root=data_root, session_id=session_id)
    by_name = {spec.name: spec for spec in specs}
    messages: list[dict] = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": user_message},
    ]
    tools_payload = openai_tools_payload(specs)
    cost = 0.0
    steps = 0
    try:
        while True:
            resp = await adapter.generate(messages, tools=tools_payload)
            steps += 1
            cost += float(getattr(resp, "cost", 0.0) or 0.0)
            tool_calls = list(getattr(resp, "tool_calls", None) or [])
            if tool_calls:
                if resp.text:
                    yield {"type": "text", "content": resp.text}
                # assistant 消息(带 tool_calls)原样进上下文,content 空时置 ""
                messages.append({
                    "role": "assistant",
                    "content": resp.text or "",
                    "tool_calls": tool_calls,
                })
                for tc in tool_calls:
                    function = tc.get("function", {}) if isinstance(tc, dict) else {}
                    name = str(function.get("name", ""))
                    call_id = tc.get("id") if isinstance(tc, dict) else None
                    raw_args = function.get("arguments")
                    yield {
                        "type": "tool_start",
                        "name": name,
                        "args": raw_args,
                        "tool_call_id": call_id,
                        "step": steps,
                    }
                    if name not in by_name:
                        result = (
                            f"(未知工具:{name}。可用工具:{'、'.join(by_name)})"
                        )
                        pending = None
                    else:
                        args, parse_error = _parse_tool_args(raw_args)
                        if parse_error:
                            result = f"(参数不是合法 JSON:{parse_error};请用合法 JSON 重新调用)"
                            pending = None
                        else:
                            outcome = execute_tool(by_name[name], args or {})
                            result = outcome.text
                            pending = outcome.pending
                    if pending is not None:
                        yield {"type": "pending_action", **pending}
                    yield {
                        "type": "tool_result",
                        "name": name,
                        "summary": result[:200],
                        "content": result,
                        "tool_call_id": call_id,
                        "step": steps,
                    }
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": result,
                    })
                if steps >= max_steps:
                    yield {
                        "type": "text",
                        "content": (
                            f"(已到单轮步数上限 {max_steps} 步,本轮到此收尾;"
                            "已经查到/登记的内容都保留,需要继续请再发一条消息。)"
                        ),
                    }
                    break
                continue
            yield {"type": "text", "content": resp.text or ""}
            break
        yield {"type": "done", "cost": round(cost, 6), "steps": steps}
    except Exception as exc:  # noqa: BLE001 — 模型层异常收成 error 事件,由 API 层翻人话
        # S-7d:中途失败也要把已花费用带出去,记账方不丢部分成本
        yield {"type": "error", "message": str(exc), "cost": round(cost, 6)}
