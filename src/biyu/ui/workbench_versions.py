"""Durable plan/candidate version cards and the author-facing recycle bin."""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _number(path: Path) -> int:
    match = re.search(r"v(\d+)", path.stem)
    return int(match.group(1)) if match else 0


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _plans_dir(book_dir: Path, chapter: int) -> Path:
    return book_dir / "logs" / f"ch{chapter}" / "plans"


def _outlines_dir(book_dir: Path, chapter: int) -> Path:
    """Durable outline snapshots live beside the chapter's other workbench assets."""
    return book_dir / "logs" / f"ch{chapter}" / "outlines"


def _outline_path(book_dir: Path, chapter: int) -> Path:
    return book_dir / "outlines" / f"ch{chapter}.md"


def current_outline_version(book_dir: Path, chapter: int) -> int | None:
    pointer = _outlines_dir(book_dir, chapter) / "current"
    try:
        value = int(pointer.read_text(encoding="utf-8").strip().removeprefix("v"))
    except (OSError, ValueError):
        return None
    return value if (_outlines_dir(book_dir, chapter) / f"outline_v{value}.md").exists() else None


def save_outline_version(book_dir: Path, chapter: int, content: str) -> int:
    """Snapshot content once, deduplicating identical outline versions."""
    directory = _outlines_dir(book_dir, chapter)
    directory.mkdir(parents=True, exist_ok=True)
    versions = sorted(directory.glob("outline_v*.md"), key=_number)
    existing = next((path for path in versions if path.read_text(encoding="utf-8") == content), None)
    version = _number(existing) if existing else (_number(versions[-1]) + 1 if versions else 1)
    if existing is None:
        (directory / f"outline_v{version}.md").write_text(content, encoding="utf-8")
        _write_json(directory / f"outline_v{version}.json", {"version": version, "created_at": _now()})
    (directory / "current").write_text(f"v{version}\n", encoding="utf-8")
    return version


def sync_outline_version(book_dir: Path, chapter: int) -> int | None:
    """Absorb a direct external edit the next time the application sees it."""
    outline = _outline_path(book_dir, chapter)
    # Do not make a GET create chapter logs for a pre-existing unmanaged outline.
    # Once any managed write created this directory, later direct edits are absorbed.
    if not outline.exists() or not _outlines_dir(book_dir, chapter).exists():
        return None
    return save_outline_version(book_dir, chapter, outline.read_text(encoding="utf-8"))


def list_outline_versions(book_dir: Path, chapter: int) -> list[dict[str, Any]]:
    directory = _outlines_dir(book_dir, chapter)
    current = current_outline_version(book_dir, chapter)
    result = []
    for path in sorted(directory.glob("outline_v*.md"), key=_number, reverse=True):
        version = _number(path)
        meta = _read_json(path.with_suffix(".json"))
        result.append({
            "version": version,
            "current": version == current,
            "created_at": meta.get("created_at", ""),
            "content": path.read_text(encoding="utf-8"),
        })
    return result


def select_outline_version(book_dir: Path, chapter: int, version: int) -> str:
    """Restore one snapshot while retaining the file being replaced as a version."""
    directory = _outlines_dir(book_dir, chapter)
    source = directory / f"outline_v{version}.md"
    if not source.exists():
        raise FileNotFoundError(f"细纲 v{version} 不存在")
    outline = _outline_path(book_dir, chapter)
    if outline.exists():
        save_outline_version(book_dir, chapter, outline.read_text(encoding="utf-8"))
    content = source.read_text(encoding="utf-8")
    outline.parent.mkdir(parents=True, exist_ok=True)
    outline.write_text(content, encoding="utf-8")
    (directory / "current").write_text(f"v{version}\n", encoding="utf-8")
    return content


