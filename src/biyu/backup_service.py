"""Directly-readable author backups with persistent settings and status."""
from __future__ import annotations

import json
import errno
import os
import re
import shutil
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from biyu.secure_config import user_config_dir


@dataclass
class BackupSettings:
    enabled: bool = False
    destination: str = r"D:\BiyuBackup"
    source_path: str = ""
    schedule_state: str = "disabled"
    schedule_error: str | None = None


@dataclass
class BackupStatus:
    scope: str
    configured: bool = True
    writable: bool = True
    last_backup_at: str | None = None
    last_backup_path: str | None = None
    state: str = "never"
    message: str = "还没备过"
    book_count: int = 0
    copied_files: int = 0
    duration_seconds: float | None = None
    last_attempt_at: str | None = None
    last_error: str | None = None
    running_started_at: str | None = None


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
    duration_seconds: float
    error: str | None = None


class BackupBusyError(RuntimeError):
    """Raised when another process already owns the backup lock."""


_STATUS = ".biyu_backup_status.json"
_MANIFEST = "_manifest.json"
_SNAPSHOT_RE = re.compile(r"^\d{8}-\d{6}-\d{6}$")
_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _settings_path() -> Path:
    return user_config_dir() / "backup.json"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_backup_settings() -> BackupSettings:
    try:
        raw = json.loads(_settings_path().read_text(encoding="utf-8"))
        known = {field.name for field in fields(BackupSettings)}
        return BackupSettings(**{key: value for key, value in raw.items() if key in known})
    except (OSError, ValueError, TypeError):
        return BackupSettings(
            enabled=os.environ.get("BIYU_AUTO_BACKUP") == "1",
            destination=os.environ.get("BIYU_BACKUP_ROOT", r"D:\BiyuBackup"),
            source_path=os.environ.get("BIYU_DATA_ROOT", ""),
        )


def save_backup_settings(settings: BackupSettings) -> None:
    _atomic_json(_settings_path(), {"schema_version": 1, **asdict(settings)})


def validate_backup_destination(destination: Path) -> Path:
    """Require an existing writable directory before changing saved settings."""
    path = Path(destination).expanduser()
    if not path.exists():
        raise RuntimeError(f"备份目录不存在：{path}")
    if not path.is_dir():
        raise RuntimeError(f"备份位置不是文件夹：{path}")
    probe = path / f".biyu-write-test-{os.getpid()}-{threading.get_ident()}.tmp"
    try:
        with probe.open("xb") as handle:
            handle.write(b"biyu")
            handle.flush()
            os.fsync(handle.fileno())
    except PermissionError as exc:
        raise RuntimeError(f"备份目录不可写：{path}（{exc}）") from exc
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise RuntimeError(f"备份磁盘空间不足：{path}") from exc
        raise RuntimeError(f"备份目录不可写：{path}（{exc}）") from exc
    finally:
        try:
            probe.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
    return path.resolve()


def next_backup_at(*, now: datetime | None = None) -> str:
    local_now = now or datetime.now().astimezone()
    candidate = local_now.replace(hour=3, minute=15, second=0, microsecond=0)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate.isoformat()


def _status_path(destination: Path, scope: str, status_dir: Path | None = None) -> Path:
    if status_dir is not None:
        return Path(status_dir) / f"backup-status-{scope}.json"
    return Path(destination) / scope / _STATUS


def _status_from_dict(scope: str, raw: dict[str, Any]) -> BackupStatus:
    known = {field.name for field in fields(BackupStatus)}
    values = {key: value for key, value in raw.items() if key in known}
    values["scope"] = scope
    return BackupStatus(**values)


def _write_status(destination: Path, status: BackupStatus, *, status_dir: Path | None = None) -> None:
    _atomic_json(_status_path(destination, status.scope, status_dir), asdict(status))


def _write_failure_log(status_dir: Path, scope: str, message: str, *, legacy: bool = False) -> None:
    path = Path(status_dir) / ("backup.log" if legacy else f"backup-{scope}.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{_now().isoformat()} [{scope}] {message}\n")


