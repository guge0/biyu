"""S-10 段3a修正·工单第8条：主题首帧不闪。

服务端把用户当前主题的令牌 cssText 随 HTML 内联（window.__BIYU_THEME_BOOT__），
theme-boot.js 在 localStorage 无缓存时用它回放——冷启动首帧即用户主题。
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from biyu.ui import appearance


def _client() -> TestClient:
    from biyu.ui.app import app
    return TestClient(app)


def test_theme_boot_injected_with_user_theme() -> None:
    appearance.save_ui_prefs({"theme": "dark", "custom": None,
                              "background": {"type": "none", "preset": None, "file": None,
                                             "overlay": 90.0, "blur": 0}})
    resp = _client().get("/")
    assert resp.status_code == 200
    html = resp.text
    m = re.search(r"window\.__BIYU_THEME_BOOT__=\"([^\"]*)\"", html)
    assert m, "HTML 头部应内联服务端主题令牌 window.__BIYU_THEME_BOOT__"
    css = m.group(1).encode().decode("unicode_escape")
    # dark 主题的关键令牌必须在首帧脚本里（含玻璃令牌与背景；3g 起玻璃 alpha 0.38/0.45）
    assert "--paper: #181614;" in css
    assert "--glass-bg: rgba(34, 31, 28, 0.38);" in css
    assert "--glass-strong: rgba(30, 28, 26, 0.45);" in css
    assert "--bg-image: none;" in css
    # 注入位置在 <head> 之后、theme-boot.js 之前
    assert html.index("window.__BIYU_THEME_BOOT__") < html.index("theme-boot.js")


def test_theme_boot_injection_follows_custom_colors() -> None:
    appearance.save_ui_prefs({"theme": "default", "custom": {"--paper": "#123456"},
                              "background": {"type": "none", "preset": None, "file": None,
                                             "overlay": 90.0, "blur": 0}})
    html = _client().get("/").text
    m = re.search(r"window\.__BIYU_THEME_BOOT__=\"([^\"]*)\"", html)
    assert m
    css = m.group(1).encode().decode("unicode_escape")
    assert "--paper: #123456;" in css  # 取色覆盖压过预设


def test_theme_boot_injection_follows_glass_personalization() -> None:
    """S-10 3g·工单第2条：雾面浓度/卡片透明度非默认时随首帧注入，刷新不闪。"""
    appearance.save_ui_prefs({"theme": "default", "custom": None,
                              "background": {"type": "none", "preset": None, "file": None,
                                             "overlay": 90.0, "blur": 0,
                                             "mist": 150.0, "glass": 0.25}})
    css = re.search(r"window\.__BIYU_THEME_BOOT__=\"([^\"]*)\"", _client().get("/").text).group(1) \
        .encode().decode("unicode_escape")
    # 雾面浓度 150%：亮色基准档 .45/.45/.40 → 67.5%/67.5%/60%
    assert "--glass-blob-alpha-a: 67.5%;" in css
    assert "--glass-blob-alpha-c: 60%;" in css
    # 卡片透明度 0.25 直驱 --glass-bg，strong = min(0.95, 0.25+0.07) = 0.32
    assert "--glass-bg: rgba(255, 255, 255, 0.25);" in css
    assert "--glass-strong: rgba(255, 255, 255, 0.32);" in css


def test_theme_boot_injection_skips_default_glass() -> None:
    """3g：两字段都在默认值（100%/0.38）时不写覆盖令牌——出栈 preset 令牌已是默认值。"""
    appearance.save_ui_prefs({"theme": "default", "custom": None,
                              "background": {"type": "none", "preset": None, "file": None,
                                             "overlay": 90.0, "blur": 0}})
    css = re.search(r"window\.__BIYU_THEME_BOOT__=\"([^\"]*)\"", _client().get("/").text).group(1) \
        .encode().decode("unicode_escape")
    assert "--glass-blob-alpha" not in css


def test_theme_boot_js_uses_server_fallback() -> None:
    js = (Path(__file__).resolve().parents[1] / "src" / "biyu" / "ui" / "static" / "theme-boot.js") \
        .read_text(encoding="utf-8")
    assert "window.__BIYU_THEME_BOOT__" in js
    # localStorage 优先（同会话内最新），服务端注入只兜冷启动——判执行语句，不看注释
    stmt = [ln for ln in js.splitlines() if "localStorage.getItem" in ln][0]
    assert stmt.index("localStorage.getItem") < stmt.index("__BIYU_THEME_BOOT__")
