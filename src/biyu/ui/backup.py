"""Author-visible backup and recoverable deletion endpoints."""
from __future__ import annotations
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from biyu.config import get_data_root
from biyu.backup_service import get_backup_status, run_backup, preview_book_restore, restore_book
from biyu.deletion_service import (list_book_trash, move_book_to_trash, restore_book_from_trash,
                                   retract_official_chapter, clear_chapter)

router = APIRouter()

class BackupRun(BaseModel):
    scope: str = "production"
    reason: str = "manual"

class RestoreBody(BaseModel):
    destination: str | None = None
    actor: str = "author"

def _backup_root() -> Path:
    return Path(os.environ.get("BIYU_BACKUP_ROOT", r"D:\BiyuBackup"))

def _actor(actor: str) -> None:
    if actor != "author": raise HTTPException(403, "只有作者可以执行此操作")

@router.get("/api/backup/status")
def backup_status(scope: str = Query("production")):
    status = get_backup_status(_backup_root(), scope=scope)
    if os.environ.get("BIYU_AUTO_BACKUP") != "1":
        status.state = "disabled"
        status.message = "备份没有开。等你开始写真书的时候再打开它。"
    return status

@router.post("/api/backup/run")
def backup_run(payload: BackupRun):
    scope = payload.scope if payload.scope in ("production", "test") else "production"
    source = get_data_root()
    try: return run_backup(source, _backup_root(), scope=scope, reason=payload.reason)
    except RuntimeError as exc: raise HTTPException(503, str(exc)) from exc

@router.get("/api/backup/{backup_id}/books/{book_id}/preview")
def backup_preview(backup_id: str, book_id: str, scope: str = Query("production")):
    try: return preview_book_restore(backup_id, book_id, backup_root=_backup_root() / scope)
    except FileNotFoundError as exc: raise HTTPException(404, str(exc)) from exc

@router.post("/api/backup/{backup_id}/books/{book_id}/restore")
def backup_restore(backup_id: str, book_id: str, body: RestoreBody, scope: str = Query("production")):
    _actor(body.actor)
    destination = Path(body.destination) if body.destination else Path.cwd() / "biyu-restore"
    try: return restore_book(backup_id, book_id, destination, backup_root=_backup_root() / scope)
    except FileNotFoundError as exc: raise HTTPException(404, str(exc)) from exc
    except (ValueError, FileExistsError) as exc: raise HTTPException(409, str(exc)) from exc

@router.get("/api/trash/books")
def trash_books(): return list_book_trash(_backup_root())

@router.post("/api/trash/books/{trash_id}/restore")
def trash_restore(trash_id: str, body: RestoreBody):
    _actor(body.actor)
    try: return restore_book_from_trash(get_data_root(), _backup_root(), trash_id, actor=body.actor)
    except FileNotFoundError as exc: raise HTTPException(404, str(exc)) from exc
    except FileExistsError as exc: raise HTTPException(409, str(exc)) from exc

@router.post("/api/books/{book_id}/trash")
def book_trash(book_id: str, body: RestoreBody):
    _actor(body.actor)
    try:
        # The backup must have completed before this endpoint is called.
        status = get_backup_status(_backup_root(), scope="production")
        return move_book_to_trash(get_data_root(), _backup_root(), book_id, actor=body.actor, backup_ok=status.state == "ok")
    except FileNotFoundError as exc: raise HTTPException(404, str(exc)) from exc
    except (RuntimeError, PermissionError) as exc: raise HTTPException(409, str(exc)) from exc

@router.post("/api/books/{book_id}/chapters/{chapter_num}/retract-official")
def chapter_retract(book_id: str, chapter_num: int, body: RestoreBody):
    _actor(body.actor)
    try: return retract_official_chapter(get_data_root(), book_id, chapter_num, actor=body.actor, estimated_cost=0.10)
    except FileNotFoundError as exc: raise HTTPException(404, str(exc)) from exc

@router.post("/api/books/{book_id}/chapters/{chapter_num}/clear")
def chapter_clear(book_id: str, chapter_num: int, body: RestoreBody):
    _actor(body.actor)
    try: return clear_chapter(get_data_root(), book_id, chapter_num, actor=body.actor)
    except FileNotFoundError as exc: raise HTTPException(404, str(exc)) from exc
