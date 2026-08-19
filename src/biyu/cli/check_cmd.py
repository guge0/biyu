"""biyu check — 一致性检查命令。"""
from __future__ import annotations

import sys

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()


def check_command(
    chapter: int = typer.Option(..., "--chapter", "-c", help="章节号"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
) -> None:
    """检查章节一致性。"""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from biyu.config import resolve_book_dir
    from biyu.consistency import check_chapter
    from biyu.db import init_db, sync_characters_from_yaml

    try:
        book_dir = resolve_book_dir(book)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # Ensure DB exists and is synced
    init_db(book_dir)
    sync_result = sync_characters_from_yaml(book_dir)
    console.print(
        f"  角色同步: yaml {sync_result[0]} 条 → SQLite {sync_result[1]} 条写入"
    )

    # Run consistency check
    issues = check_chapter(book_dir, chapter)

    if not issues:
        console.print(Panel(
            f"第 {chapter} 章一致性检查通过",
            style="green",
            border_style="green",
        ))
        return

    # Display issues
    console.print(f"\n[bold red]第 {chapter} 章发现 {len(issues)} 个一致性问题:[/bold red]\n")

    for i, issue in enumerate(issues, 1):
        severity_style = "bold red" if issue.severity == "critical" else "yellow"
        severity_tag = f"[{severity_style}][{issue.severity.upper()}][/{severity_style}]"

        console.print(f"  {i}. {severity_tag} [cyan]{issue.rule}[/cyan]")

        # Character name
        console.print(f"     角色: [bold]{issue.character}[/bold]")

        # Location snippet - highlight the character name
        snippet_text = Text(issue.location)
        highlight_start = issue.location.find(issue.character)
        if highlight_start >= 0:
            snippet_text.stylize(
                "bold red",
                highlight_start,
                highlight_start + len(issue.character),
            )
        console.print(Text("     片段: "), snippet_text)

        # Suggestion
        if issue.suggestion:
            console.print(f"     建议: [dim]{issue.suggestion}[/dim]")

        console.print()

    # Summary
    critical = sum(1 for i in issues if i.severity == "critical")
    warnings = len(issues) - critical
    console.print(
        f"  [bold]汇总:[/bold] {critical} critical, {warnings} warning"
    )
