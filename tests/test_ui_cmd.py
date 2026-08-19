"""Tests for biyu.cli.ui_cmd(P8-M1 T6)— 端口冲突自动换 + banner.

覆盖:
- _find_available_port:冲突自动 +1 重试到下一个
- _find_available_port:10 次失败 → raise(D-70 出声)
- ui_command 默认 host=127.0.0.1(不 0.0.0.0)
- banner 含 env level + 数据根目录

uvicorn.run 通过 monkeypatch 替换为 no-op,不真起服务。
"""
from __future__ import annotations

import socket
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from biyu.cli.main import app
from biyu.cli.ui_cmd import _find_available_port, ui_command


runner = CliRunner()


# ---------------------------------------------------------------------------
# _find_available_port
# ---------------------------------------------------------------------------


class _FakeSocket:
    """假 socket —— bind 行为由 _bind_fail_ports 控制。"""

    _bind_fail_ports: set[int] = set()

    def __init__(self, *args, **kwargs):
        pass

    def setsockopt(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        return False

    def bind(self, addr):
        host, port = addr
        if port in self._bind_fail_ports:
            raise OSError(f"[Errno 98] Address already in use: port={port}")


def test_find_available_port_retries_on_conflict(monkeypatch: pytest.MonkeyPatch):
    """端口冲突 → 自动 +1 重试到下一个可用端口。"""
    monkeypatch.setattr(socket, "socket", _FakeSocket)
    # 8080 模拟被占,8081 可用
    _FakeSocket._bind_fail_ports = {8080}
    port = _find_available_port(host="127.0.0.1", start=8080, max_retries=10)
    assert port == 8081


def test_find_available_port_raises_after_all_fail(monkeypatch: pytest.MonkeyPatch):
    """所有 10 次重试都失败 → raise RuntimeError(D-70 不沉默)。"""
    monkeypatch.setattr(socket, "socket", _FakeSocket)
    _FakeSocket._bind_fail_ports = set(range(8080, 8090))
    with pytest.raises(RuntimeError, match="8080"):
        _find_available_port(host="127.0.0.1", start=8080, max_retries=10)


def test_find_available_port_returns_start_when_free(monkeypatch: pytest.MonkeyPatch):
    """无冲突 → 直接返 start。"""
    monkeypatch.setattr(socket, "socket", _FakeSocket)
    _FakeSocket._bind_fail_ports = set()
    port = _find_available_port(host="127.0.0.1", start=8080, max_retries=10)
    assert port == 8080


# ---------------------------------------------------------------------------
# ui_command 默认 host + banner
# ---------------------------------------------------------------------------


def test_ui_command_default_host_is_localhost(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """ui_command 默认 host=127.0.0.1(不 0.0.0.0)。"""
    # 不真起 uvicorn
    monkeypatch.setattr("biyu.cli.ui_cmd.uvicorn", MagicMock())
    monkeypatch.setattr("biyu.cli.ui_cmd._find_available_port", lambda host, start, max_retries: start)
    monkeypatch.setattr("biyu.cli.ui_cmd.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.cli.ui_cmd.read_env", lambda: {"level": "test", "label": "测试", "color": "#a8a8a8"})

    # 直接调函数,拿默认 host(typer.Option 返 OptionInfo,真值在 .default)
    import inspect
    sig = inspect.signature(ui_command)
    host_default = sig.parameters["host"].default
    actual = getattr(host_default, "default", host_default)
    assert actual == "127.0.0.1", "默认 host 必须 127.0.0.1,不 0.0.0.0"


def test_ui_command_banner_contains_env_and_data_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
):
    """banner 打印实际端口 + 环境 level + 数据根目录(让作者看清自己在哪)。"""
    monkeypatch.setattr("biyu.cli.ui_cmd.uvicorn", MagicMock())
    monkeypatch.setattr(
        "biyu.cli.ui_cmd._find_available_port",
        lambda host, start, max_retries: 8085,
    )
    monkeypatch.setattr("biyu.cli.ui_cmd.get_data_root", lambda: tmp_path)
    monkeypatch.setattr(
        "biyu.cli.ui_cmd.read_env",
        lambda: {"level": "test", "label": "测试", "color": "#a8a8a8"},
    )

    ui_command(port=8080, host="127.0.0.1")

    out = capsys.readouterr().out
    # 实际监听端口(banner 必含)
    assert "8085" in out
    # 环境 level(test/prod)与 label
    assert "test" in out or "测试" in out
    # 数据根目录(rich 可能按宽度换行,去掉所有空白后对比路径)
    out_compact = "".join(out.split())
    path_compact = "".join(str(tmp_path).split())
    assert path_compact in out_compact, f"banner 未含数据根目录 {tmp_path}"


def test_ui_command_help_lists_port_and_host():
    """biyu ui --help 输出含 --port --host(T7 注册前置验证)。"""
    result = runner.invoke(app, ["ui", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.output
    assert "--host" in result.output
