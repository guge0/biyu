"""biyu rollback chN — 回滚章节到上一版本。"""
from __future__ import annotations

import sys

from rich.console import Console

console = Console()


def rollback_ch_command(
    chapter: int,
    book: str | None = None,
    target_hash: str | None = None,
) -> None:
    """回滚章节到上一个 git 版本（或指定版本）。"""
    from biyu.config import resolve_book_dir
    from biyu.git_helper import get_chapter_history, rollback_chapter

    try:
        book_dir = resolve_book_dir(book)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        return

    history = get_chapter_history(book_dir, chapter)

    if not history:
        console.print(f"[red]CH{chapter}: 无 git 历史记录[/red]")
        return

    if target_hash:
        # Roll back to specified hash
        ok = rollback_chapter(book_dir, chapter, target_hash)
        if ok:
            console.print()
            console.print(f"[green]✅ CH{chapter} 已回滚到 {target_hash[:7]}[/green]")
            console.print()
        else:
            console.print(f"[red]CH{chapter}: 回滚失败[/red]")
    else:
        # Show history and roll back to previous version
        console.print()
        console.print(f"[bold cyan]⏪ CH{chapter} 版本历史[/bold cyan]")
        console.print()

        for i, entry in enumerate(history):
            marker = "→" if i == 0 else " "
            console.print(f"  {marker} {entry['hash']} {entry['date'][:16]} {entry['message']}")

        if len(history) < 2:
            console.print()
            console.print("[yellow]仅有一个版本，无法回滚[/yellow]")
            return

        target = history[1]
        ok = rollback_chapter(book_dir, chapter, target["hash"])
        if ok:
            console.print()
            console.print(f"[green]✅ CH{chapter} 已回滚到 {target['hash']} ({target['message']})[/green]")
            console.print()
        else:
            console.print(f"[red]CH{chapter}: 回滚失败[/red]")
