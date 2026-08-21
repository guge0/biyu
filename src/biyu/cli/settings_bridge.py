"""Supported editor bridge for the production settings HTTP contract.

This module deliberately knows nothing about asset files or C1 helpers.  The
production Web service remains the only writer and concurrency authority.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
import typer


settings_write_app = typer.Typer(help="责编通过笔驭设定集接口写创作件。")


def _runtime_settings() -> tuple[str, Path]:
    """Require the launch source to bind both endpoint and data root."""
    import os

    base_url = os.environ.get("BIYU_SETTINGS_EDITOR_URL", "").strip()
    data_root = os.environ.get("BIYU_SETTINGS_DATA_ROOT", "").strip()
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname != "127.0.0.1" or parsed.port not in {8080, 8090}:
        raise RuntimeError("责编运行来源未绑定有效端口（只接受 8080 或 8090），拒绝写入。")
    if not data_root:
        raise RuntimeError("责编运行来源未绑定数据根，拒绝写入。")
    return base_url, Path(data_root).expanduser().resolve()


def _normal_root(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def _message_for_response(response: httpx.Response) -> tuple[str, str]:
    if response.status_code == 409:
        return "conflict", "你刚在网页改过这一格，我这版没写进去，要不要我重来。"
    try:
        detail = str(response.json().get("detail") or response.text)
    except (ValueError, AttributeError):
        detail = response.text
    return "failed", f"这一格没写进去：{detail or '服务返回了错误。'}"


def write_cell(
    *,
    book: str,
    cell_id: str,
    content: str,
    base_url: str,
    expected_data_root: Path,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """GET the current cell, then attempt exactly one version-guarded PUT."""
    with httpx.Client(base_url=base_url, transport=transport, timeout=10.0) as client:
        opened = client.get(f"/books/{quote(book, safe='')}")
        opened.raise_for_status()
        snapshot = opened.json()
        cell = next((item for item in snapshot["cells"] if item["id"] == cell_id), None)
        if cell is None:
            return {"status": "failed", "message": f"没有找到设定格 {cell_id}。"}
        result = {
            "data_root": snapshot["data_root"],
            "cell": cell["label"],
            "previous_length": cell["length"],
        }
        if _normal_root(snapshot.get("data_root", "")) != _normal_root(expected_data_root):
            return {**result, "status": "failed", "message": "服务数据根与责编拉起来源不一致，拒绝写入。"}
        typer.echo(f"目标数据根：{result['data_root']}")
        typer.echo(f"{result['cell']}现有 {result['previous_length']} 字，准备整格替换。")
        saved = client.put(
            f"/books/{quote(book, safe='')}/cells/{quote(cell_id, safe='')}",
            json={"version": cell["version"], "content": content},
        )
        if saved.status_code != 200:
            status, message = _message_for_response(saved)
            return {**result, "status": status, "message": message}
        return {
            **result,
            "status": "ok",
            "message": f"{cell['label']}已写入。",
            "new_length": saved.json()["cell"]["length"],
        }


def write_character(
    *,
    book: str,
    name: str,
    content: str,
    base_url: str,
    expected_data_root: Path,
    transport: httpx.BaseTransport | None = None,
    archive: bool = False,
) -> dict[str, Any]:
    """GET a character card, then update or archive it exactly once."""
    with httpx.Client(base_url=base_url, transport=transport, timeout=10.0) as client:
        opened = client.get(f"/books/{quote(book, safe='')}")
        opened.raise_for_status()
        snapshot = opened.json()
        card = next((item for item in snapshot["characters"] if item["name"] == name), None)
        creating = card is None
        if creating and archive:
            return {"status": "failed", "message": f"没有找到人物“{name}”，不能归档。"}
        if creating:
            card = {"version": snapshot["character_version"], "content": ""}
        result = {
            "data_root": snapshot["data_root"],
            "cell": f"人物卡：{name}",
            "previous_length": len(card["content"]),
        }
        if _normal_root(snapshot.get("data_root", "")) != _normal_root(expected_data_root):
            return {**result, "status": "failed", "message": "服务数据根与责编拉起来源不一致，拒绝写入。"}
        typer.echo(f"目标数据根：{result['data_root']}")
        typer.echo(f"{result['cell']}现有 {result['previous_length']} 字，准备整格替换。")
        path = f"/books/{quote(book, safe='')}/characters/{quote(name, safe='')}"
        if archive:
            saved = client.post(path + "/archive", json={"version": card["version"]})
        else:
            saved = client.put(path, json={"version": card["version"], "content": content})
        if saved.status_code != 200:
            status, message = _message_for_response(saved)
            return {**result, "status": status, "message": message}
        action = "已归档" if archive else ("已创建" if creating else "已写入")
        return {**result, "status": "ok", "message": f"人物卡“{name}”{action}。"}


def _echo(result: dict[str, Any]) -> None:
    if result.get("data_root"):
        typer.echo(f"目标数据根：{result['data_root']}")
        typer.echo(f"{result['cell']}现有 {result['previous_length']} 字，准备整格替换。")
    typer.echo(str(result["message"]))
    if result["status"] != "ok":
        raise typer.Exit(code=2)


@settings_write_app.command("cell")
def cell_command(
    book: str = typer.Option(..., "--book", help="书的 id"),
    cell_id: str = typer.Option(..., "--cell", help="设定格 id"),
    content_file: Path = typer.Option(..., "--content-file", exists=True, dir_okay=False),
) -> None:
    """写北极星、大纲或单个世界观格；细纲不在此合同内。"""
    try:
        base_url, expected_root = _runtime_settings()
        result = write_cell(book=book, cell_id=cell_id, content=content_file.read_text(encoding="utf-8"), base_url=base_url, expected_data_root=expected_root)
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2)
    except (httpx.ConnectError, httpx.TimeoutException):
        typer.echo("笔驭网页服务没开。请先双击 start_biyu_ui.bat。")
        raise typer.Exit(code=2)
    except httpx.HTTPStatusError as exc:
        typer.echo(f"读取设定失败：HTTP {exc.response.status_code}。")
        raise typer.Exit(code=2)
    _echo(result)


@settings_write_app.command("character")
def character_command(
    book: str = typer.Option(..., "--book", help="书的 id"),
    name: str = typer.Option(..., "--name", help="人物姓名"),
    content_file: Path = typer.Option(..., "--content-file", exists=True, dir_okay=False),
) -> None:
    """新增或整卡替换一张人物卡，不提供删除。"""
    try:
        base_url, expected_root = _runtime_settings()
        result = write_character(
            book=book, name=name, content=content_file.read_text(encoding="utf-8"),
            base_url=base_url, expected_data_root=expected_root,
        )
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2)
    except (httpx.ConnectError, httpx.TimeoutException):
        typer.echo("笔驭网页服务没开。请先双击 start_biyu_ui.bat。")
        raise typer.Exit(code=2)
    _echo(result)


@settings_write_app.command("archive-character")
def archive_character_command(
    book: str = typer.Option(..., "--book", help="书的 id"),
    name: str = typer.Option(..., "--name", help="人物姓名"),
) -> None:
    """归档人物卡；责编合同没有硬删除命令。"""
    try:
        base_url, expected_root = _runtime_settings()
        result = write_character(book=book, name=name, content="", archive=True, base_url=base_url, expected_data_root=expected_root)
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2)
    except (httpx.ConnectError, httpx.TimeoutException):
        typer.echo("笔驭网页服务没开。请先双击 start_biyu_ui.bat。")
        raise typer.Exit(code=2)
    _echo(result)
