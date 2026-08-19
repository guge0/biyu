"""biyu lint — outline / sub-md 工程冲突扫描命令。

用法:
    biyu lint outlines/ch28.md           # 扫单个 outline
    biyu lint outlines/sub_md_ch28-30.md # 扫 sub-md
    biyu lint --before-write             # biyu write 启动前自动跑

退出码: 全 ✅ → 0; 有 ⚠️ → 1; 有 ❌ → 2
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.text import Text

from biyu.lint_rules import run_lint
from biyu.lint_rules.base import LintContext

console = Console()


def _load_pending_hooks(book_dir: Path) -> list[dict[str, str]]:
    """解析 pending_hooks.md 表格。"""
    hooks_path = book_dir / "truth_files" / "pending_hooks.md"
    if not hooks_path.exists():
        # 尝试根目录
        hooks_path = book_dir / "pending_hooks.md"
    if not hooks_path.exists():
        return []

    text = hooks_path.read_text(encoding="utf-8")
    hooks: list[dict[str, str]] = []

    lines = text.splitlines()
    # 找表头行
    header_idx = -1
    for i, line in enumerate(lines):
        if line.strip().startswith("|") and "hook_id" in line:
            header_idx = i
            break

    if header_idx < 0:
        return hooks

    # 解析表头
    headers = [h.strip() for h in lines[header_idx].split("|") if h.strip()]

    # 跳过分隔行 (|---|---|)
    data_start = header_idx + 2 if header_idx + 1 < len(lines) else header_idx + 1

    for line in lines[data_start:]:
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        cells = [c for c in cells if c]  # 去空
        if len(cells) < len(headers):
            continue

        hook = {}
        for j, header in enumerate(headers):
            if j < len(cells):
                hook[header] = cells[j]
        hooks.append(hook)

    return hooks


def _build_context(book_dir: Path) -> LintContext:
    """构建 LintContext。"""
    # 加载 characters
    chars_path = book_dir / "characters.yaml"
    characters = []
    if chars_path.exists():
        with open(chars_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        characters = data.get("characters", [])

    # 加载 worldbook
    wb_path = book_dir / "worldbook.yaml"
    worldbook = None
    if wb_path.exists():
        with open(wb_path, encoding="utf-8") as f:
            worldbook = yaml.safe_load(f)

    # 加载 pending hooks
    pending_hooks = _load_pending_hooks(book_dir)

    return LintContext(
        book_dir=book_dir,
        characters=characters,
        worldbook=worldbook,
        pending_hooks=pending_hooks,
        outlines_dir=book_dir / "outlines",
        chapters_dir=book_dir / "chapters",
    )


def _severity_icon(severity: str) -> str:
    return {"info": "ℹ️", "warning": "⚠️", "error": "❌"}.get(severity, "?")

def _severity_exit_code(issues: list) -> int:
    """根据 issues 决定退出码。"""
    for issue in issues:
        if issue.severity == "error":
            return 2
    for issue in issues:
        if issue.severity == "warning":
            return 1
    return 0


def lint_command(
    target: str = typer.Argument(..., help="outline/sub-md 文件路径"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
) -> None:
    """扫描 outline / sub-md 工程冲突。"""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from biyu.config import resolve_book_dir

    try:
        book_dir = resolve_book_dir(book)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    target_path = Path(target)
    if not target_path.is_absolute():
        # 尝试相对于 book_dir
        candidate = book_dir / target
        if candidate.exists():
            target_path = candidate
        elif not target_path.exists():
            console.print(f"[red]文件不存在: {target}[/red]")
            raise typer.Exit(1)

    if not target_path.exists():
        console.print(f"[red]文件不存在: {target_path}[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold][biyu lint][/bold] 扫描 {target_path.name}")
    console.print("=" * 50)

    ctx = _build_context(book_dir)
    issues = run_lint(target_path, ctx)

    if not issues:
        console.print("[green]✅ 扫描完成: 无问题[/green]")
        console.print("=" * 50)
        raise typer.Exit(0)

    # 按严重级别分组显示
    for issue in issues:
        icon = _severity_icon(issue.severity)
        style = {"error": "red", "warning": "yellow", "info": "cyan"}.get(
            issue.severity, "white"
        )
        console.print(f"[{style}]{icon} {issue.message}[/{style}]")
        if issue.suggestion:
            console.print(f"   [dim]建议: {issue.suggestion}[/dim]")

    # 汇总
    console.print("=" * 50)
    info_count = sum(1 for i in issues if i.severity == "info")
    warn_count = sum(1 for i in issues if i.severity == "warning")
    err_count = sum(1 for i in issues if i.severity == "error")
    console.print(
        f"扫描完成: {info_count} ℹ️  {warn_count} ⚠️  {err_count} ❌"
    )

    raise typer.Exit(_severity_exit_code(issues))
