"""R3-2 workbench-only file actions; UI remains a thin CLI adapter."""
from __future__ import annotations

import json
import asyncio
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from uuid import uuid4

import typer
from rich.console import Console

from biyu.config import resolve_book_dir


console = Console()
workbench_app = typer.Typer(help="工作台内部动作。")


def _append(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


@dataclass(frozen=True)
class AdoptionResult:
    commit_hash: str
    memory_updated: bool


def _memory_state_path(book_dir: Path, chapter: int) -> Path:
    return book_dir / "logs" / f"ch{chapter}" / "memory_state.json"


def _set_memory_dirty(book_dir: Path, chapter: int, dirty: bool, error: str = "") -> None:
    path = _memory_state_path(book_dir, chapter)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "memory_dirty": dirty,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if error:
        payload["error"] = error
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_memory_dirty(book_dir: Path, chapter: int) -> bool:
    path = _memory_state_path(book_dir, chapter)
    if not path.exists():
        return False
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("memory_dirty"))
    except (json.JSONDecodeError, OSError):
        return True


def _recycle_official(book_dir: Path, chapter: int, official: Path) -> Path | None:
    if not official.exists():
        return None
    trash = book_dir / "logs" / f"ch{chapter}" / "trash"
    trash.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    target = trash / f"official_{stamp}_{uuid4().hex[:8]}.md"
    official.replace(target)
    return target


def _run_official_observer(book_dir: Path, chapter: int, official_path: Path) -> bool:
    from biyu.config import BookConfig, get_registry
    from biyu.observer import update_official_chapter_projection
    from biyu.pipeline import _log_cost

    registry = get_registry()
    observer_alias = registry.get_pipeline_config().get("writer", "v3")
    adapter = registry.get_adapter_for_stage("writer", override=observer_alias)
    book = BookConfig(book_dir)

    def log_cost(cost: float, latency: float) -> None:
        _log_cost(book, chapter, "observer", cost, latency)

    return asyncio.run(
        update_official_chapter_projection(
            book_dir,
            chapter,
            official_path,
            adapter,
            _log_cost_fn=log_cost,
        )
    )


def _adopt_pending(
    book_dir: Path,
    chapter: int,
    *,
    commit_fn: Callable[[Path, int, Path | None], str],
    observer_runner: Callable[[Path, int, Path], bool],
) -> AdoptionResult:
    """Adopt in the seven steps fixed by the Ring 4 order."""
    pending = book_dir / "chapters" / "_pending" / f"ch{chapter}.md"
    official = book_dir / "chapters" / f"ch{chapter}.md"

    # 1. Pending must exist and contain real text.
    if not pending.exists() or not pending.read_text(encoding="utf-8").strip():
        raise typer.BadParameter("没有可采用的候选正文；请先生成并读稿")

    # 2. Preserve the former official in the recycle bin.
    recycled = _recycle_official(book_dir, chapter, official)
    # 3. Candidate becomes the on-disk official.
    official.parent.mkdir(parents=True, exist_ok=True)
    pending.replace(official)

    # 4. A Git failure means adoption failed: restore steps 2-3 exactly.
    try:
        commit_hash = commit_fn(book_dir, chapter, recycled)
    except Exception:
        official.replace(pending)
        if recycled is not None and recycled.exists():
            recycled.replace(official)
        raise

    # 5. Dirty is durable before any Observer work begins.
    _set_memory_dirty(book_dir, chapter, True)

    # 6-7. Observer failure never revokes the author's adopted official.
    try:
        memory_updated = bool(observer_runner(book_dir, chapter, official))
        error = "" if memory_updated else "Observer 未完成"
    except Exception as exc:
        memory_updated = False
        error = str(exc)
    _set_memory_dirty(book_dir, chapter, not memory_updated, error)
    return AdoptionResult(commit_hash=commit_hash, memory_updated=memory_updated)


