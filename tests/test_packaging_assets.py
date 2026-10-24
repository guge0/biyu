"""S-3 打包链静态资产契约(packaging/)。

不依赖真实构建产物(dist/ 由 build_sidecar.ps1 生成,冒烟由 smoke_sidecar.py 做);
此处锚定:骨架文件在位、图标容器合法、Key 红线(models.yaml 永不入包)在脚本层成立。
"""
from __future__ import annotations

import struct
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PK = REPO / "packaging"


def test_packaging_skeleton_files_exist() -> None:
    for rel in (
        "sidecar_main.py",
        "sidecar.spec",
        "build_sidecar.ps1",
        "smoke_sidecar.py",
        "make_icon.py",
        "requirements-build.txt",
        "README.md",
        "electron/main.js",
        "electron/package.json",
    ):
        assert (PK / rel).is_file(), f"missing packaging asset: {rel}"


def test_sidecar_main_refuses_without_env() -> None:
    text = (PK / "sidecar_main.py").read_text(encoding="utf-8")
    assert "BIYU_SIDECAR_PORT" in text
    assert "BIYU_DATA_ROOT" in text
    assert "refusing to start" in text or "拒绝启动" in text


def test_build_script_never_stages_private_models_yaml() -> None:
    """Key 红线:构建脚本只 staging models.yaml.example,绝不带私人 models.yaml。"""
    text = (PK / "build_sidecar.ps1").read_text(encoding="utf-8")
    assert "'models.yaml.example'" in text
    assert "'models.yaml'" not in text
    assert "FORBIDDEN: models.yaml must never be staged" in text


def test_icon_ico_container_is_valid() -> None:
    ico = PK / "electron" / "icons" / "biyu.ico"
    assert ico.is_file(), "biyu.ico missing (run packaging/make_icon.py)"
    raw = ico.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", raw[:6])
    assert (reserved, kind) == (0, 1)
    assert count >= 5, "ico should carry >=5 sizes"
    first_w = raw[6]
    assert first_w in (16, 0), "first entry should be smallest or 256(marker 0)"
    # 每张内嵌图均为 PNG
    import zlib  # noqa: F401  (仅确认可导入;PNG 魔数断言如下)

    for i in range(count):
        off = 6 + 16 * i
        _, _, _, _, _, _, size, offset = struct.unpack("<BBBBHHII", raw[off:off + 16])
        blob = raw[offset:offset + size]
        assert blob[:8] == b"\x89PNG\r\n\x1a\n", f"entry {i} not PNG-embedded"


def test_electron_main_kills_sidecar_on_quit() -> None:
    text = (PK / "electron" / "main.js").read_text(encoding="utf-8")
    assert "taskkill" in text
    assert "before-quit" in text
    assert "BIYU_SIDECAR_PORT" in text
    assert "biyu-studio" in text  # 安装版默认数据根 %APPDATA%\biyu-studio


def test_electron_package_declares_product_name_and_version() -> None:
    import json

    meta = json.loads((PK / "electron" / "package.json").read_text(encoding="utf-8"))
    assert meta["productName"] == "笔驭"
    assert meta["version"] == "1.0.0"
    assert meta["main"] == "main.js"