def current_plan_version(book_dir: Path, chapter: int) -> int | None:
    pointer = _plans_dir(book_dir, chapter) / "current"
    try:
        value = int(pointer.read_text(encoding="utf-8").strip().removeprefix("v"))
    except (OSError, ValueError):
        return None
    return value if (_plans_dir(book_dir, chapter) / f"plan_v{value}.md").exists() else None


def save_plan_version(book_dir: Path, chapter: int, content: str) -> int:
    directory = _plans_dir(book_dir, chapter)
    directory.mkdir(parents=True, exist_ok=True)
    versions = sorted(directory.glob("plan_v*.md"), key=_number)
    existing = next((path for path in versions if path.read_text(encoding="utf-8") == content), None)
    version = _number(existing) if existing else (_number(versions[-1]) + 1 if versions else 1)
    if existing is None:
        (directory / f"plan_v{version}.md").write_text(content, encoding="utf-8")
        _write_json(directory / f"plan_v{version}.json", {"version": version, "created_at": _now()})
    (directory / "current").write_text(f"v{version}\n", encoding="utf-8")
    return version


def list_plan_versions(book_dir: Path, chapter: int) -> list[dict[str, Any]]:
    directory = _plans_dir(book_dir, chapter)
    current = current_plan_version(book_dir, chapter)
    result = []
    for path in sorted(directory.glob("plan_v*.md"), key=_number, reverse=True):
        version = _number(path)
        meta = _read_json(path.with_suffix(".json"))
        result.append({
            "version": version,
            "current": version == current,
            "created_at": meta.get("created_at", ""),
            "content": path.read_text(encoding="utf-8"),
        })
    return result


def select_plan_version(book_dir: Path, chapter: int, version: int) -> str:
    directory = _plans_dir(book_dir, chapter)
    source = directory / f"plan_v{version}.md"
    if not source.exists():
        raise FileNotFoundError(f"方案 v{version} 不存在")
    content = source.read_text(encoding="utf-8")
    planning = book_dir / "logs" / f"ch{chapter}" / "planning.md"
    planning.parent.mkdir(parents=True, exist_ok=True)
    planning.write_text("status: 已批\n" + content, encoding="utf-8")
    (directory / "current").write_text(f"v{version}\n", encoding="utf-8")
    return content


def _candidates_dir(book_dir: Path, chapter: int) -> Path:
    return book_dir / "logs" / f"ch{chapter}" / "candidates"


def _candidate_paths(book_dir: Path, chapter: int, version: int) -> tuple[Path, Path]:
    directory = _candidates_dir(book_dir, chapter)
    return directory / f"candidate_v{version}.md", directory / f"candidate_v{version}.json"


def snapshot_candidate(book_dir: Path, chapter: int, *, run_id: str, action: str) -> int | None:
    pending = book_dir / "chapters" / "_pending" / f"ch{chapter}.md"
    if not pending.exists() or not pending.read_text(encoding="utf-8").strip():
        return None
    directory = _candidates_dir(book_dir, chapter)
    directory.mkdir(parents=True, exist_ok=True)
    metas = sorted(directory.glob("candidate_v*.json"), key=_number)
    version = _number(metas[-1]) + 1 if metas else 1
    for meta_path in metas:
        meta = _read_json(meta_path)
        if meta.get("state") == "current":
            meta["state"] = "archived"
            _write_json(meta_path, meta)
    content_path, meta_path = _candidate_paths(book_dir, chapter, version)
    content = pending.read_text(encoding="utf-8")
    official = book_dir / "chapters" / f"ch{chapter}.md"
    official_content = official.read_text(encoding="utf-8") if official.exists() else ""
    content_path.write_text(content, encoding="utf-8")
    _write_json(meta_path, {
        "version": version,
        "run_id": run_id,
        "action": action,
        "from_plan": current_plan_version(book_dir, chapter),
        "created_at": _now(),
        "word_count": sum(1 for char in content if "\u4e00" <= char <= "\u9fff"),
        "official_base_words": sum(1 for char in official_content if "\u4e00" <= char <= "\u9fff") if official.exists() else None,
        "state": "current",
    })
    return version


