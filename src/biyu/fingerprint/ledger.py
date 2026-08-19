"""Read-only access to the append-only author feedback ledger."""
from __future__ import annotations

import json
from pathlib import Path


def read_feedback_entries(book_dir: Path) -> list[dict]:
    """Return valid ledger objects without exposing a mutation path."""
    path = Path(book_dir) / "反馈账.jsonl"
    if not path.exists():
        return []
    entries: list[dict] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"反馈账第 {line_no} 行不是有效 JSON") from exc
        if not isinstance(item, dict):
            raise ValueError(f"反馈账第 {line_no} 行必须是 JSON 对象")
        entries.append(item)
    return entries
