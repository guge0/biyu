"""biyu accept chN — 老板手改完后接受章节。"""
from __future__ import annotations

import json
import sys

from rich.console import Console

console = Console()


def accept_command(chapter: int, book: str | None = None, message: str = "") -> None:
    """接受章节：显示 audit_report 确认 → _pending/ 移到 chapters/ + git commit。"""
    from biyu.config import resolve_book_dir
    from biyu.git_helper import move_to_chapters, commit_chapter

    try:
        book_dir = resolve_book_dir(book)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        return

    pending = book_dir / "chapters" / "_pending" / f"ch{chapter}.md"
    target = book_dir / "chapters" / f"ch{chapter}.md"

    if not pending.exists() and not target.exists():
        console.print(f"[red]CH{chapter}: 未找到章节文件[/red]")
        return

    console.print()
    console.print(f"[bold cyan]✅ 接受 CH{chapter}[/bold cyan]")
    console.print()

    # Show audit report summary if exists
    _show_audit_summary(book_dir, chapter)

    # Confirm
    if pending.exists():
        console.print(f"[yellow]确认接受 CH{chapter}（_pending/ → chapters/）？[y/N][/yellow]")
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print("[dim]已取消[/dim]")
            return
        if answer != 'y':
            console.print("[dim]已取消[/dim]")
            return

        moved = move_to_chapters(book_dir, chapter)
        if not moved:
            console.print(f"[red]CH{chapter}: 移动失败[/red]")
            return
        location_desc = "(_pending/ → chapters/)"
    else:
        location_desc = "(已在 chapters/)"

    # Git commit
    try:
        commit_msg = message or "老板手改后接受"
        commit_hash = commit_chapter(book_dir, chapter, commit_msg, auto=False)
        console.print()
        console.print(f"[green]✅ CH{chapter} 已接受[/green]")
        console.print(f"📝 git commit: {commit_hash} — manual: CH{chapter} {commit_msg}")
        console.print(f"📚 状态变更：{location_desc}")
        console.print()
    except Exception as e:
        console.print(f"[yellow]⚠️ CH{chapter} 移动成功但 commit 失败：{e}[/yellow]")
        console.print("[dim]章节已在 chapters/，可手动 git add + commit[/dim]")


def _show_audit_summary(book_dir, chapter: int) -> None:
    """显示 audit_report 摘要。"""
    audit_md = book_dir / "audit_reports" / f"ch{chapter}.md"
    if audit_md.exists():
        content = audit_md.read_text(encoding="utf-8")
        # 提取关键行
        lines = content.splitlines()
        for line in lines:
            if line.startswith("> ") or line.startswith("## ") or line.startswith("- **"):
                console.print(f"  {line}")
        console.print()
        return

    # Fallback: try JSON
    audit_json = book_dir / "audit_reports" / f"ch{chapter}.json"
    if audit_json.exists():
        with open(audit_json, encoding="utf-8") as f:
            data = json.load(f)
        results = data.get("results", [])
        for r in results:
            severity = r.get("severity", "?")
            checker = r.get("checker", "?")
            msg = r.get("message", "")
            icon = "❌" if severity == "BLOCK" else "⚠️" if severity == "WARN" else "✅"
            console.print(f"  {icon} {checker}: {msg}")
        console.print()
