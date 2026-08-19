"""biyu review chN — 查看章节审稿信息。"""
from __future__ import annotations

import json
import sys

from rich.console import Console
from rich.table import Table

console = Console()


def review_command(chapter: int, book: str | None = None) -> None:
    """显示章节的审稿信息：audit report + 评分 + 修改历史。"""
    from biyu.config import resolve_book_dir
    from biyu.git_helper import get_chapter_history

    try:
        book_dir = resolve_book_dir(book)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        return

    ch_file = book_dir / "chapters" / f"ch{chapter}.md"
    pending_file = book_dir / "chapters" / "_pending" / f"ch{chapter}.md"

    # --- Locate chapter ---
    chapter_path = None
    location = ""
    if ch_file.exists():
        chapter_path = ch_file
        location = f"chapters/ch{chapter}.md"
    elif pending_file.exists():
        chapter_path = pending_file
        location = f"chapters/_pending/ch{chapter}.md"

    console.print()
    console.print(f"[bold cyan]📖 CH{chapter} 审稿信息[/bold cyan]")
    console.print()

    if chapter_path:
        text = chapter_path.read_text(encoding="utf-8")
        # Count CJK chars
        cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        console.print(f"📝 章节路径：data/{book_dir.name}/{location}")
        console.print(f"📊 字数：{cjk_count}")
    else:
        console.print(f"[red]未找到 CH{chapter}[/red]")
        return

    # --- Audit report (JSON) ---
    audit_json = book_dir / "audit_reports" / f"ch{chapter}.json"
    audit_md = book_dir / "audit_reports" / f"ch{chapter}.md"

    if audit_json.exists():
        with open(audit_json, encoding="utf-8") as f:
            audit_data = json.load(f)

        console.print()
        console.print("[bold]🔍 检查器结果：[/bold]")

        results = audit_data.get("results", [])
        has_issue = False
        for r in results:
            checker = r.get("checker", "?")
            severity = r.get("severity", "?")
            message = r.get("message", "")

            if severity == "BLOCK":
                icon = "❌"
                style = "red"
            elif severity == "WARN":
                icon = "⚠️"
                style = "yellow"
            elif severity == "PASS":
                icon = "✅"
                style = "green"
            else:
                icon = "•"
                style = "dim"

            console.print(f"  {icon} [{style}]{checker}[/{style}]: {message}")
            if severity in ("BLOCK", "WARN"):
                has_issue = True
    elif audit_md.exists():
        console.print()
        console.print(f"📝 完整问题报告：data/{book_dir.name}/audit_reports/ch{chapter}.md")
    else:
        console.print()
        console.print("[dim]（无 audit report）[/dim]")

    # --- Git history ---
    history = get_chapter_history(book_dir, chapter)
    if history:
        console.print()
        console.print("[bold]📌 修改历史：[/bold]")
        for i, entry in enumerate(history, 1):
            date_str = entry["date"][:16]
            msg = entry["message"]
            console.print(f"  {i}. {msg} ({date_str})")

    # --- Action suggestions ---
    console.print()
    console.print("[bold]操作选项：[/bold]")
    console.print(f"  biyu accept ch{chapter}   # 我手改完了，接受")
    console.print(f"  biyu approve ch{chapter}  # 不改放过")
    console.print(f"  biyu rewrite ch{chapter}  # 重生成")
    console.print()
