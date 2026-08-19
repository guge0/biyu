"""biyu suggest 命令 — 轻量决策面板，扫描 outline 留白并让老板批量决策。"""
from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from biyu.config import get_data_root, get_registry, resolve_book_dir
from biyu.suggest_engine import (
    BlankDecision,
    build_options,
    generate_suggestion,
    record_decision,
    resolve_outline_path,
    scan_file,
)

console = Console()


def suggest_command(
    chapter: int | None = typer.Option(None, "--chapter", "-c", help="章节号"),
    outline: str | None = typer.Option(None, "--outline", help="outline 文件路径"),
    sub_md: str | None = typer.Option(None, "--sub-md", help="sub-md 文件路径"),
    book: str | None = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
) -> None:
    """扫描 outline/sub-md 中的留白决策，逐条提供选项。"""
    # 解析书目录
    try:
        book_dir = resolve_book_dir(book)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # 解析要扫描的文件
    target = resolve_outline_path(book_dir, chapter=chapter, outline=outline, sub_md=sub_md)
    if target is None:
        console.print("[red]未找到目标文件。请指定 --chapter, --outline 或 --sub-md[/red]")
        raise typer.Exit(1)

    # 扫描留白
    console.print(f"[cyan][biyu suggest][/cyan] 扫描 {target}")
    console.print("=" * 44)

    decisions = scan_file(target)

    if not decisions:
        console.print("[green]未发现任何留白标记。[/green]")
        return

    console.print(f"发现 {len(decisions)} 条留白决策:\n")

    # 获取 LLM adapter
    registry = get_registry()
    adapter = registry.get_adapter("v4_pro")

    total_cost = 0.0

    for i, decision in enumerate(decisions, 1):
        # 生成示例值
        console.print(f"[bold][{i}/{len(decisions)}][/bold] {decision.prompt}")
        console.print(f"  [dim]上下文:{decision.context}[/dim]")

        suggestion = ""
        try:
            with console.status("生成示例值中..."):
                suggestion = asyncio.run(generate_suggestion(decision, book_dir, adapter))
        except Exception as e:
            console.print(f"  [yellow]示例值生成失败: {e}[/yellow]")
            suggestion = ""

        options = build_options(decision, suggestion)
        decision.options = options
        decision.suggestion = suggestion

        console.print()
        for j, opt in enumerate(options, 1):
            console.print(f"  [bold]{j})[/bold] {opt}")
        console.print()

        # 交互式选择
        chosen = _ask_choice(len(options))
        decision.chosen = chosen
        decision.chosen_value = _resolve_chosen_value(decision, chosen)

        # 记录决策
        log_path = record_decision(decision, book_dir)
        console.print(f"  [dim]已记录 → {log_path}[/dim]")
        console.print()

    # 汇总
    console.print(
        Panel(
            f"共处理 {len(decisions)} 条留白决策\n"
            f"决策记录: {book_dir / 'decisions' / 'suggest_log.yaml'}",
            title="biyu suggest 完成",
            border_style="green",
        )
    )


def _ask_choice(max_val: int) -> int:
    """交互式让用户选择 1-max_val。"""
    while True:
        try:
            raw = input(f"  请选择 [1-{max_val}]: ").strip()
            val = int(raw)
            if 1 <= val <= max_val:
                return val
            console.print(f"  [yellow]请输入 1-{max_val} 之间的数字[/yellow]")
        except (ValueError, EOFError):
            console.print(f"  [yellow]请输入 1-{max_val} 之间的数字[/yellow]")
        except KeyboardInterrupt:
            console.print("\n  [yellow]已中断[/yellow]")
            raise typer.Exit(0)


def _resolve_chosen_value(decision: BlankDecision, chosen: int) -> str:
    """根据选择确定最终值。"""
    if chosen == 1:
        # 示例值: 提取冒号后的部分
        opt = decision.options[0]
        if ":" in opt:
            return opt.split(":", 1)[1].strip()
        return decision.suggestion
    elif chosen == 2:
        return "auto"
    else:
        return "skip"