def _undo_adopt(
    book_dir: Path,
    chapter: int,
    *,
    commit_fn: Callable[[Path, int, Path | None], str],
    rebuild_runner: Callable[[Path, int], bool],
    recycled: Path | None = None,
) -> AdoptionResult:
    """Undo one adoption: file transaction first, then deterministic replay.

    A failed commit restores both moves.  Once committed, a failed replay keeps
    the author's text change and records ``memory_dirty`` as Ring 4 requires.
    """
    official = book_dir / "chapters" / f"ch{chapter}.md"
    pending = book_dir / "chapters" / "_pending" / f"ch{chapter}.md"
    if not official.exists():
        raise ValueError("本章没有正式正文，不能撤销采用")
    if pending.exists():
        raise ValueError("本章已有候选正文，不能覆盖")
    if recycled is None:
        trash = book_dir / "logs" / f"ch{chapter}" / "trash"
        candidates = sorted(trash.glob("official_*.md"), reverse=True) if trash.exists() else []
        recycled = candidates[0] if candidates else None

    pending.parent.mkdir(parents=True, exist_ok=True)
    official.replace(pending)
    if recycled is not None and recycled.exists():
        recycled.replace(official)
    try:
        commit_hash = commit_fn(book_dir, chapter, recycled)
    except Exception:
        if official.exists():
            official.replace(recycled if recycled is not None else official)
        pending.replace(official)
        raise

    _set_memory_dirty(book_dir, chapter, True)
    try:
        memory_updated = bool(rebuild_runner(book_dir, chapter))
        error = "" if memory_updated else "记忆分片重放未完成"
    except Exception as exc:
        memory_updated = False
        error = str(exc)
    _set_memory_dirty(book_dir, chapter, not memory_updated, error)
    return AdoptionResult(commit_hash=commit_hash, memory_updated=memory_updated)


def _commit_undo_adoption(book_dir: Path, chapter: int, recycled: Path | None = None) -> str:
    """Commit only the paths changed by one undo transaction."""
    from biyu.git_helper import _run_git, repo_root_for_book

    repo_root = repo_root_for_book(book_dir)
    paths = [
        book_dir / "chapters" / "_pending" / f"ch{chapter}.md",
        book_dir / "chapters" / f"ch{chapter}.md",
    ]
    if recycled is not None:
        paths.append(recycled)
    rel_paths = []
    for path in paths:
        rel = path.resolve().relative_to(repo_root).as_posix()
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", rel], cwd=str(repo_root),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        ).returncode == 0
        if path.exists() or tracked:
            rel_paths.append(rel)
    _run_git("add", "-A", "--", *rel_paths, cwd=repo_root)
    try:
        _run_git(
            "commit",
            "-m",
            f"manual: CH{chapter} 作者撤销采用",
            "--",
            *rel_paths,
            cwd=repo_root,
        )
    except Exception:
        _run_git("restore", "--staged", "--", *rel_paths, cwd=repo_root)
        raise
    return _run_git("rev-parse", "--short", "HEAD", cwd=repo_root).stdout.strip()


@workbench_app.command("adopt")
def adopt(
    chapter: int = typer.Option(..., "--chapter", "-c"),
    book: Optional[str] = typer.Option(None, "--book", "-b"),
) -> None:
    """Adopt the current pending draft as the official chapter."""
    from biyu.git_helper import commit_adoption
    from biyu.ui.workbench_versions import mark_current_candidate_adopted

    book_dir = resolve_book_dir(book)
    result = _adopt_pending(
        book_dir,
        chapter,
        commit_fn=commit_adoption,
        observer_runner=_run_official_observer,
    )
    mark_current_candidate_adopted(book_dir, chapter)
    console.print(f"已采用为正式正文: chapters/ch{chapter}.md")
    console.print(f"版本: {result.commit_hash}")
    if result.memory_updated:
        console.print("本章记忆已更新")
    else:
        console.print("这一章的记忆还没更新；正文已保留，可稍后重算记忆")


