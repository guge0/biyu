"""T3.1(P8-M3R)— `biyu serve` 退役为纯提示壳(不绑端口)。

Spec(specs/P8-M3R.md R3):
  serve_cmd.py 改成打印 "DEPRECATED, 请用 biyu ui" + 正确命令后 sys.exit(0)
  (不调 uvicorn);web/app.py 不删(路由仍给 ui/app.py include)。

验收:
  - 启动后立即退出(code=0),不绑定端口
  - 打印 DEPRECATED + 正确命令(biyu ui)
  - 不 import uvicorn / 不调 uvicorn.run

零烧钱,纯 capsys + pytest.raises(SystemExit)。
"""
from __future__ import annotations

import pytest


def test_serve_exits_zero():
    """serve_command 必须立即 sys.exit(0),不绑端口。"""
    from biyu.cli.serve_cmd import serve_command

    with pytest.raises(SystemExit) as excinfo:
        serve_command(port=9999)
    assert excinfo.value.code == 0, f"期望 exit code 0,实际 {excinfo.value.code}"


def test_serve_banner_warns_deprecated(capsys: pytest.CaptureFixture[str]):
    """banner 含 'DEPRECATED' / '已废弃' / '弃用' 字样。"""
    from biyu.cli.serve_cmd import serve_command

    with pytest.raises(SystemExit):
        serve_command(port=9999)

    out = capsys.readouterr().out
    assert any(kw in out for kw in ["DEPRECATED", "已废弃", "弃用"]), (
        f"serve banner 未含 deprecated 标识。输出:\n{out}"
    )


def test_serve_banner_directs_to_ui(capsys: pytest.CaptureFixture[str]):
    """banner 必须指向 `biyu ui`(正确命令)。"""
    from biyu.cli.serve_cmd import serve_command

    with pytest.raises(SystemExit):
        serve_command(port=9999)

    out = capsys.readouterr().out
    assert "biyu ui" in out, f"serve banner 未指向 biyu ui。输出:\n{out}"


def test_serve_does_not_import_uvicorn():
    """serve_cmd 模块不得 import uvicorn(避免绑端口的可能性)。"""
    import importlib
    import sys

    # 清缓存确保重 import
    sys.modules.pop("biyu.cli.serve_cmd", None)
    importlib.import_module("biyu.cli.serve_cmd")
    import biyu.cli.serve_cmd as mod

    # 模块级不得出现 uvicorn import
    assert "uvicorn" not in dir(mod), (
        "serve_cmd 不应再 import uvicorn;退役为纯提示壳。"
    )
    assert not hasattr(mod, "uvicorn"), "serve_cmd 不应再持有 uvicorn 属性。"