def list_candidate_versions(book_dir: Path, chapter: int) -> list[dict[str, Any]]:
    chronological: list[dict[str, Any]] = []
    for meta_path in sorted(_candidates_dir(book_dir, chapter).glob("candidate_v*.json"), key=_number):
        meta = _read_json(meta_path)
        content_path = meta_path.with_suffix(".md")
        if not content_path.exists():
            continue
        item = {**meta, "content": content_path.read_text(encoding="utf-8"), "compare": None}
        if chronological:
            base = chronological[-1]
            item["compare"] = {
                "label": f"第 {base.get('version')} 版",
                "delta": int(item.get("word_count", 0)) - int(base.get("word_count", 0)),
            }
        elif meta.get("official_base_words") is not None:
            item["compare"] = {
                "label": "正式稿",
                "delta": int(item.get("word_count", 0)) - int(meta.get("official_base_words", 0)),
            }
        chronological.append(item)
    return list(reversed(chronological))


def candidate_plan_is_stale(book_dir: Path, chapter: int) -> bool | None:
    """Compare explicit plan bindings; return None for legacy candidates without one."""
    current_plan = current_plan_version(book_dir, chapter)
    if current_plan is None:
        return None
    for meta_path in sorted(
        _candidates_dir(book_dir, chapter).glob("candidate_v*.json"),
        key=_number,
        reverse=True,
    ):
        meta = _read_json(meta_path)
        if meta.get("state") != "current":
            continue
        from_plan = meta.get("from_plan")
        if not isinstance(from_plan, int):
            return None
        return from_plan != current_plan
    return None


def mark_current_candidate_archived(book_dir: Path, chapter: int) -> None:
    for meta_path in _candidates_dir(book_dir, chapter).glob("candidate_v*.json"):
        meta = _read_json(meta_path)
        if meta.get("state") == "current":
            meta["state"] = "archived"
            _write_json(meta_path, meta)


def mark_current_candidate_adopted(book_dir: Path, chapter: int) -> None:
    for meta_path in _candidates_dir(book_dir, chapter).glob("candidate_v*.json"):
        meta = _read_json(meta_path)
        if meta.get("state") == "current":
            meta["state"] = "adopted"
            meta["adopted_at"] = _now()
            _write_json(meta_path, meta)


def select_candidate_version(book_dir: Path, chapter: int, version: int) -> None:
    content_path, selected_meta_path = _candidate_paths(book_dir, chapter, version)
    if not content_path.exists() or not selected_meta_path.exists():
        raise FileNotFoundError(f"正文第 {version} 版不存在")
    pending = book_dir / "chapters" / "_pending" / f"ch{chapter}.md"
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(content_path.read_text(encoding="utf-8"), encoding="utf-8")
    for meta_path in _candidates_dir(book_dir, chapter).glob("candidate_v*.json"):
        meta = _read_json(meta_path)
        if meta_path == selected_meta_path:
            meta["state"] = "current"
            _write_json(meta_path, meta)
        elif meta.get("state") != "trash":
            meta["state"] = "archived"
            _write_json(meta_path, meta)


def discard_current_candidate(book_dir: Path, chapter: int) -> dict[str, Any]:
    pending = book_dir / "chapters" / "_pending" / f"ch{chapter}.md"
    if not pending.exists():
        raise FileNotFoundError("当前没有候选稿")
    current = next((item for item in list_candidate_versions(book_dir, chapter) if item.get("state") == "current"), None)
    version = int(current.get("version", 0)) if current else 0
    trash = book_dir / "logs" / f"ch{chapter}" / "trash"
    trash.mkdir(parents=True, exist_ok=True)
    entry_id = f"candidate_v{version or 'legacy'}_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}"
    content_path = trash / f"{entry_id}.md"
    shutil.move(str(pending), content_path)
    entry = {"id": entry_id, "kind": "candidate", "version": version or None, "deleted_at": _now(), "content_path": content_path.name}
    _write_json(trash / f"{entry_id}.json", entry)
    if version:
        _, meta_path = _candidate_paths(book_dir, chapter, version)
        meta = _read_json(meta_path)
        meta["state"] = "trash"
        _write_json(meta_path, meta)
    return entry


