"""Durable three-axis state for the chapter workbench."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STEPS = ("outline", "planning", "generation", "reading", "revision", "adoption", "review")
STEP_STAGE = {
    "outline": 0,
    "planning": 1,
    "generation": 2,
    "reading": 3,
    "revision": 3,
    "adoption": 3,
    "review": 4,
}


def asset_state(book_dir: Path, chapter: int) -> str:
    official = (book_dir / "chapters" / f"ch{chapter}.md").exists()
    candidate = (book_dir / "chapters" / "_pending" / f"ch{chapter}.md").exists()
    if official and candidate:
        return "both"
    if official:
        return "official"
    if candidate:
        return "candidate"
    return "none"


def _state_path(book_dir: Path, chapter: int) -> Path:
    return book_dir / "logs" / f"ch{chapter}" / "workbench_state.json"


def _legacy_step(book_dir: Path, chapter: int) -> str:
    """One-time migration fallback for books created before the step ledger."""
    outline = book_dir / "outlines" / f"ch{chapter}.md"
    planning = book_dir / "logs" / f"ch{chapter}" / "planning.md"
    review = book_dir / "判词" / f"ch{chapter}.md"
    assets = asset_state(book_dir, chapter)
    if review.exists() or assets == "official":
        return "review"
    if assets in {"candidate", "both"}:
        return "reading"
    if planning.exists():
        first = planning.read_text(encoding="utf-8").splitlines()[:1]
        if first and first[0].strip() == "status: 已批":
            return "generation"
        return "planning"
    if outline.exists():
        return "planning"
    return "outline"


def read_workbench_step(book_dir: Path, chapter: int) -> str:
    path = _state_path(book_dir, chapter)
    if path.exists():
        try:
            step = str(json.loads(path.read_text(encoding="utf-8")).get("step", ""))
            if step in STEPS:
                return step
        except (json.JSONDecodeError, OSError):
            pass
    return _legacy_step(book_dir, chapter)


def write_workbench_step(book_dir: Path, chapter: int, step: str) -> None:
    if step not in STEPS:
        raise ValueError(f"unknown workbench step: {step}")
    path = _state_path(book_dir, chapter)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    path.write_text(
        json.dumps(
            {**existing, "step": step, "updated_at": datetime.now(timezone.utc).isoformat()},
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def remember_diagnosis_return(book_dir: Path, chapter: int, step: str = "reading") -> None:
    path = _state_path(book_dir, chapter)
    value: dict[str, Any] = {}
    if path.exists():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            value = {}
    value["diagnosis_return_step"] = step
    value["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def pop_diagnosis_return(book_dir: Path, chapter: int) -> str:
    path = _state_path(book_dir, chapter)
    if not path.exists():
        return "reading"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "reading"
    step = str(value.pop("diagnosis_return_step", "reading"))
    value["step"] = step if step in STEPS else "reading"
    value["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(value["step"])


def has_diagnosis_return(book_dir: Path, chapter: int) -> bool:
    path = _state_path(book_dir, chapter)
    if not path.exists():
        return False
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("diagnosis_return_step"))
    except (json.JSONDecodeError, OSError):
        return False


def _latest_run_log(book_dir: Path, chapter: int) -> Path | None:
    run_dir = book_dir / "logs" / f"ch{chapter}" / "runs"
    logs = list(run_dir.glob("*.log")) if run_dir.exists() else []
    return max(logs, key=lambda path: (path.stat().st_mtime_ns, path.name)) if logs else None


def persisted_run_state(book_dir: Path, chapter: int) -> tuple[str, dict[str, Any]]:
    path = _latest_run_log(book_dir, chapter)
    if path is None:
        return "idle", {}
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            if key in {"run_id", "action", "status", "returncode", "error"}:
                fields[key] = value
    if fields.get("status") != "failed":
        return "idle", {}
    return "fail", {
        "run_id": fields.get("run_id", path.stem),
        "action": fields.get("action", ""),
        "reason": fields.get("error", "操作没有完成，请重试"),
        "log_path": str(path.relative_to(book_dir)),
    }
