"""biyu diff chN — 查看章节修改历史（diff）。"""
from __future__ import annotations

import sys

from rich.console import Console

console = Console()


def diff_command(
    chapter: int,
    book: str | None = None,
    from_ref: str | None = None,
    to_ref: str | None = None,
) -> None:
    """显示章节的 git diff。"""
    from biyu.config import resolve_book_dir
    from biyu.git_helper import diff_chapter, get_chapter_history

    try:
        book_dir = resolve_book_dir(book)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        return

    console.print()
    console.print(f"[bold cyan]📊 CH{chapter} 修改对比[/bold cyan]")
    console.print()

    # Show history context
    history = get_chapter_history(book_dir, chapter, max_entries=5)
    if history:
        console.print("[dim]版本历史：[/dim]")
        for i, entry in enumerate(history):
            marker = "→" if i == 0 else " "
            console.print(f"  {marker} {entry['hash']} {entry['date'][:16]} {entry['message']}")
        console.print()

    # Get diff
    diff_text = diff_chapter(book_dir, chapter, from_ref=from_ref, to_ref=to_ref)
    console.print(diff_text)
    console.print()
