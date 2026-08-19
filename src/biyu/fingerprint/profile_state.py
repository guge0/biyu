"""Atomic persistence for the one active voiceprint profile."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def profile_state_path(book_dir: Path) -> Path:
    return Path(book_dir) / "声纹" / "选择.json"


def _legacy_active(value: dict[str, Any]) -> str | None:
    """Deterministically collapse the retired selected/order contract."""
    selected = list(dict.fromkeys(
        str(item) for item in value.get("selected", []) if str(item)
    )) if isinstance(value.get("selected", []), list) else []
    order = list(dict.fromkeys(
        str(item) for item in value.get("order", []) if str(item)
    )) if isinstance(value.get("order", []), list) else []
    if "book:self" in selected:
        return "book:self"
    return next((item for item in order if item in selected), selected[0] if selected else None)


def load_profile_state(book_dir: Path) -> dict[str, Any]:
    """Read the new contract and compatibly interpret old selected/order state."""
    path = profile_state_path(book_dir)
    if not path.exists():
        return {"active": None, "saved": False, "migrated_from_legacy": False}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("声纹选择状态格式无效")
    if "active" in value:
        active = value["active"]
        if active is not None and not isinstance(active, str):
            raise ValueError("声纹选择状态格式无效")
        return {
            "active": active.strip() if isinstance(active, str) and active.strip() else None,
            "saved": True,
            "migrated_from_legacy": False,
        }
    active = _legacy_active(value)
    save_profile_state(book_dir, active)
    return {"active": active, "saved": True, "migrated_from_legacy": True}


def save_profile_state(
    book_dir: Path,
    active: str | None = None,
) -> dict[str, Any]:
    """Write only the D-160 contract."""
    active = str(active).strip() if active is not None else None
    active = active or None
    path = profile_state_path(book_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"active": active}
    handle, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return {**payload, "saved": True, "migrated_from_legacy": False}
