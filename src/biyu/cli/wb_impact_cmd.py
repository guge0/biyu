"""biyu wb-impact — worldbook 改动影响扫描命令。

用法:
    biyu wb-impact <worldbook_path> --since HEAD~1
    biyu wb-impact <worldbook_path> --diff <commit>..<commit>

只列报告，不自动改。退出码: 有影响 → 1; 无影响 → 0。
"""
from __future__ import annotations

import sys
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.panel import Panel

from biyu.lint_rules.wb_impact_scan import diff_worldbook, scan_impact

console = Console()


def wb_impact_command(
    worldbook_path: str = typer.Argument(..., help="worldbook.yaml 路径"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
    since: str = typer.Option(None, "--since", help="对比基准 (git ref)"),
    diff: str = typer.Option(None, "--diff", help="对比范围 (commit..commit)"),
) -> None:
    """扫描 worldbook 改动影响。"""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from biyu.config import resolve_book_dir

    try:
        book_dir = resolve_book_dir(book)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # 加载新 worldbook
    wb_path = Path(worldbook_path)
    if not wb_path.is_absolute():
        candidate = book_dir / worldbook_path
        if candidate.exists():
            wb_path = candidate

    if not wb_path.exists():
        console.print(f"[red]worldbook 不存在: {wb_path}[/red]")
        raise typer.Exit(1)

    with open(wb_path, encoding="utf-8") as f:
        new_wb = yaml.safe_load(f)

    # 加载旧 worldbook
    old_wb = None
    if since or diff:
        old_wb = _load_old_worldbook_git(wb_path, since, diff)
    else:
        # 无对比基准时，尝试用 git HEAD 版本
        old_wb = _load_old_worldbook_git(wb_path, "HEAD", None)
        if old_wb is None:
            # 无法获取旧版，提示用户
            console.print("[yellow]无法获取旧版 worldbook，将作为全新创建处理[/yellow]")

    console.print(f"\n[bold][biyu wb-impact][/bold] 扫描 worldbook 改动")
    console.print("=" * 50)

    items = scan_impact(old_wb, new_wb, book_dir)

    if not items:
        console.print("[green]✅ 无变动[/green]")
        console.print("=" * 50)
        raise typer.Exit(0)

    total_chapters = set()
    for i, item in enumerate(items, 1):
        console.print(f"\n[bold]变动 {i}:[/bold] {item.field_path}")
        if item.old_value and item.new_value:
            console.print(f"  旧值: {item.old_value[:60]}...")
            console.print(f"  新值: {item.new_value[:60]}...")
        elif item.new_value:
            console.print(f"  [green]新增:[/green] {item.new_value[:80]}")
        elif item.old_value:
            console.print(f"  [red]删除:[/red] {item.old_value[:80]}")

        if item.affected_chapters:
            ch_list = ", ".join(f"CH{name[2:]}" for name in item.affected_chapters)
            console.print(f"  受影响章节: {ch_list}")
            total_chapters.update(item.affected_chapters)

        if item.affected_outlines:
            ol_list = ", ".join(f"OL{name[2:]}" for name in item.affected_outlines)
            console.print(f"  受影响 outline: {ol_list}")

        if item.suggestion:
            console.print(f"  [dim]建议: {item.suggestion}[/dim]")

    console.print("\n" + "=" * 50)
    console.print(
        f"共 {len(items)} 项变动, 涉及 {len(total_chapters)} 章节"
    )
    raise typer.Exit(1)


def _load_old_worldbook_git(
    wb_path: Path, since: str | None, diff_range: str | None,
) -> dict | None:
    """从 git 历史加载旧版 worldbook。"""
    import subprocess

    try:
        if diff_range:
            # "commit1..commit2" → 取 commit1 的版本
            old_ref = diff_range.split("..")[0]
            ref = f"{old_ref}:{wb_path}"
        elif since:
            ref = f"{since}:{wb_path}"
        else:
            return None

        # 获取相对路径
        result = subprocess.run(
            ["git", "show", ref],
            capture_output=True, text=True, encoding="utf-8",
            timeout=10,
        )
        if result.returncode == 0:
            return yaml.safe_load(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, yaml.YAMLError):
        pass

    return None
