# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec:biyu-sidecar(笔驭 v1.0 安装包本地服务)。

onedir(非 onefile):首启更快、杀毒误报更少、排障友好;NSIS/便携层在 T10 叠加。
datas 用 collect_data_files('biyu') 带上包内非 Python 资源(ui/static 的 html/js/css/字体、
audit_reports/templates、prompt/templates 等);根级 config/docs/prompts 载荷不经此处,
由 build_sidecar.ps1 staging 到 home 目录,经 BIYU_PROJECT_ROOT 指给运行期。
"""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

# 数据必须取自源码树 src/biyu:site-packages 里的 biyu 是陈旧安装副本
# (实测缺 audit_reports/templates 等),而模块本身经 pathex=src 从源码编译。
_SRC_BIYU = Path(os.path.abspath(os.path.join(SPECPATH, "..", "src", "biyu")))
_datas = []
for _root, _dirs, _files in os.walk(_SRC_BIYU):
    if "__pycache__" in _root:
        continue
    for _f in _files:
        if _f.endswith((".py", ".pyc", ".pyo")):
            continue
        _abs = Path(_root) / _f
        _dest = _abs.parent.relative_to(_SRC_BIYU.parent).as_posix()
        _datas.append((str(_abs), _dest))

# conda 底座 venv(本机 biyu312)的 OpenSSL DLL 带 -x64 后缀,PyInstaller 默认钩子
# 按无后缀名匹配会漏带,导致冻结后 _ssl「DLL load failed」;此处动态补齐。
_extra_bins = []
_conda_bin = Path(sys.base_prefix) / "Library" / "bin"
for _dll in (
    "libcrypto-3.dll", "libssl-3.dll",
    "libcrypto-3-x64.dll", "libssl-3-x64.dll",
    "sqlite3.dll",
    "ffi.dll", "ffi-8.dll", "ffi-7.dll",  # _ctypes(conda 命名)
):
    _p = _conda_bin / _dll
    if _p.is_file():
        _extra_bins.append((str(_p), "."))

_hidden = [
    # uvicorn 按运行时字符串选择实现,静态分析追不到
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

# 动态 import 的检查器/规则模块(auditor 与 lint_rules 按 _REGISTRY 字符串加载,
# PyInstaller 静态分析看不到;冻结版漏包会让所有检查器报 No module named)
from PyInstaller.utils.hooks import collect_submodules

_hidden += collect_submodules("biyu.auditor")
_hidden += collect_submodules("biyu.lint_rules")

a = Analysis(
    [os.path.join(SPECPATH, "sidecar_main.py")],
    pathex=[os.path.abspath(os.path.join(SPECPATH, "..", "src"))],
    binaries=_extra_bins,
    datas=_datas,
    hiddenimports=_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="biyu-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=os.path.join(SPECPATH, "electron", "icons", "biyu.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="biyu-sidecar",
)
