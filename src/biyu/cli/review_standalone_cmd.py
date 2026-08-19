"""P8-M2 T3 · `biyu review-standalone` — Editor 独立审读入口。

不走生成管线,直接对指定章跑 Editor,产出问题卡 Markdown。

与既有命令的边界:
- `biyu review chN`       — 查看 chapters/_pending/chN.md 已有的 audit 报告(只读)
- `biyu revise chN`       — 管理 Editor 已生成的 issue(应用 / 重生成 / 解决)
- `biyu review-standalone` — 本命令,对任意章独立跑一次 Editor,产出新问题卡

为什么不复用 `biyu review`:`review` 读既有 audit 报告,本命令跑 Editor。
为什么不复用 `biyu revise`:`revise` 接的 Reviser 改稿链,本命令先于 Reviser。

D-70 兜底出声:truth_files 缺失时由 standalone.run_standalone_review 出 WARNING。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def review_standalone_command(
    chapter: int = typer.Option(..., "--chapter", "-c", help="章节号"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
    output: str = typer.Option(
        None, "--output", "-o",
        help="输出 Markdown 路径(默认 data/<book>/reviews/standalone/chN.md)",
    ),
    model: str = typer.Option(
        None, "--model",
        help="覆盖 LLM 模型别名(默认 pipeline.writer 配的别名)",
    ),
    print_md: bool = typer.Option(
        False, "--print-md",
        help="额外把 Markdown 全文打到 stdout(默认只保存文件)",
    ),
    no_save: bool = typer.Option(
        False, "--no-save",
        help="不保存文件,只返回结果(配合 --print-md 用)",
    ),
) -> None:
    """对指定章独立跑 Editor 审读,产出问题卡 Markdown。"""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from biyu.config import resolve_book_dir
    from biyu.editor.editor import _enable_editor_file_logging
    from biyu.editor.standalone import (
        run_standalone_review,
        summarize_failure_modes,
        summarize_issues,
    )
    from biyu.llm import ModelRegistry

    # 1. 解析书目录
    try:
        book_dir = resolve_book_dir(book)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]书目录解析失败: {e}[/red]")
        raise typer.Exit(1)

    # 2. 加载上一章末尾(跨章衔接用,Editor 内部已默认空串,这里只是预读)
    prev_tail = ""
    if chapter > 1:
        prev_path = book_dir / "chapters" / f"ch{chapter - 1}.md"
        if prev_path.exists():
            prev_text = prev_path.read_text(encoding="utf-8")
            prev_tail = prev_text[-500:]

    # 3. 建 adapter(走 writer stage,与 pipeline.py editor 阶段一致)
    registry = ModelRegistry()
    try:
        adapter = registry.get_adapter_for_stage("writer", override=model)
    except (KeyError, ValueError) as e:
        console.print(f"[red]LLM 适配器构造失败: {e}[/red]")
        raise typer.Exit(1)

    # 4. 开 Editor 文件日志(UTF-8,绕 Windows 终端 GBK)
    try:
        log_path = _enable_editor_file_logging()
        console.print(f"[dim]Editor 日志: {log_path}[/dim]")
    except Exception as e:
        # 兜底出声 D-70:日志初始化失败不许静默
        console.print(f"[yellow]Editor 日志初始化失败(忽略,继续跑): {e}[/yellow]")

    # 5. 跑
    console.print(f"[bold cyan]开始独立审读 第{chapter}章[/bold cyan]")
    console.print(f"  书: {book_dir.name}")
    if model:
        console.print(f"  模型覆盖: {model}")

    try:
        result, md = asyncio.run(run_standalone_review(
            book_dir, chapter_num=chapter, adapter=adapter,
            prev_chapter_tail=prev_tail,
        ))
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]审读失败: {e}[/red]")
        raise typer.Exit(1)

    # 6. 落盘
    if not no_save:
        if output:
            out_path = Path(output)
        else:
            out_path = book_dir / "reviews" / "standalone" / f"ch{chapter}.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        console.print(f"[green]报告已保存: {out_path}[/green]")

    if print_md:
        console.print(Panel(md, title="问题卡", border_style="cyan"))

    # 7. 摘要表
    summary = summarize_issues(result)
    failures = summarize_failure_modes(result)
    table = Table(title=f"第{chapter}章 审读摘要", show_header=False)
    table.add_column("指标", style="cyan", no_wrap=True)
    table.add_column("值", style="white")
    table.add_row("Issue 数", str(summary["total"]))
    if summary["by_type"]:
        type_str = ", ".join(f"{t}×{n}" for t, n in summary["by_type"].items())
        table.add_row("按类型", type_str)
    if summary["by_severity"]:
        sev_str = ", ".join(f"{s}×{n}" for s, n in summary["by_severity"].items())
        table.add_row("按严重度", sev_str)
    if failures:
        fail_str = ", ".join(f"{m}×{n}" for m, n in failures.items())
        table.add_row("[yellow]失败模式[/yellow]", f"[yellow]{fail_str}[/yellow]")
    table.add_row("信心", result.confidence)
    table.add_row("成本", f"¥{result.cost:.4f}")
    console.print(table)
