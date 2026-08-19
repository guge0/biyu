"""R3-1 talk — 以参数化 launcher 打开持久创作轨对话。"""
from __future__ import annotations

import os
import json
from pathlib import Path
import subprocess
from typing import Optional
from uuid import uuid4

import typer
from rich.console import Console

from biyu.config import get_project_root
from biyu.config import resolve_book_dir

console = Console()


def _bookroom_bat() -> Path:
    """Locate the checkout launcher independently of the installed package path."""
    configured_root = os.environ.get("BIYU_PROJECT_ROOT", "").strip()
    candidates = []
    if configured_root:
        candidates.append(Path(configured_root).expanduser())
    candidates.append(Path.cwd())
    candidates.append(get_project_root())
    for root in candidates:
        launcher = root / "书房.bat"
        if launcher.is_file():
            return launcher
    return candidates[0] / "书房.bat"


def _registry_path(book: str, role: str = "章节导演") -> Path:
    filename = "total_director_sessions.json" if role == "总导演" else "chapter_director_sessions.json"
    return resolve_book_dir(book) / "consults" / filename


def _session_id(book: str, chapter: int | None, *, role: str, new: bool) -> tuple[str, bool]:
    path = _registry_path(book) if role == "章节导演" else _registry_path(book, role)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        registry = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        registry = {}
    key = "book" if role == "总导演" else str(chapter)
    existed = bool(registry.get(key)) and not new
    sid = str(registry[key]) if existed else str(uuid4())
    if not existed:
        registry[key] = sid
        path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    return sid, existed


def _forget_new_session(book: str, chapter: int | None, role: str, session_id: str) -> None:
    path = _registry_path(book) if role == "章节导演" else _registry_path(book, role)
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    key = "book" if role == "总导演" else str(chapter)
    if registry.get(key) != session_id:
        return
    del registry[key]
    if registry:
        path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path.unlink(missing_ok=True)


def open_talk(*, role: str, book: Optional[str], chapter: Optional[int], new: bool = False) -> None:
    if role not in {"章节导演", "总导演"}:
        raise typer.BadParameter(f"未注册角色: {role}")
    if role == "章节导演" and chapter is None:
        raise typer.BadParameter("章节导演需要 --chapter/-c")
    if not book:
        raise typer.BadParameter(f"{role}需要 --book/-b")
    book_dir = resolve_book_dir(book)
    launcher = _bookroom_bat()
    if not launcher.exists():
        raise typer.BadParameter(f"未找到 launcher: {launcher}")
    if role == "总导演":
        greeting = (
            f"为《{book}》担任总导演。本书唯一目录是 {book_dir}。先从该目录读北极星、人物设定、世界观、大纲和已有章节状态，"
            "再和作者讨论全书方向、人物弧线与长线安排。任何方案先给作者确认；除非作者明确要求，"
            "不直接写章节正文，不擅自改书内文件。讨论节奏、爽点、开篇或卖点时，按问题选读 "
            "prompts/assets/网文Craft蒸馏_v0.md 的相关章节；它只作参考，不覆盖本书事实和作者拍板。"
        )
    else:
        greeting = (
            f"为《{book}》处理第{chapter}章。本书唯一目录是 {book_dir}；"
            f"只从该目录读取 outlines/ch{chapter}.md，并把方案写到 logs/ch{chapter}/planning.md。"
        )
    session_id, existed = _session_id(book, chapter, role=role, new=new)
    session_args = ["--resume", session_id] if existed else ["--session-id", session_id]
    env = os.environ.copy()
    env["BIYU_TRACK"] = "creative"
    try:
        subprocess.Popen(
            ["cmd.exe", "/d", "/c", str(launcher), *session_args, greeting],
            cwd=str(get_project_root()),
            env=env,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
    except Exception:
        if not existed:
            _forget_new_session(book, chapter, role, session_id)
        raise
    target = f"{book} 第{chapter}章" if role == "章节导演" else book
    console.print(f"已{'续接' if existed else '打开'}{role}对话: {target}")
    console.print("费用口径: 账B（订阅）")


def talk(
    role: str = typer.Argument(...),
    book: Optional[str] = typer.Option(None, "--book", "-b"),
    chapter: Optional[int] = typer.Option(None, "--chapter", "-c"),
    new: bool = typer.Option(False, "--new", help="显式新开一段对话"),
) -> None:
    """打开持久创作轨对话；不使用 -p/--print。"""
    open_talk(role=role, book=book, chapter=chapter, new=new)
