"""biyu cost — show cost summary from cost_log.csv."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def cost_command(
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
) -> None:
    """显示成本汇总。"""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from biyu.config import resolve_book_dir

    try:
        book_dir = resolve_book_dir(book)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    cost_path = book_dir / "logs" / "cost_log.csv"
    if not cost_path.exists():
        console.print(f"[yellow]暂无成本记录: {cost_path}[/yellow]")
        raise typer.Exit(0)

    rows: list[dict] = []
    with open(cost_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    if not rows:
        console.print("[yellow]成本日志为空[/yellow]")
        raise typer.Exit(0)

    # Group by chapter
    chapters: dict[str, list[dict]] = {}
    for row in rows:
        ch = row.get("chapter", "?")
        chapters.setdefault(ch, []).append(row)

    table = Table(title=f"成本汇总 — {book_dir.name}")
    table.add_column("章节", style="cyan")
    table.add_column("阶段", style="blue")
    table.add_column("成本 (¥)", style="green", justify="right")
    table.add_column("延迟 (s)", style="yellow", justify="right")

    total_cost = 0.0
    for ch_num in sorted(chapters.keys(), key=lambda x: int(x) if x.isdigit() else 0):
        ch_rows = chapters[ch_num]
        ch_cost = sum(float(r.get("cost_cny", 0)) for r in ch_rows)
        for r in ch_rows:
            table.add_row(
                f"第{r.get('chapter', '?')}章" if r == ch_rows[0] else "",
                r.get("stage", "?"),
                f"{float(r.get('cost_cny', 0)):.4f}",
                r.get("latency_s", "?"),
            )
        total_cost += ch_cost

    table.add_row("", "[bold]累计[/bold]", f"[bold]{total_cost:.4f}[/bold]", "")
    console.print(table)
