"""biyu approve chN — 老板看了不改放过。"""
from __future__ import annotations

import json
import sys

from rich.console import Console

console = Console()


def approve_command(chapter: int, book: str | None = None) -> None:
    """批准章节：显示问题清单确认 → _pending/ 移到 chapters/ + git commit。"""
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
    console.print(f"[bold cyan]📋 审批 CH{chapter}[/bold cyan]")
    console.print()

    # Count issues from audit report
    issue_count = _show_issues_summary(book_dir, chapter)

    # Confirm
    if pending.exists():
        issue_str = f"（已知 {issue_count} 个问题不修）" if issue_count > 0 else ""
        console.print(f"[yellow]确认放过 CH{chapter}{issue_str}？[y/N][/yellow]")
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
    commit_msg_suffix = f"（已知 {issue_count} 个问题）" if issue_count > 0 else ""
    try:
        commit_hash = commit_chapter(
            book_dir, chapter,
            f"老板审阅通过{commit_msg_suffix}",
            auto=False,
        )
        console.print()
        console.print(f"[green]✅ CH{chapter} 已批准[/green]")
        console.print(f"📝 git commit: {commit_hash}")
        console.print(f"📚 状态变更：{location_desc}")
        console.print()
    except Exception as e:
        if "nothing to commit" in str(e).lower() or "no changes" in str(e).lower():
            console.print()
            console.print(f"[green]✅ CH{chapter} 已在 chapters/（无需重复操作）[/green]")
            console.print()
        else:
            console.print(f"[yellow]⚠️ CH{chapter} 移动成功但 commit 失败：{e}[/yellow]")


def _show_issues_summary(book_dir, chapter: int) -> int:
    """显示问题清单摘要，返回问题数。"""
    # Try JSON first
    audit_json = book_dir / "audit_reports" / f"ch{chapter}.json"
    if audit_json.exists():
        with open(audit_json, encoding="utf-8") as f:
            data = json.load(f)
        results = data.get("results", [])
        block_or_warn = [r for r in results if r.get("severity") in ("BLOCK", "WARN")]
        if block_or_warn:
            console.print("[bold]现存问题：[/bold]")
            for r in block_or_warn:
                icon = "❌" if r["severity"] == "BLOCK" else "⚠️"
                console.print(f"  {icon} {r['checker']}: {r['message']}")
            console.print()
            return len(block_or_warn)

    # Try markdown
    audit_md = book_dir / "audit_reports" / f"ch{chapter}.md"
    if audit_md.exists():
        content = audit_md.read_text(encoding="utf-8")
        # Count issue indicators
        warn_count = content.count("⚠️") + content.count("❌")
        if warn_count > 0:
            console.print(f"[dim]（audit_report 中有 {warn_count} 处标记）[/dim]")
            console.print()
        return warn_count

    return 0
