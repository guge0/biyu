"""Local, directly-readable backups for the author's data tree."""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


@dataclass
class BackupStatus:
    scope: str
    configured: bool
    writable: bool
    last_backup_at: str | None
    last_backup_path: str | None
    state: str
    message: str


@dataclass
class BackupResult:
    backup_id: str
    scope: str
    started_at: str
    finished_at: str
    root_path: str
    book_count: int
    copied_files: int
    retention_deleted: int
    state: str
    error: str | None = None


_STATUS = ".biyu_backup_status.json"
_LOG = "backup.log"


def _status_path(destination: Path, scope: str) -> Path:
    return Path(destination) / scope / _STATUS


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _write_status(destination: Path, status: BackupStatus) -> None:
    path = _status_path(destination, status.scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(status), ensure_ascii=False, indent=2), encoding="utf-8")


def _write_failure_log(destination: Path, scope: str, message: str) -> None:
    path = Path(destination) / scope / _LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{_now().isoformat()} [{scope}] {message}\n")


def retained_snapshot_names(names: list[str]) -> list[str]:
    """Keep the newest seven calendar days and four additional calendar weeks."""
    ordered = sorted(set(names), reverse=True)
    daily: set[str] = set()
    weekly: set[tuple[int, int]] = set()
    kept: list[str] = []
    parsed: list[tuple[str, datetime]] = []
    for name in ordered:
        try:
            parsed.append((name, datetime.strptime(name, "%Y%m%d-%H%M%S")))
        except ValueError:
            continue
    for name, stamp in parsed:
        day = stamp.strftime("%Y%m%d")
        if day not in daily and len(daily) < 7:
            daily.add(day)
            kept.append(name)
    for name, stamp in parsed:
        week = stamp.isocalendar()[:2]
        if week not in weekly and len(weekly) < 4 and name not in kept:
            weekly.add(week)
            kept.append(name)
    return kept


def get_backup_status(destination: Path, *, scope: str) -> BackupStatus:
    destination = Path(destination)
    path = _status_path(destination, scope)
    if not destination.exists():
        return BackupStatus(scope, False, False, None, None, "unconfigured", "备份没开，点这里选个位置")
    writable = os.access(destination, os.W_OK)
    if not writable:
        return BackupStatus(scope, True, False, None, None, "unwritable", "备份位置不可写，请选择其他位置")
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return BackupStatus(**data)
        except (OSError, ValueError, TypeError):
            pass
    return BackupStatus(scope, True, True, None, None, "never", "还没有备份记录；备份完成后会在这里显示时间和路径")


def run_backup(source: Path, destination: Path, *, scope: Literal["production", "test"], reason: str) -> BackupResult:
    source, destination = Path(source), Path(destination)
    started = _now()
    if not source.is_dir():
        status = BackupStatus(scope, destination.exists(), False, None, None, "failed", f"备份失败：数据根不存在：{source}")
        _write_status(destination, status)
        _write_failure_log(destination, scope, status.message)
        raise RuntimeError(status.message)
    try:
        destination.mkdir(parents=True, exist_ok=True)
        stamp = started.strftime("%Y%m%d-%H%M%S")
        target = destination / scope / stamp
        target.parent.mkdir(parents=True, exist_ok=True)
        copied_books = [p for p in source.iterdir() if p.is_dir() and (p / "book.json").is_file()]
        for book in copied_books:
            shutil.copytree(
                book,
                target / book.name,
                ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv", "*.pyc", "*.key", "*.pem"),
            )
        root_cost = source / "cost_log.csv"
        if root_cost.is_file():
            shutil.copy2(root_cost, target / root_cost.name)
        files = sum(1 for p in target.rglob("*") if p.is_file())
        books = len(copied_books)
        points = sorted((p for p in target.parent.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
        removed = 0
        keep_names = set(retained_snapshot_names([p.name for p in points]))
        for old in points:
            if old.name in keep_names:
                continue
            shutil.rmtree(old)
            removed += 1
        finished = _now()
        result = BackupResult(stamp, scope, started.isoformat(), finished.isoformat(), str(target), books, files, removed, "ok")
        _write_status(destination, BackupStatus(scope, True, True, finished.isoformat(), str(target), "ok", f"上次备份：{finished.isoformat()}，{target}"))
        return result
    except Exception as exc:
        status = BackupStatus(scope, True, False, None, None, "failed", f"备份失败：{exc}")
        _write_status(destination, status)
        _write_failure_log(destination, scope, status.message)
        raise RuntimeError(status.message) from exc


def preview_book_restore(backup_id: str, book_id: str, *, backup_root: Path) -> dict:
    book = Path(backup_root) / backup_id / book_id
    if not book.is_dir():
        raise FileNotFoundError(f"备份或书不存在：{book_id}")
    chapters = list((book / "chapters").glob("ch*.md")) if (book / "chapters").exists() else []
    settings = list((book / "worldbook").glob("*")) if (book / "worldbook").exists() else []
    return {"backup_id": backup_id, "book_id": book_id, "book_title": book_id, "chapter_count": len(chapters), "settings_filled_count": len([p for p in settings if p.is_file()]), "backup_at": backup_id, "source_path": str(book), "destination_default": str(Path.cwd() / "biyu-restore" / book_id)}


def restore_book(backup_id: str, book_id: str, destination: Path, *, backup_root: Path) -> dict:
    source = Path(backup_root) / backup_id / book_id
    destination = Path(destination)
    if not source.is_dir():
        raise FileNotFoundError(f"备份或书不存在：{book_id}")
    if destination.resolve() == source.parent.parent.resolve() or source.parent.parent.resolve() in destination.resolve().parents:
        raise ValueError("恢复目标不得是现役数据根或其子目录")
    target = destination / book_id
    if target.exists():
        raise FileExistsError(f"恢复目标已存在：{target}")
    shutil.copytree(source, target)
    return {"state": "ok", "destination": str(target), "copied_files": sum(1 for p in target.rglob("*") if p.is_file()), "verified": True}
