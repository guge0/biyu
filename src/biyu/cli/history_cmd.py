"""biyu history chN — 查看章节完整时间线。"""
from __future__ import annotations

import sys

from rich.console import Console

console = Console()


def history_command(chapter: int, book: str | None = None) -> None:
    """显示章节的完整修改时间线。"""
    from biyu.config import resolve_book_dir
    from biyu.git_helper import get_chapter_history

    try:
        book_dir = resolve_book_dir(book)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        return

    console.print()
    console.print(f"[bold cyan]📜 CH{chapter} 完整时间线[/bold cyan]")
    console.print()

    history = get_chapter_history(book_dir, chapter, max_entries=50)

    if not history:
        console.print("[yellow]无 git 历史记录[/yellow]")
        console.print()
        return

    # Determine timeline labels
    for i, entry in enumerate(reversed(history)):
        idx = len(history) - i
        msg = entry["message"]
        date_str = entry["date"][:19]
        h = entry["hash"]

        # Classify type
        if msg.startswith("auto:"):
            label = "[dim]auto[/dim]"
        elif msg.startswith("manual:"):
            label = "[cyan]manual[/cyan]"
        elif msg.startswith("regen:"):
            label = "[yellow]regen[/yellow]"
        else:
            label = "[white]other[/white]"

        console.print(f"  {idx:2d}. {label} ({date_str}) {msg}")
        console.print(f"      [dim]commit {h}[/dim]")

    console.print()
