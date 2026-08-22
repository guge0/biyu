"""Author-visible backup settings, status, and recoverable deletion endpoints."""
from __future__ import annotations

import asyncio
import locale
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from biyu.backup_service import (
    BackupBusyError,
    BackupSettings,
    get_backup_status,
    load_backup_settings,
    next_backup_at,
    preview_book_restore,
    reset_backup_status,
    restore_book,
    run_backup,
    save_backup_settings,
    validate_backup_destination,
)
from biyu.config import get_data_root
from biyu.deletion_service import (
    clear_chapter,
    list_book_trash,
    move_book_to_trash,
    restore_book_from_trash,
    retract_official_chapter,
)
from biyu.secure_config import user_config_dir

router = APIRouter()
_manual_task: asyncio.Task[None] | None = None


class BackupSettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    destination: str


class RestoreBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination: str | None = None
    actor: str = "author"


def _scope() -> str:
    return "test" if os.environ.get("BIYU_RUNTIME_ROLE") in {"test", "development"} else "production"


def _backup_root() -> Path:
    return Path(load_backup_settings().destination)


def _trash_root() -> Path:
    # Recycle-bin data must not disappear when the snapshot destination changes.
    return Path(os.environ.get("BIYU_TRASH_ROOT", r"D:\BiyuBackup"))


def _actor(actor: str) -> None:
    if actor != "author":
        raise HTTPException(403, "只有作者可以执行此操作")


def _running() -> bool:
    return _manual_task is not None and not _manual_task.done()


def _project_root() -> Path:
    configured = os.environ.get("BIYU_PROJECT_ROOT")
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parents[3]


def _process_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    for encoding in ("utf-8", locale.getpreferredencoding(False), "mbcs"):
        try:
            return value.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return value.decode("utf-8", errors="replace")


def _status_payload() -> dict[str, object]:
    settings = load_backup_settings()
    status = get_backup_status(Path(settings.destination), scope=_scope(), status_dir=user_config_dir())
    payload = asdict(status)
    payload.update({
        "enabled": settings.enabled,
        "destination": settings.destination,
        "schedule_state": settings.schedule_state,
        "schedule_error": settings.schedule_error,
        "next_backup_at": next_backup_at() if settings.enabled else None,
        "retention": {"daily": 7, "weekly": 4},
    })
    if _running():
        payload["state"] = "running"
        payload["message"] = "正在备份…"
    elif not settings.enabled and status.state != "failed":
        payload["state"] = "disabled"
        payload["message"] = "备份没有开"
    return payload


def _sync_daily_schedule(enabled: bool) -> tuple[str, str | None]:
    if _scope() == "test":
        return ("test", None)
    project_root = _project_root()
    script = project_root / "scripts" / "install_biyu_backup_task.ps1"
    if not script.is_file():
        return ("failed", "找不到自动备份安装脚本，请重新安装笔驭")
    command = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
        "-PythonPath", sys.executable, "-ProjectRoot", str(project_root),
    ]
    if not enabled:
        command.append("-Disable")
    completed = subprocess.run(command, capture_output=True)
    if completed.returncode != 0:
        detail = (_process_text(completed.stderr) or _process_text(completed.stdout)).strip()
        if detail:
            return ("failed", f"Windows 计划任务没有更新成功：{detail}")
        return ("failed", "Windows 计划任务没有更新成功")
    return ("enabled" if enabled else "disabled", None)


def _run_configured_backup(reason: str) -> None:
    settings = load_backup_settings()
    source = get_data_root()
    run_backup(
        source,
        Path(settings.destination),
        scope=_scope(),
        reason=reason,
        status_dir=user_config_dir(),
    )


@router.get("/api/backup/status")
def backup_status() -> dict[str, object]:
    return _status_payload()