def get_backup_status(destination: Path, *, scope: str, status_dir: Path | None = None) -> BackupStatus:
    destination = Path(destination)
    candidates = [_status_path(destination, scope, status_dir)]
    if status_dir is not None:
        candidates.append(_status_path(destination, scope))
    for path in candidates:
        try:
            return _status_from_dict(scope, json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            continue
    return BackupStatus(scope=scope, configured=bool(str(destination)), writable=True)


def reset_backup_status(destination: Path, *, scope: str, status_dir: Path | None = None) -> BackupStatus:
    status = BackupStatus(scope=scope, configured=True, writable=True)
    _write_status(Path(destination), status, status_dir=status_dir)
    return status


def retained_snapshot_names(names: list[str]) -> list[str]:
    """Keep one snapshot for seven recent backup days, then four older weeks."""
    parsed: list[tuple[str, datetime]] = []
    for name in sorted(set(names), reverse=True):
        for fmt in ("%Y%m%d-%H%M%S-%f", "%Y%m%d-%H%M%S"):
            try:
                parsed.append((name, datetime.strptime(name, fmt)))
                break
            except ValueError:
                continue
    kept: list[str] = []
    daily: set[str] = set()
    for name, stamp in parsed:
        day = stamp.strftime("%Y%m%d")
        if day not in daily and len(daily) < 7:
            daily.add(day)
            kept.append(name)
    weekly: set[tuple[int, int]] = set()
    for name, stamp in parsed:
        if stamp.strftime("%Y%m%d") in daily:
            continue
        week = stamp.isocalendar()[:2]
        if week not in weekly and len(weekly) < 4:
            weekly.add(week)
            kept.append(name)
    return kept


def _thread_lock(key: str) -> threading.Lock:
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.Lock())


@contextmanager
def _backup_lock(lock_root: Path, scope: str) -> Iterator[None]:
    lock_root.mkdir(parents=True, exist_ok=True)
    key = str((lock_root / f"backup-{scope}.lock").resolve())
    local = _thread_lock(key)
    if not local.acquire(blocking=False):
        raise BackupBusyError("另一份备份正在进行")
    handle = None
    try:
        handle = Path(key).open("a+b")
        handle.seek(0)
        if handle.read(1) == b"":
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BackupBusyError("另一份备份正在进行") from exc
        yield
    finally:
        if handle is not None:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            handle.close()
        local.release()


def _validate_roots(source: Path, destination: Path) -> None:
    source_resolved = source.resolve()
    destination_resolved = destination.resolve()
    if destination_resolved == source_resolved or source_resolved in destination_resolved.parents:
        raise RuntimeError("备份位置不能放在书稿目录里面")


