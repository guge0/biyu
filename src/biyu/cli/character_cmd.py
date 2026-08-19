"""biyu character 子命令 — add / promote。"""
from __future__ import annotations

import typer

character_app = typer.Typer(help="角色管理命令")


@character_app.command("add")
def character_add(
    name: str = typer.Argument(..., help="角色名"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
    auto: bool = typer.Option(False, "--auto", help="AI 辅助全自动(仅 npc 用)"),
):
    """新增角色卡。支持交互式和 AI 辅助两种模式。"""
    from biyu.cli.character_add import add_character
    add_character(name=name, book=book, auto=auto)


@character_app.command("promote")
def character_promote(
    name: str = typer.Argument(..., help="角色名"),
    to_tier: str = typer.Option(..., "--to", help="目标 tier"),
    from_chapter: int = typer.Option(..., "--from-chapter", help="生效章节"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
    reason: str = typer.Option("", "--reason", "-r", help="升格原因"),
):
    """角色升格。"""
    from biyu.cli.character_add import promote_character
    promote_character(name=name, to_tier=to_tier, from_chapter=from_chapter, book=book, reason=reason)