@router.put("/api/backup/settings")
def backup_settings(payload: BackupSettingsBody) -> dict[str, object]:
    if _running():
        raise HTTPException(409, "正在备份，完成后再改设置")
    destination = Path(payload.destination.strip()).expanduser()
    if not payload.destination.strip() or not destination.is_absolute():
        raise HTTPException(400, "请选择完整的备份路径")
    source = get_data_root().resolve()
    resolved = destination.resolve()
    if resolved == source or source in resolved.parents:
        raise HTTPException(400, "备份位置不能放在书稿目录里面")
    try:
        validate_backup_destination(destination)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    previous = load_backup_settings()
    pending = BackupSettings(
        enabled=payload.enabled,
        destination=str(destination),
        source_path=str(source),
        schedule_state="updating",
    )
    save_backup_settings(pending)
    state, error = _sync_daily_schedule(payload.enabled)
    if error:
        save_backup_settings(previous)
        raise HTTPException(503, f"自动备份没有设置成功：{error}")
    pending.schedule_state = state
    pending.schedule_error = None
    save_backup_settings(pending)
    if Path(previous.destination).resolve() != destination.resolve():
        reset_backup_status(destination, scope=_scope(), status_dir=user_config_dir())
    return _status_payload()


@router.post("/api/backup/choose-directory")
def backup_choose_directory() -> dict[str, str | None]:
    if os.name != "nt":
        raise HTTPException(501, "当前系统不能打开 Windows 文件夹选择器")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$d=New-Object System.Windows.Forms.FolderBrowserDialog;"
        "$d.Description='选择笔驭备份位置';$d.ShowNewFolderButton=$true;"
        "if($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){$d.SelectedPath}"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-STA", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if completed.returncode != 0:
        raise HTTPException(503, "文件夹选择器没有打开成功")
    selected = completed.stdout.strip()
    return {"destination": selected or None}


@router.post("/api/backup/run", status_code=202)
async def backup_run() -> dict[str, object]:
    global _manual_task
    if _running():
        raise HTTPException(409, "正在备份")

    async def execute() -> None:
        try:
            await asyncio.to_thread(_run_configured_backup, "manual")
        except (RuntimeError, BackupBusyError):
            return

    _manual_task = asyncio.create_task(execute())
    payload = _status_payload()
    payload["state"] = "running"
    payload["message"] = "正在备份…"
    return payload


@router.get("/api/backup/{backup_id}/books/{book_id}/preview")
def backup_preview(backup_id: str, book_id: str):
    try:
        return preview_book_restore(backup_id, book_id, backup_root=_backup_root() / _scope())
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/api/backup/{backup_id}/books/{book_id}/restore")
def backup_restore(backup_id: str, book_id: str, body: RestoreBody):
    _actor(body.actor)
    destination = Path(body.destination) if body.destination else Path.cwd() / "biyu-restore"
    try:
        return restore_book(backup_id, book_id, destination, backup_root=_backup_root() / _scope())
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, FileExistsError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/api/trash/books")
def trash_books() -> list[dict[str, object]]:
    return [_trash_payload(entry) for entry in list_book_trash(_trash_root())]


def _trash_payload(entry) -> dict[str, object]:
    return {
        "trash_id": entry.trash_id,
        "book_id": entry.book_id,
        "book_title": entry.book_title,
        "deleted_at": entry.deleted_at,
        "chapter_count": entry.chapter_count,
        "settings_filled_count": entry.settings_filled_count,
        "state": entry.state,
    }


@router.post("/api/trash/books/{trash_id}/restore")
def trash_restore(trash_id: str, body: RestoreBody):
    _actor(body.actor)
    try:
        return restore_book_from_trash(get_data_root(), _trash_root(), trash_id, actor=body.actor)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/api/books/{book_id}/trash")
def book_trash(book_id: str, body: RestoreBody):
    _actor(body.actor)
    try:
        return _trash_payload(move_book_to_trash(get_data_root(), _trash_root(), book_id, actor=body.actor))
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/api/books/{book_id}/chapters/{chapter_num}/retract-official")
def chapter_retract(book_id: str, chapter_num: int, body: RestoreBody):
    _actor(body.actor)
    try:
        return retract_official_chapter(get_data_root(), book_id, chapter_num, actor=body.actor, estimated_cost=0.10)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/api/books/{book_id}/chapters/{chapter_num}/clear")
def chapter_clear(book_id: str, chapter_num: int, body: RestoreBody):
    _actor(body.actor)
    try:
        return clear_chapter(get_data_root(), book_id, chapter_num, actor=body.actor)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
