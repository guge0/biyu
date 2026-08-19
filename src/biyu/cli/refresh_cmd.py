"""biyu refresh / rollback — 改稿同步命令。"""
from __future__ import annotations

import sys

import typer
from rich.console import Console

console = Console()


def rebuild_memory_command(
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="确认产生真实 LLM 费用"),
) -> None:
    """从全部正式正文重算长期记忆，并打印逐文件 diff 摘要。"""
    import asyncio
    from biyu.config import BookConfig, get_registry, resolve_book_dir
    from biyu.observer import rebuild_hooks
    from biyu.pipeline import _log_cost

    if not yes and not typer.confirm("将读取全部正式章节并产生 LLM 费用，继续？"):
        raise typer.Abort()
    book_dir = resolve_book_dir(book)
    registry = get_registry()
    observer_alias = registry.get_pipeline_config().get("writer", "v3")
    adapter = registry.get_adapter_for_stage("writer", override=observer_alias)
    book_config = BookConfig(book_dir)
    result = asyncio.run(rebuild_hooks(
        book_dir,
        adapter,
        _log_cost_fn=lambda chapter, cost, latency: _log_cost(
            book_config, chapter, "observer", cost, latency,
        ),
    ))
    console.print(f"备份: {result['backup_path']}")
    for path, item in result["diff"].items():
        if item["changed"]:
            console.print(f"已重算: {path} {item['before_sha256'][:8]} → {item['after_sha256'][:8]}")
    if result["errors"]:
        console.print("[red]部分章节记忆未更新；正式正文未受影响[/red]")
        for error in result["errors"]:
            console.print(f"[red]- {error}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]记忆重算完成: {result['chapters_processed']} 章[/green]")


def refresh_command(
    chapter: int = typer.Option(None, "--chapter", "-c", help="单章刷新"),
    from_ch: int = typer.Option(None, "--from", help="起始章节(范围刷新)"),
    to_ch: int = typer.Option(None, "--to", help="结束章节(范围刷新)"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
) -> None:
    """重跑 Observer 刷新设定文件。支持 --chapter N 或 --from X --to Y。"""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from biyu.config import resolve_book_dir
    from biyu.refresh import refresh_chapter, refresh_range

    try:
        book_dir = resolve_book_dir(book)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if chapter is not None:
        ok = refresh_chapter(book_dir, chapter)
        if ok:
            console.print(f"[green]ch{chapter} 刷新成功[/green]")
        else:
            console.print(f"[red]ch{chapter} 刷新失败[/red]")
            raise typer.Exit(1)
    elif from_ch is not None and to_ch is not None:
        results = refresh_range(book_dir, from_ch, to_ch)
        success = sum(1 for _, ok in results if ok)
        console.print(f"[green]{success}/{len(results)} 章刷新成功[/green]")
    else:
        console.print("[red]请指定 --chapter N 或 --from X --to Y[/red]")
        raise typer.Exit(1)


def rollback_command(
    to_chapter: int = typer.Option(..., "--to-chapter", "-t", help="回退到的目标章节号"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
) -> None:
    """回退 truth_files 到指定章节的历史状态，并归档后续章节。"""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from biyu.config import resolve_book_dir
    from biyu.refresh import rollback_to_chapter

    try:
        book_dir = resolve_book_dir(book)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    ok = rollback_to_chapter(book_dir, to_chapter)
    if ok:
        console.print(f"[green]已回退到 ch{to_chapter} 状态[/green]")
    else:
        console.print(f"[red]回退失败[/red]")
        raise typer.Exit(1)


def rollback_full_command(
    to_chapter: int,
    book: str | None = None,
) -> None:
    """整退:章文件 + truth_files 一次退到第 N 章后状态。

    内部串联既有两刀（不造新轮子）:
    1. rollback_to_chapter → 归档后续章节 + 恢复 truth_files 到 chN
    2. 当前保留的章文件保持不动（归档已移走 >N 的章节）
    """
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from biyu.config import resolve_book_dir
    from biyu.refresh import rollback_to_chapter

    try:
        book_dir = resolve_book_dir(book)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # 第一步:归档后续章节 + 恢复 truth_files
    console.print(f"[cyan]▶ 整退到 ch{to_chapter}...[/cyan]")
    ok = rollback_to_chapter(book_dir, to_chapter)
    if not ok:
        console.print(f"[red]整退失败:truth_files 回退未完成[/red]")
        raise typer.Exit(1)

    # 第二步:清理 pending 目录中 > to_chapter 的章节
    pending_dir = book_dir / "chapters" / "_pending"
    if pending_dir.exists():
        from pathlib import Path
        moved = 0
        for p in sorted(pending_dir.glob("ch*.md")):
            stem = p.stem
            try:
                ch_num = int(stem.replace("ch", ""))
            except ValueError:
                continue
            if ch_num > to_chapter:
                p.unlink()
                moved += 1
        if moved:
            console.print(f"[dim]  清理 pending: {moved} 个文件[/dim]")

    console.print(f"[green]✓ 整退完成:ch{to_chapter} 后状态[/green]")
