"""biyu serve — 已退役为纯提示壳(P8-M3R T3.1)。

历史:M2.5 期保留为"只读旧入口 + DEPRECATED banner";M3 走查发现仍调 uvicorn 绑端口
(走查单第一步"启用命令和端口都是过时的"血证)。P8-M3R T3.1 收紧为:**只打印提示 +
sys.exit(0),不 import uvicorn、不绑端口**。web/app.py 不删(路由仍给 ui/app.py include)。

正确入口:`biyu ui`(src/biyu/ui/app.py,作者工作台统一入口)。
"""
from __future__ import annotations

import sys

import typer
from rich.console import Console

console = Console()


def serve_command(
    port: int = typer.Option(8080, "--port", "-p", help="(已忽略)旧端口参数,保留仅为向后兼容"),
) -> None:
    """[DEPRECATED] 已退役:请改用 `biyu ui`。

    本命令不再启动服务、不绑端口,仅打印提示后立即退出(code=0)。
    正确命令:`biyu ui`(作者工作台统一入口)。
    """
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    console.print("[bold yellow]⚠ DEPRECATED, 请用 biyu ui[/bold yellow]")
    console.print("  本命令已退役,不再启动服务、不绑端口。")
    console.print("  正确命令:[bold cyan]biyu ui[/bold cyan](作者工作台统一入口:首页 + 立项屏 + 编辑部 + 审读)。")
    console.print("  双击启动:项目根 [dim]start_biyu_ui.bat[/dim] (Windows) / [dim]start_biyu_ui.sh[/dim] (macOS/Linux)。")
    console.print("  历史:M2.5 期为只读旧入口;M3 走查发现仍绑端口(P8-M3R T3.1 收紧)。web/app.py 仍 include,不删。")

    sys.exit(0)