def run_backup(
    source: Path,
    destination: Path,
    *,
    scope: Literal["production", "test"],
    reason: str,
    status_dir: Path | None = None,
) -> BackupResult:
    source, destination = Path(source), Path(destination)
    durable_status_dir = Path(status_dir) if status_dir else destination
    partial: Path | None = None
    with _backup_lock(durable_status_dir, scope):
        previous = get_backup_status(destination, scope=scope, status_dir=status_dir)
        started_precise = datetime.now(timezone.utc)
        started = started_precise.replace(microsecond=0)
        running = BackupStatus(
            scope=scope,
            last_backup_at=previous.last_backup_at,
            last_backup_path=previous.last_backup_path,
            state="running",
            message="正在备份…",
            book_count=previous.book_count,
            copied_files=previous.copied_files,
            duration_seconds=previous.duration_seconds,
            last_attempt_at=started.isoformat(),
            running_started_at=started.isoformat(),
        )
        _write_status(destination, running, status_dir=status_dir)
        try:
            if not source.is_dir():
                raise RuntimeError(f"数据根不存在：{source}")
            _validate_roots(source, destination)
            destination.mkdir(parents=True, exist_ok=True)
            scope_root = destination / scope
            scope_root.mkdir(parents=True, exist_ok=True)
            backup_id = started_precise.strftime("%Y%m%d-%H%M%S-%f")
            target = scope_root / backup_id
            partial = scope_root / f".partial-{backup_id}"
            partial.mkdir()
            books = [path for path in source.iterdir() if path.is_dir() and (path / "book.json").is_file()]
            for book in books:
                shutil.copytree(
                    book,
                    partial / book.name,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv", "*.pyc", "*.key", "*.pem"),
                )
            root_cost = source / "cost_log.csv"
            if root_cost.is_file():
                shutil.copy2(root_cost, partial / root_cost.name)
            verified_books = [path for path in partial.iterdir() if path.is_dir() and (path / "book.json").is_file()]
            finished_precise = datetime.now(timezone.utc)
            duration = max(0.0, (finished_precise - started_precise).total_seconds())
            _atomic_json(partial / _MANIFEST, {
                "schema_version": 1,
                "backup_id": backup_id,
                "scope": scope,
                "reason": reason,
                "source_path": str(source.resolve()),
                "started_at": started.isoformat(),
                "finished_at": finished_precise.replace(microsecond=0).isoformat(),
                "book_count": len(verified_books),
                "books": [path.name for path in verified_books],
            })
            os.replace(partial, target)
            partial = None
            files = sum(1 for path in target.rglob("*") if path.is_file())
            completed = [
                path for path in scope_root.iterdir()
                if path.is_dir() and _SNAPSHOT_RE.fullmatch(path.name) and (path / _MANIFEST).is_file()
            ]
            keep_names = set(retained_snapshot_names([path.name for path in completed]))
            removed = 0
            for old in completed:
                if old.name not in keep_names:
                    shutil.rmtree(old)
                    removed += 1
            finished = finished_precise.replace(microsecond=0)
            state = "ok" if verified_books else "needs_attention"
            result = BackupResult(
                backup_id, scope, started.isoformat(), finished.isoformat(), str(target),
                len(verified_books), files, removed, state, duration,
            )
            if verified_books:
                status = BackupStatus(
                    scope=scope,
                    last_backup_at=finished.isoformat(),
                    last_backup_path=str(target),
                    state="ok",
                    message=f"备份完成：{result.book_count} 本 · {target} · 用时 {duration:.3f} 秒",
                    book_count=result.book_count,
                    copied_files=result.copied_files,
                    duration_seconds=result.duration_seconds,
                    last_attempt_at=finished.isoformat(),
                )
            else:
                status = BackupStatus(
                    scope=scope,
                    last_backup_at=previous.last_backup_at,
                    last_backup_path=previous.last_backup_path,
                    state="needs_attention",
                    message="这次备份没有备到任何书，请检查数据位置。",
                    book_count=previous.book_count,
                    copied_files=previous.copied_files,
                    duration_seconds=previous.duration_seconds,
                    last_attempt_at=finished.isoformat(),
                )
            _write_status(destination, status, status_dir=status_dir)
            return result
        except Exception as exc:
            if partial is not None and partial.exists():
                shutil.rmtree(partial, ignore_errors=True)
            failed_at = _now().isoformat()
            message = f"备份失败：{exc}"
            _write_status(destination, BackupStatus(
                scope=scope,
                writable=False,
                last_backup_at=previous.last_backup_at,
                last_backup_path=previous.last_backup_path,
                state="failed",
                message=message,
                book_count=previous.book_count,
                copied_files=previous.copied_files,
                duration_seconds=previous.duration_seconds,
                last_attempt_at=failed_at,
                last_error=str(exc),
            ), status_dir=status_dir)
            _write_failure_log(destination / scope if status_dir is None else durable_status_dir, scope, message, legacy=status_dir is None)
            raise RuntimeError(message) from exc


def preview_book_restore(backup_id: str, book_id: str, *, backup_root: Path) -> dict[str, Any]:
    book = Path(backup_root) / backup_id / book_id
    if not book.is_dir():
        raise FileNotFoundError(f"备份或书不存在：{book_id}")
    chapters = list((book / "chapters").glob("ch*.md")) if (book / "chapters").exists() else []
    settings = list((book / "worldbook").glob("*")) if (book / "worldbook").exists() else []
    return {
        "backup_id": backup_id,
        "book_id": book_id,
        "book_title": book_id,
        "chapter_count": len(chapters),
        "settings_filled_count": len([path for path in settings if path.is_file()]),
        "backup_at": backup_id,
        "source_path": str(book),
        "destination_default": str(Path.cwd() / "biyu-restore" / book_id),
    }


def restore_book(backup_id: str, book_id: str, destination: Path, *, backup_root: Path) -> dict[str, Any]:
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
    return {
        "state": "ok",
        "destination": str(target),
        "copied_files": sum(1 for path in target.rglob("*") if path.is_file()),
        "verified": True,
    }
