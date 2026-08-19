"""biyu ui — 启动作者工作台(立项屏)。

与 biyu serve(章节工作台壳)隔离:独立 FastAPI app,默认 host=127.0.0.1,
端口冲突自动 +1 重试(8080 → 8081 → ... → 8089),10 次失败报错退出(D-70)。

启动 banner 打印实际监听端口 + 环境 level + 数据根目录,让作者看清自己在哪。
"""
from __future__ import annotations

import socket
import sys

import typer
import uvicorn
from rich.console import Console

from biyu.config import get_data_root
from biyu.ui.env import read_env

console = Console()

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8080
_MAX_PORT_RETRIES = 10


def _find_available_port(host: str, start: int, max_retries: int) -> int:
    """探测从 start 起,host 上第一个可 bind 的端口。

    Args:
        host: 监听地址
        start: 起始端口
        max_retries: 最多重试次数(含 start)

    Returns:
        第一个可 bind 的端口

    Raises:
        RuntimeError: max_retries 次全失败(D-70 出声)
    """
    last_err = ""
    for offset in range(max_retries):
        port = start + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
                return port
        except OSError as e:
            last_err = str(e)
            continue
    raise RuntimeError(
        f"端口 {start}..{start + max_retries - 1} 全部不可用(最后错误:{last_err})。"
        f"请用 --port 指定其他端口,或释放被占端口。"
    )


def ui_command(
    port: int = typer.Option(_DEFAULT_PORT, "--port", "-p", help="监听端口"),
    host: str = typer.Option(_DEFAULT_HOST, "--host", help="监听地址(默认 127.0.0.1,不暴露外网)"),
) -> None:
    """启动作者工作台(立项屏)— 复用 P7-2 propose 子模块,网页壳形态。"""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # 探测可用端口(冲突时自动 +1)
    try:
        actual_port = _find_available_port(host, port, _MAX_PORT_RETRIES)
    except RuntimeError as e:
        console.print(f"[bold red]✗ 启动失败:[/bold red] {e}")
        raise typer.Exit(code=1)

    # banner:让作者看清自己在哪(端口 / 环境 / 数据根目录)
    env_info = read_env()
    data_root = get_data_root()

    env_color = "red" if env_info["level"] == "prod" else "dim"
    console.print(f"[bold cyan]笔驭作者工作台(立项屏)启动中...[/bold cyan]")
    console.print(f"  地址     : [underline]http://{host}:{actual_port}[/underline]")
    console.print(f"  环境     : [{env_color}]{env_info['label']}({env_info['level']})[/{env_color}]")
    console.print(f"  数据根目录: {data_root}")
    if port != actual_port:
        console.print(
            f"  [yellow]⚠ 端口 {port} 被占,已自动换到 {actual_port}[/yellow]"
        )
    console.print(
        f"  [dim]提示:在浏览器打开上面的地址开始使用。Ctrl+C 退出。[/dim]"
    )

    uvicorn.run(
        "biyu.ui.app:app",
        host=host,
        port=actual_port,
        log_level="info",
    )
