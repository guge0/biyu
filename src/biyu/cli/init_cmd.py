"""biyu init — create a new book directory structure."""
from __future__ import annotations

import sys

import typer
from rich.console import Console

console = Console()


def init_command(
    title: str = typer.Option(..., "--title", "-t", help="书名"),
    genre: str = typer.Option(..., "--genre", "-g", help="题材 (xuanhuan/dushi/kehuan)"),
) -> None:
    """初始化一本新书。"""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from biyu.book_service import create_book

    try:
        created = create_book(title, genre)
    except (ValueError, OSError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    book_dir = created.book_dir

    console.print(f"[green]书 '{title}' 初始化完成[/green]")
    console.print(f"  目录: {book_dir}")
    console.print(f"  题材: {genre}")
    console.print(f"  目标字数: 5000/章 (下限 4250)")

    console.print(f"  数据库: {book_dir / 'book.db'}")

    console.print(f"\n  下一步: 编辑 {book_dir / 'outlines' / 'ch1.md'} 写大纲, 然后 biyu write --chapter 1")
