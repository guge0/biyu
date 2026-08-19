"""Safe, opt-in call summaries for Q-3 diagnostics."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_EVIDENCE_DIR_ENV = "BIYU_CALL_EVIDENCE_DIR"


def _tool_call_count(response: Any) -> int:
    raw = getattr(response, "raw", None)
    if not isinstance(raw, dict):
        return 0
    choices = raw.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return 0
    message = choices[0].get("message") or {}
    calls = message.get("tool_calls") or []
    return len(calls) if isinstance(calls, list) else 0


def _message_summary(message: dict) -> dict[str, int | str]:
    content = message.get("content")
    if content is None:
        content_length = 0
    elif isinstance(content, str):
        content_length = len(content)
    else:
        content_length = len(json.dumps(content, ensure_ascii=False))
    calls = message.get("tool_calls") or []
    return {
        "role": str(message.get("role") or ""),
        "content_length": content_length,
        "tool_call_count": len(calls) if isinstance(calls, list) else 0,
    }


def record_call_evidence(
    *,
    role: str,
    chapter_num: int,
    round_num: int,
    messages: list[dict],
    response: Any,
    final_round: bool,
) -> Path | None:
    """Append a metadata-only JSONL row when an external directory is explicit."""
    configured = os.environ.get(_EVIDENCE_DIR_ENV, "").strip()
    if not configured:
        return None
    evidence_dir = Path(configured).expanduser().resolve()
    repository_root = Path(__file__).resolve().parents[2]
    try:
        evidence_dir.relative_to(repository_root)
    except ValueError:
        pass
    else:
        raise ValueError("调用证据目录必须位于仓库之外")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / "call_evidence.jsonl"
    row = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "chapter": chapter_num,
        "round": round_num,
        "final_round": final_round,
        "messages": [_message_summary(message) for message in messages],
        "finish_reason": getattr(response, "finish_reason", None),
        "usage": {
            "prompt_tokens": int(getattr(response, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(response, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(response, "total_tokens", 0) or 0),
        },
        "response": {
            "text_length": len(getattr(response, "text", "") or ""),
            "tool_call_count": _tool_call_count(response),
        },
    }
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path
