"""biyu auto — 全自动批量生成。"""
from __future__ import annotations

import asyncio
import sys

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def auto_command(
    book: str = typer.Option(..., "--book", "-b", help="书名"),
    from_ch: int = typer.Option(..., "--from", help="起始章节号"),
    to_ch: int = typer.Option(..., "--to", help="结束章节号(含)"),
    warning: float = typer.Option(0.8, "--warning", help="累计成本报警线(元)，默认 ¥0.8，必须显式传参才可调高"),
) -> None:
    """全自动批量生成章节。"""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from biyu.config import resolve_book_dir
    from biyu.auto import auto_generate

    try:
        book_dir = resolve_book_dir(book)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold cyan]批量生成: ch{from_ch} → ch{to_ch}[/bold cyan]")
    console.print(f"  书: {book_dir.name}")
    console.print(f"  章数: {to_ch - from_ch + 1}")
    console.print(f"  报警线: ¥{warning}")

    results = asyncio.run(auto_generate(
        book_dir, from_ch, to_ch,
        warning_threshold=warning,
    ))

    # 汇总表
    table = Table(title="批量生成汇总")
    table.add_column("章节", style="cyan")
    table.add_column("字数", style="green")
    table.add_column("成本", style="yellow")
    table.add_column("延迟", style="dim")
    table.add_column("警告", style="red")

    total_cost = 0.0
    total_words = 0
    for r in results:
        total_cost += r.cost_cny
        total_words += r.word_count
        warn_str = str(len(r.warnings)) if r.warnings else "-"
        table.add_row(
            f"ch{r.chapter_num}",
            str(r.word_count),
            f"¥{r.cost_cny:.4f}",
            f"{r.latency_seconds:.1f}s",
            warn_str,
        )

    table.add_row("合计", str(total_words), f"¥{total_cost:.4f}", "", "")
    console.print(table)
