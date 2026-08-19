"""R3-1 verdict add — 判词与样本候选三落点。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from biyu.config import resolve_book_dir

console = Console()
verdict_app = typer.Typer(help="判词与样本候选归档。")


def _append(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def add_verdict(*, chapter: int, book: Optional[str], verdict: str, positive: str = "", negative: str = "") -> None:
    if not verdict.strip():
        raise typer.BadParameter("判词不能为空")
    book_dir = resolve_book_dir(book)
    stamp = datetime.now().isoformat(timespec="seconds")
    verdict_path = book_dir / "判词" / f"ch{chapter}.md"
    _append(verdict_path, f"- [{stamp}] ch{chapter}: {verdict.strip()}\n")
    if positive.strip():
        _append(book_dir / "样本库" / "正例候选.md", f"- [{stamp}] ch{chapter}: {positive.strip()}\n")
    if negative.strip():
        from biyu.feedback_ledger import append_feedback

        append_feedback(
            book_dir,
            book=book_dir.name,
            chapter=chapter,
            round_no=0,
            scope="chapter",
            verdict=negative,
            action="note_problem",
            in_revision_package=False,
        )
    console.print(f"判词: {verdict_path}")
    console.print(f"正例候选: {book_dir / '样本库' / '正例候选.md'}")
    console.print(f"章级反馈账: {book_dir / '反馈账.jsonl'}")


@verdict_app.command("add")
def add(
    chapter: int = typer.Option(..., "--chapter", "-c"),
    book: Optional[str] = typer.Option(None, "--book", "-b"),
    verdict: str = typer.Option(..., "--verdict"),
    positive: str = typer.Option("", "--positive"),
    negative: str = typer.Option("", "--negative"),
) -> None:
    """追加判词，按需追加正／负例候选。"""
    add_verdict(chapter=chapter, book=book, verdict=verdict, positive=positive, negative=negative)