@workbench_app.command("undo-adopt")
def undo_adopt(
    chapter: int = typer.Option(..., "--chapter", "-c"),
    book: Optional[str] = typer.Option(None, "--book", "-b"),
) -> None:
    """Return the current official text to candidate and replay memory locally."""
    from biyu.observer import replay_persisted_projections

    book_dir = resolve_book_dir(book)
    result = _undo_adopt(
        book_dir, chapter,
        commit_fn=_commit_undo_adoption,
        rebuild_runner=lambda current_book, _chapter: replay_persisted_projections(current_book),
    )
    if result.memory_updated:
        console.print("这一章退回候选状态，世界观和角色卡已跟着退回")
    else:
        console.print("正文已退回候选状态；记忆重放未完成，可稍后重试")


@workbench_app.command("revise")
def revise(
    chapter: int = typer.Option(..., "--chapter", "-c"),
    book: Optional[str] = typer.Option(None, "--book", "-b"),
    package: Path = typer.Option(..., "--package"),
) -> None:
    """Consume exactly one persisted package and produce a new candidate."""
    import asyncio
    from biyu.pipeline import revise_chapter_from_package

    book_dir = resolve_book_dir(book)
    result = asyncio.run(revise_chapter_from_package(book_dir, chapter, package))
    console.print("整章修订与复审已完成，新候选稿等待定夺")
    console.print(f"候选版本: {result['candidate_sha']}")


@workbench_app.command("excerpt")
def excerpt(
    chapter: int = typer.Option(..., "--chapter", "-c"),
    book: Optional[str] = typer.Option(None, "--book", "-b"),
    kind: str = typer.Option(..., "--kind"),
    content: str = typer.Option(..., "--content"),
    version: str = typer.Option(..., "--version"),
    anchor: int = typer.Option(0, "--anchor"),
) -> None:
    """Append an immutable good/problem sentence snapshot."""
    if kind not in {"good", "problem"}:
        raise typer.BadParameter("摘句类型必须是 good 或 problem")
    if not content.strip():
        raise typer.BadParameter("请先选中一句文字")
    book_dir = resolve_book_dir(book)
    stamp = datetime.now().isoformat(timespec="seconds")
    entry = {
        "id": uuid4().hex,
        "type": kind,
        "text": content.strip(),
        "book": book_dir.name,
        "chapter": chapter,
        "version_sha": version,
        "anchor": anchor if isinstance(anchor, int) else 0,
        "created_at": stamp,
        "status": "候选",
    }
    if kind == "problem":
        from biyu.feedback_ledger import append_feedback

        path = book_dir / "反馈账.jsonl"
        append_feedback(
            book_dir,
            book=book_dir.name,
            chapter=chapter,
            round_no=0,
            scope="sentence",
            candidate_sha=version,
            anchor=max(1, anchor if isinstance(anchor, int) else 0),
            text=content,
            action="note_problem",
            in_revision_package=False,
        )
        console.print(f"已记下问题，暂不修改本章: {path}")
        return
    path = book_dir / "样本库" / "正例候选.md"
    _append(path, "- " + json.dumps(entry, ensure_ascii=False) + "\n")
    console.print(f"已记录好句: {path}")


def _find_excerpt(book_dir: Path, entry_id: str) -> tuple[dict, Path] | None:
    for name in ("正例候选.md", "负例候选.md"):
        path = book_dir / "样本库" / name
        for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
            if not line.startswith("- {"):
                continue
            try:
                item = json.loads(line[2:])
            except json.JSONDecodeError:
                continue
            if item.get("id") == entry_id:
                return item, path
    return None


