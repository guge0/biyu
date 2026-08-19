"""biyu status — 查看项目当前状态。"""
from __future__ import annotations

import json
import sys

from rich.console import Console
from rich.table import Table

console = Console()


def status_command(book: str | None = None) -> None:
    """显示项目当前状态：已签章节、待处理章节（含详情）、最近修改、累计成本。"""
    from biyu.config import resolve_book_dir
    from biyu.git_helper import get_recent_commits, get_cost_from_log

    try:
        book_dir = resolve_book_dir(book)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        return

    title = ""
    meta_path = book_dir / "book.json"
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
            title = meta.get("title", "")

    # --- Chapters in chapters/ ---
    chapters_dir = book_dir / "chapters"
    signed_chapters: list[int] = []
    if chapters_dir.exists():
        for f in sorted(chapters_dir.iterdir()):
            if f.is_file() and f.name.startswith("ch") and f.suffix == ".md":
                try:
                    num = int(f.stem[2:])
                    signed_chapters.append(num)
                except ValueError:
                    pass

    # --- Chapters in _pending/ ---
    pending_dir = chapters_dir / "_pending"
    pending_chapters: list[int] = []
    if pending_dir.exists():
        for f in sorted(pending_dir.iterdir()):
            if f.is_file() and f.name.startswith("ch") and f.suffix == ".md":
                try:
                    num = int(f.stem[2:])
                    pending_chapters.append(num)
                except ValueError:
                    pass

    # --- Recent commits ---
    recent = get_recent_commits(max_entries=5)

    # --- Cost ---
    total_cost = get_cost_from_log(book_dir)

    # --- Print ---
    console.print()
    console.print(f"[bold cyan]📚 {title} - 当前状态[/bold cyan]")
    console.print()

    if signed_chapters:
        console.print(f"[green]✅ 已签章节（chapters/）：CH{min(signed_chapters)}-CH{max(signed_chapters)} 共 {len(signed_chapters)} 章[/green]")
    else:
        console.print("[dim]✅ 已签章节：0 章[/dim]")

    if pending_chapters:
        ch_str = ", ".join(f"CH{n}" for n in sorted(pending_chapters))
        console.print(f"[yellow]⚠️ 待处理章节（_pending/）：{ch_str}（{len(pending_chapters)} 章）[/yellow]")

        # Show detail for each pending chapter
        for num in sorted(pending_chapters):
            reason = _get_pending_reason(book_dir, num)
            if reason:
                console.print(f"  - CH{num}: {reason}")
            console.print(f"    [dim]biyu review ch{num}  # 看详情[/dim]")
            console.print(f"    [dim]biyu accept ch{num}  # 手改后接受[/dim]")
            console.print(f"    [dim]biyu approve ch{num} # 不改放过[/dim]")
            console.print(f"    [dim]biyu rewrite ch{num} # 重生成[/dim]")
    else:
        console.print("[green]⚠️ 待处理章节（_pending/）：0 章[/green]")

    console.print()
    if recent:
        console.print("[bold]📊 最近修改：[/bold]")
        for entry in recent:
            date_str = entry["date"][:16]
            msg = entry["message"]
            console.print(f"  [dim]{date_str}[/dim] {msg}")

    console.print()
    console.print(f"[bold]💰 累计成本：¥{total_cost:.2f}[/bold] / 月预算 ¥100")
    console.print()


def _get_pending_reason(book_dir, chapter_num: int) -> str:
    """获取章节进 _pending 的原因。"""
    # Try JSON audit report
    audit_json = book_dir / "audit_reports" / f"ch{chapter_num}.json"
    if audit_json.exists():
        with open(audit_json, encoding="utf-8") as f:
            data = json.load(f)
        results = data.get("results", [])
        blocks = [r for r in results if r.get("severity") == "BLOCK"]
        warns = [r for r in results if r.get("severity") == "WARN"]
        if blocks:
            return f"Auditor BLOCK: {', '.join(r['checker'] for r in blocks)}"
        if warns:
            return f"{len(warns)} 项 Auditor 警告"

    return ""