def _trash_dir(book_dir: Path, chapter: int) -> Path:
    return book_dir / "logs" / f"ch{chapter}" / "trash"


def cleanup_expired_trash(book_dir: Path, chapter: int, *, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=30)
    removed = 0
    for meta_path in _trash_dir(book_dir, chapter).glob("*.json"):
        meta = _read_json(meta_path)
        try:
            deleted = datetime.fromisoformat(str(meta.get("deleted_at", "")))
        except ValueError:
            continue
        if deleted.tzinfo is None:
            deleted = deleted.replace(tzinfo=timezone.utc)
        if deleted > cutoff:
            continue
        (meta_path.parent / str(meta.get("content_path", ""))).unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        removed += 1
    return removed


def list_trash(book_dir: Path, chapter: int) -> list[dict[str, Any]]:
    cleanup_expired_trash(book_dir, chapter)
    trash = _trash_dir(book_dir, chapter)
    result = [_read_json(path) for path in trash.glob("*.json")]
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    for content in trash.glob("official_*.md"):
        if content.with_suffix(".json").exists():
            continue
        modified = datetime.fromtimestamp(content.stat().st_mtime, timezone.utc)
        if modified < cutoff:
            content.unlink(missing_ok=True)
            continue
        result.append({
            "id": content.stem,
            "kind": "official",
            "deleted_at": modified.isoformat(),
            "content_path": content.name,
        })
    return sorted(result, key=lambda item: str(item.get("deleted_at", "")), reverse=True)


def restore_trash(book_dir: Path, chapter: int, entry_id: str) -> str:
    trash = _trash_dir(book_dir, chapter)
    meta_path = trash / f"{entry_id}.json"
    meta = _read_json(meta_path)
    if not meta and (trash / f"{entry_id}.md").exists() and entry_id.startswith("official_"):
        meta = {"kind": "official", "content_path": f"{entry_id}.md"}
    source = trash / str(meta.get("content_path", ""))
    if meta.get("kind") not in {"candidate", "official"} or not source.exists():
        raise FileNotFoundError("回收站项目不存在")
    if meta.get("kind") == "official":
        official = book_dir / "chapters" / f"ch{chapter}.md"
        official.parent.mkdir(parents=True, exist_ok=True)
        if official.exists():
            replacement = trash / f"official_{datetime.now(timezone.utc):%Y%m%dT%H%M%S%f}_restore.md"
            shutil.move(str(official), replacement)
        shutil.move(str(source), official)
        meta_path.unlink(missing_ok=True)
        return "official"
    pending = book_dir / "chapters" / "_pending" / f"ch{chapter}.md"
    pending.parent.mkdir(parents=True, exist_ok=True)
    if pending.exists():
        raise FileExistsError("已有当前候选稿，请先处理后再取回")
    shutil.move(str(source), pending)
    version = meta.get("version")
    if version:
        select_candidate_version(book_dir, chapter, int(version))
    meta_path.unlink(missing_ok=True)
    return "candidate"


def purge_trash(book_dir: Path, chapter: int, entry_id: str) -> None:
    trash = _trash_dir(book_dir, chapter)
    meta_path = trash / f"{entry_id}.json"
    meta = _read_json(meta_path)
    if not meta and (trash / f"{entry_id}.md").exists() and entry_id.startswith("official_"):
        (trash / f"{entry_id}.md").unlink()
        return
    if not meta:
        raise FileNotFoundError("回收站项目不存在")
    (trash / str(meta.get("content_path", ""))).unlink(missing_ok=True)
    meta_path.unlink(missing_ok=True)
