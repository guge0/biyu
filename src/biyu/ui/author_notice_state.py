"""Durable author-facing notice choices, independent from book content."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from biyu.secure_config import user_config_dir

ACK_KEY = "replica_unconfigured_acknowledged"
LOAD_ERROR = "界面状态没有读成功，未设置提醒已恢复显示。"


def author_notice_state_path() -> Path:
    return user_config_dir() / "author_ui_state.json"


def _resolved_path(path: Path | None) -> Path:
    return path if path is not None else author_notice_state_path()


def _read_mapping(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("author notice state must be an object")
    return value


def load_author_notice_state(path: Path | None = None) -> dict[str, Any]:
    """Read a notice state file; any invalid value fails safe to not acknowledged."""
    path = _resolved_path(path)
    if not path.exists():
        return {ACK_KEY: False, "load_error": ""}
    try:
        value = _read_mapping(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {ACK_KEY: False, "load_error": LOAD_ERROR}
    return {
        ACK_KEY: value.get(ACK_KEY) is True,
        "load_error": "",
    }


def acknowledge_replica_warning(path: Path | None = None) -> dict[str, Any]:
    """Persist acknowledgement atomically while retaining future state fields."""
    path = _resolved_path(path)
    value: dict[str, Any] = {}
    if path.exists():
        try:
            value = _read_mapping(path)
        except (OSError, ValueError, json.JSONDecodeError):
            value = {}
    value[ACK_KEY] = True
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return load_author_notice_state(path)
