"""S-4A 责编助手引擎 — 工具调用循环 + 工具清单 + 确认闸。

分层(工单 2026-11-03):
- tools.py: ToolSpec 与工具清单(read 只读 / run 只登记待确认,绝不直接执行)
- confirmations.py: 待确认动作存储(data/<book>/consults/pending_actions.jsonl)
- loop.py: run_agent_turn 工具调用循环(事件流)
- prompt.py: 系统提示词常量(不新建 prompts/ 下的文件)

权限三档(议题书):只读随时可用;花钱动作先报预估、作者确认才跑;
批准方案/批准章节/采纳版本是作者钦定,agent 不可代批(FORBIDDEN_TOOL_NAMES)。
"""
from __future__ import annotations

from .confirmations import RUN_ACTION_IDS, PendingActionStore
from .loop import run_agent_turn
from .prompt import AGENT_SYSTEM_PROMPT
from .tools import (
    FORBIDDEN_TOOL_NAMES,
    ToolSpec,
    build_tool_specs,
    execute_tool,
    openai_tools_payload,
)

__all__ = [
    "AGENT_SYSTEM_PROMPT",
    "FORBIDDEN_TOOL_NAMES",
    "RUN_ACTION_IDS",
    "PendingActionStore",
    "ToolSpec",
    "build_tool_specs",
    "execute_tool",
    "openai_tools_payload",
    "run_agent_turn",
]
