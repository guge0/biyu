"""biyu write — generate a chapter through the pipeline."""
from __future__ import annotations

import asyncio
import sys

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def write_command(
    chapter: int = typer.Option(..., "--chapter", "-c", help="章节号"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
    planner: str = typer.Option(None, "--planner", help="规划阶段模型别名(覆盖yaml配置)"),
    writer: str = typer.Option(None, "--writer", help="写作阶段模型别名(覆盖yaml配置)"),
    polisher: str = typer.Option(None, "--polisher", help="润色阶段模型别名(覆盖yaml配置)"),
    prompt_version: str = typer.Option("v4", "--prompt-version", help="v3=旧 prompt,v4=新三层 prompt"),
    replan: bool = typer.Option(False, "--replan", help="无视已有规划件,强制走内置 Architect 重出"),
    force_pending: bool = typer.Option(False, "--force-pending", hidden=True),
) -> None:
    """生成一章小说。可通过 --planner/--writer/--polisher 临时覆盖模型，仅影响当次调用。"""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from biyu.config import resolve_book_dir
    from biyu.pipeline import generate_chapter

    try:
        book_dir = resolve_book_dir(book)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # Build model overrides dict (only non-None values)
    model_overrides = {}
    if planner:
        model_overrides["planner"] = planner
    if writer:
        model_overrides["writer"] = writer
    if polisher:
        model_overrides["polisher"] = polisher

    console.print(f"[bold cyan]开始生成第 {chapter} 章[/bold cyan]")
    console.print(f"  书: {book_dir.name}")
    if model_overrides:
        console.print(f"  模型覆盖: {model_overrides}")
    console.print(f"  Prompt版本: {prompt_version}")

    from biyu.setup_asset_versions import SetupAssetYamlError
    try:
        result = asyncio.run(generate_chapter(
            book_dir, chapter,
            model_overrides=model_overrides or None,
            prompt_version=prompt_version,
            replan=replan,
            force_pending=force_pending,
        ))
    except SetupAssetYamlError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    # Print summary table
    table = Table(title=f"第 {chapter} 章生成完成")
    table.add_column("指标", style="cyan")
    table.add_column("值", style="green")

    table.add_row("字数 (CJK)", str(result.word_count))
    table.add_row("总成本", f"¥{result.cost_cny:.4f}")
    table.add_row("总延迟", f"{result.latency_seconds:.1f}s")

    for stage, latency in result.stage_latencies.items():
        table.add_row(f"  {stage}", f"{latency:.1f}s")

    if result.warnings:
        table.add_row("警告", "\n".join(result.warnings))

    console.print(table)

    # Print file paths
    chapter_path = book_dir / "chapters" / ("_pending" if force_pending else "") / f"ch{chapter}.md"
    console.print(f"\n  产出: {chapter_path}")
    console.print(f"  日志: {book_dir / 'logs' / f'ch{chapter}'}")
