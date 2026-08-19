"""Author-only, recoverable book and chapter deletion operations."""
from __future__ import annotations
import json, shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

@dataclass
class TrashEntry:
    trash_id: str; book_id: str; book_title: str; deleted_at: str; expires_at: str
    chapter_count: int; settings_filled_count: int; source_path: str; state: str = "trashed"

@dataclass
class ChapterResult:
    book_id: str; chapter_num: int; action: str; candidate_path: str | None; official_path: str | None
    memory_recompute: str; estimated_cost: float; actual_cost: float | None; chapter_numbers_unchanged: bool; state: str

@dataclass
class RestoreResult:
    state: str
    book_id: str
    destination: str
    copied_files: int = 0

def _author(actor: str) -> None:
    if actor != "author": raise PermissionError("只有作者可以执行此操作")

def _trash(root: Path) -> Path: return Path(root) / ".trash" / "books"

def move_book_to_trash(data_root: Path, trash_root: Path, book_id: str, *, actor: str, backup_ok: bool = False) -> TrashEntry:
    _author(actor)
    if not backup_ok: raise RuntimeError("删书前必须先完成备份")
    source = Path(data_root) / book_id
    if not source.is_dir(): raise FileNotFoundError(book_id)
    tid = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    target = _trash(trash_root) / tid
    target.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(source), str(target))
    chapters = list((target / "chapters").glob("ch*.md")) if (target / "chapters").exists() else []
    entry = TrashEntry(tid, book_id, book_id, datetime.now(timezone.utc).isoformat(), (datetime.now(timezone.utc)+timedelta(days=30)).isoformat(), len(chapters), 0, str(target))
    (target.parent / f"{tid}.json").write_text(json.dumps(asdict(entry), ensure_ascii=False), encoding="utf-8")
    return entry

def restore_book_from_trash(data_root: Path, trash_root: Path, trash_id: str, *, actor: str) -> dict:
    _author(actor); meta = _trash(trash_root) / f"{trash_id}.json"
    if not meta.exists(): raise FileNotFoundError(trash_id)
    entry = json.loads(meta.read_text(encoding="utf-8")); source = Path(entry["source_path"]); target = Path(data_root) / entry["book_id"]
    if target.exists(): raise FileExistsError(f"现役目标已存在：{target}")
    shutil.move(str(source), str(target)); meta.unlink()
    return RestoreResult("ok", entry["book_id"], str(target), sum(1 for p in target.rglob("*") if p.is_file()))

def list_book_trash(trash_root: Path) -> list[TrashEntry]:
    """Return recoverable books only; the physical tree remains hidden."""
    result: list[TrashEntry] = []
    root = _trash(trash_root)
    for meta in sorted(root.glob("*.json")) if root.exists() else []:
        try:
            result.append(TrashEntry(**json.loads(meta.read_text(encoding="utf-8"))))
        except (OSError, ValueError, TypeError):
            continue
    return result

def retract_official_chapter(data_root: Path, book_id: str, chapter_num: int, *, actor: str, estimated_cost: float = 0.0) -> ChapterResult:
    _author(actor); book=Path(data_root)/book_id; official=book/"chapters"/f"ch{chapter_num}.md"; candidate=book/"chapters"/"_pending"/f"ch{chapter_num}.md"
    if not official.exists(): raise FileNotFoundError(str(official))
    candidate.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(official), str(candidate))
    try:
        from biyu.observer import replay_persisted_projections
        replay_persisted_projections(book)
    except Exception as exc:
        shutil.move(str(candidate), str(official))
        raise RuntimeError(f"第 {chapter_num} 章已恢复正式稿，记忆重算失败：{exc}") from exc
    return ChapterResult(book_id, chapter_num, "retract-official", str(candidate), str(official), "completed", estimated_cost, 0.0, True, "ok")

def clear_chapter(data_root: Path, book_id: str, chapter_num: int, *, actor: str) -> ChapterResult:
    _author(actor); book=Path(data_root)/book_id; paths=[book/"chapters"/f"ch{chapter_num}.md",book/"chapters"/"_pending"/f"ch{chapter_num}.md",book/"outlines"/f"ch{chapter_num}.md",book/"logs"/f"ch{chapter_num}"/"planning.md"]
    if not any(p.exists() for p in paths): raise FileNotFoundError(f"第 {chapter_num} 章不存在")
    for p in paths:
        if p.is_dir(): shutil.rmtree(p)
        elif p.exists(): p.unlink()
    return ChapterResult(book_id, chapter_num, "clear", str(paths[1]), str(paths[0]), "not_required", 0.0, 0.0, True, "ok")

def confirmation_copy(kind: str, **kwargs) -> str:
    if kind == "delete_book": return f"整本书会移到回收站，保留 30 天。里面有 {kwargs['chapter_count']} 章正式稿、{kwargs['settings_count']} 格设定。"
    if kind == "retract": return f"第 {kwargs['chapter']} 章会退回候选稿。这一章发生的事已进记忆，需要重算，约 ¥{kwargs['estimated_cost']:.2f}。"
    if kind == "clear": return f"第 {kwargs['chapter']} 章会变成空位，第 {kwargs['chapter']+1} 章还是第 {kwargs['chapter']+1} 章。细纲、方案、正文都会清掉。"
    raise ValueError(kind)
