"""biyu ask 命令 — 和书对话查询。"""
from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown

console = Console()


def ask_command(
    question: str,
    book: str | None,
) -> None:
    """执行 ask 查询。"""
    from biyu.config import get_data_root, get_registry
    from biyu.ask.asker import ask

    data_dir = get_data_root()

    # 找书目录
    if book:
        book_dir = data_dir / book
    else:
        books = [d for d in data_dir.iterdir() if d.is_dir() and (d / "characters.yaml").exists()]
        if len(books) == 1:
            book_dir = books[0]
        elif len(books) == 0:
            console.print("[red]未找到任何书目录[/red]")
            raise typer.Exit(1)
        else:
            import questionary
            book = questionary.select("选择书:", choices=[b.name for b in books]).ask()
            book_dir = data_dir / book

    if not book_dir.exists():
        console.print(f"[red]书目录不存在: {book_dir}[/red]")
        raise typer.Exit(1)

    # 调 LLM
    registry = get_registry()
    adapter = registry.get_adapter("v4_pro")
    console.print("[dim]查询中...[/dim]")

    result = asyncio.run(ask(question, book_dir, adapter))

    console.print()
    console.print(Markdown(result.answer))

    if result.tool_calls:
        console.print(f"\n[dim]📝 工具调用: {', '.join(result.tool_calls)}[/dim]")
    if result.total_cost > 0:
        console.print(f"[dim]💰 成本: ¥{result.total_cost:.4f}[/dim]")
