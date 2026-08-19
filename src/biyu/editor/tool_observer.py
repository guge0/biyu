"""Editor lookup-tool observation seam.

Lookup tools are local reads, not separate LLM calls.  Usage attached to an
event therefore belongs to the *Editor response that requested the lookup*;
when one response requests multiple tools the same usage is shared and must
not be summed once per event.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from typing import Callable


logger = logging.getLogger(__name__)

ToolObserver = Callable[["ToolObservation"], None]

_QUERY_KEYS = {
    "look_up_character": "char_name",
    "look_up_setting": "keyword",
    "look_up_history": "chapter_or_keyword",
    "look_up_visual": "symbol",
}

_MISS_MARKERS = {
    "look_up_character": ("未找到角色", "角色数据不存在"),
    "look_up_setting": ("未找到", "worldbook 不存在"),
    "look_up_history": ("未找到", "无历史章节"),
    "look_up_visual": ("未出现", "无历史章节"),
}


@dataclass(frozen=True)
class ToolObservation:
    response_group: str
    tool_name: str
    query: str
    result: str
    matched: bool
    query_index: int
    response_round: int
    response_prompt_tokens: int
    response_completion_tokens: int
    response_total_tokens: int
    response_cost: float
    response_tool_call_count: int
    usage_scope: str = "triggering_response_shared"

    @property
    def return_count(self) -> int:
        """Best available count from Editor's current string-return contract."""
        if not self.matched:
            return 0
        try:
            import ast

            parsed = ast.literal_eval(self.result)
        except (SyntaxError, ValueError):
            return 1
        return len(parsed) if isinstance(parsed, (list, tuple, set)) else 1


def query_text(tool_name: str, arguments: dict) -> str:
    """Return the actual query field without guessing across tool schemas."""
    key = _QUERY_KEYS.get(tool_name)
    if key is not None:
        value = arguments.get(key, "")
        return "" if value is None else str(value)
    return json.dumps(arguments, ensure_ascii=False, sort_keys=True)


def result_matched(tool_name: str, result: str) -> bool:
    """Classify lookup results using the tools' existing explicit miss text."""
    if '"error"' in result:
        return False
    return not any(marker in result for marker in _MISS_MARKERS.get(tool_name, ()))


def notify_tool_observer(observer: ToolObserver | None, event: ToolObservation) -> None:
    """Keep optional statistics sinks from changing Editor review behaviour."""
    if observer is None:
        return
    try:
        observer(event)
    except Exception:
        logger.warning("Editor tool observer failed", exc_info=True)
