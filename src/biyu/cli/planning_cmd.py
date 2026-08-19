"""R3-1 planning approve/revoke — status 行唯一状态主权。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from biyu.config import resolve_book_dir

console = Console()
planning_app = typer.Typer(help="合同盖章与撤章。")


def _planning_path(book_dir: Path, chapter: int) -> Path:
    return book_dir / "logs" / f"ch{chapter}" / "planning.md"


def set_planning_status(*, chapter: int, book: Optional[str], revoke: bool) -> None:
    path = _planning_path(resolve_book_dir(book), chapter)
    if not path.exists():
        raise typer.BadParameter(f"合同不存在: {path}")
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if not lines or not lines[0].strip().startswith("status:"):
        raise typer.BadParameter(f"合同首行缺少 status: {path}")
    wanted = "待批" if revoke else "已批"
    ending = "\r\n" if lines[0].endswith("\r\n") else "\n"
    current = lines[0].split(":", 1)[1].strip()
    if current == wanted:
        console.print(f"合同已是「{wanted}」，无需重复操作: {path}")
        return
    lines[0] = f"status: {wanted}{ending}"
    path.write_text("".join(lines), encoding="utf-8")
    console.print(f"合同状态已改为「{wanted}」: {path}")


@planning_app.command("approve")
def approve(
    chapter: int = typer.Option(..., "--chapter", "-c"),
    book: Optional[str] = typer.Option(None, "--book", "-b"),
    revoke: bool = typer.Option(False, "--revoke"),
) -> None:
    """只改 planning.md 首行状态，正文保持原字节。"""
    set_planning_status(chapter=chapter, book=book, revoke=revoke)