@workbench_app.command("excerpt-archive")
def excerpt_archive(
    book: Optional[str] = typer.Option(None, "--book", "-b"),
    chapter: int = typer.Option(..., "--chapter", "-c"),
    entry_id: str = typer.Option(..., "--entry-id"),
) -> None:
    book_dir = resolve_book_dir(book)
    found = _find_excerpt(book_dir, entry_id)
    if not found:
        raise typer.BadParameter("没有找到这条摘句，可能已被归档")
    item, path = found
    tombstone = {"id": uuid4().hex, "tombstone_for": entry_id, "status": "回收站", "created_at": datetime.now().isoformat(timespec="seconds"), "snapshot": item}
    _append(path, "- " + json.dumps(tombstone, ensure_ascii=False) + "\n")
    console.print("摘句已移到回收站，30 天内可以取回")


@workbench_app.command("excerpt-retag")
def excerpt_retag(
    book: Optional[str] = typer.Option(None, "--book", "-b"),
    chapter: int = typer.Option(..., "--chapter", "-c"),
    entry_id: str = typer.Option(..., "--entry-id"),
    new_kind: str = typer.Option(..., "--new-kind"),
) -> None:
    if new_kind not in {"good", "problem"}:
        raise typer.BadParameter("摘句类型必须是 good 或 problem")
    book_dir = resolve_book_dir(book)
    found = _find_excerpt(book_dir, entry_id)
    if not found:
        raise typer.BadParameter("没有找到这条摘句，可能已被归档")
    item, old_path = found
    tombstone = {"id": uuid4().hex, "tombstone_for": entry_id, "status": "归档", "created_at": datetime.now().isoformat(timespec="seconds")}
    _append(old_path, "- " + json.dumps(tombstone, ensure_ascii=False) + "\n")
    if new_kind == "problem":
        from biyu.feedback_ledger import append_feedback

        append_feedback(
            book_dir,
            book=book_dir.name,
            chapter=int(item.get("chapter") or chapter),
            round_no=0,
            scope="sentence",
            candidate_sha=str(item.get("version_sha") or "legacy-unknown"),
            anchor=max(1, int(item.get("anchor") or 1)),
            text=str(item.get("text") or ""),
            action="note_problem",
            in_revision_package=False,
            from_kind="good",
        )
    else:
        item = {**item, "id": uuid4().hex, "type": new_kind, "created_at": datetime.now().isoformat(timespec="seconds"), "status": "候选", "replaces": entry_id}
        new_path = book_dir / "样本库" / "正例候选.md"
        _append(new_path, "- " + json.dumps(item, ensure_ascii=False) + "\n")
    console.print("摘句分类已修改，旧记录已归档")


@workbench_app.command("chapter-review")
def chapter_review(
    chapter: int = typer.Option(..., "--chapter", "-c"),
    book: Optional[str] = typer.Option(None, "--book", "-b"),
    content: str = typer.Option(..., "--content"),
) -> None:
    """Append a chapter review and print the real destination."""
    if not content.strip():
        raise typer.BadParameter("章评不能为空")
    book_dir = resolve_book_dir(book)
    path = book_dir / "判词" / f"ch{chapter}.md"
    stamp = datetime.now().isoformat(timespec="seconds")
    _append(path, f"- [{stamp}] {content.strip()}\n")
    console.print(f"章评已保存: {path}")


@workbench_app.command("diagnose")
def diagnose_rework(
    chapter: int = typer.Option(..., "--chapter", "-c"),
    book: Optional[str] = typer.Option(None, "--book", "-b"),
) -> None:
    """Diagnose the primary layer behind three or more rework rounds."""
    from biyu.config import BookConfig, get_registry
    from biyu.pipeline import _log_cost
    from biyu.ui.diagnosis import diagnose_chapter

    book_dir = resolve_book_dir(book)
    config = BookConfig(book_dir)
    adapter = get_registry().get_adapter_for_stage("planner")

    def log_cost(cost: float, latency: float) -> None:
        _log_cost(config, chapter, "diagnosis", cost, latency)

    result = asyncio.run(diagnose_chapter(book_dir, chapter, adapter=adapter, log_cost_fn=log_cost))
    console.print(f"诊断结论: {result['layer']}")
    console.print(result["reason"])
    console.print(f"建议动作: {result['action']}")
