"""biyu rewrite chN — 重生成章节。"""
from __future__ import annotations

import sys

from rich.console import Console

console = Console()


def rewrite_command(chapter: int, book: str | None = None) -> None:
    """重生成指定章节。

    流程:
    1. 显示当前 audit_report 问题
    2. 确认重生成
    3. 触发 biyu write
    """
    from biyu.config import resolve_book_dir

    try:
        book_dir = resolve_book_dir(book)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        return

    ch_file = book_dir / "chapters" / f"ch{chapter}.md"
    pending_file = book_dir / "chapters" / "_pending" / f"ch{chapter}.md"

    if not ch_file.exists() and not pending_file.exists():
        console.print(f"[red]CH{chapter}: 未找到章节文件[/red]")
        return

    console.print()
    console.print(f"[bold cyan]🔄 重生成 CH{chapter}[/bold cyan]")
    console.print()

    # Show current issues
    _show_current_issues(book_dir, chapter)

    # Confirm
    console.print(f"[yellow]重生成会覆盖当前版本，确认？[y/N][/yellow]")
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print("[dim]已取消[/dim]")
        return
    if answer != 'y':
        console.print("[dim]已取消[/dim]")
        return

    console.print()
    console.print(f"运行以下命令重生成章节：")
    console.print(f"[bold]  biyu write --chapter {chapter}[/bold]")
    console.print()
    console.print("[dim]重生成后 pipeline 会自动 git commit（regen: 前缀）。[/dim]")
    console.print()


def _show_current_issues(book_dir, chapter: int) -> None:
    """显示当前章节的已知问题。"""
    import json
    audit_json = book_dir / "audit_reports" / f"ch{chapter}.json"
    if audit_json.exists():
        with open(audit_json, encoding="utf-8") as f:
            data = json.load(f)
        results = data.get("results", [])
        issues = [r for r in results if r.get("severity") in ("BLOCK", "WARN")]
        if issues:
            console.print("[bold]当前问题：[/bold]")
            for r in issues:
                console.print(f"  ⚠️ {r['checker']}: {r['message']}")
            console.print()
