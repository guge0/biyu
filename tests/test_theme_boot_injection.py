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
    # dark 主题的关键令牌必须在首帧脚本里（含玻璃令牌与背景）
    assert "--paper: #181614;" in css
    assert "--glass-strong: rgba(30, 28, 26, 0.58);" in css
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


def test_theme_boot_js_uses_server_fallback() -> None:
    js = (Path(__file__).resolve().parents[1] / "src" / "biyu" / "ui" / "static" / "theme-boot.js") \
        .read_text(encoding="utf-8")
    assert "window.__BIYU_THEME_BOOT__" in js
    # localStorage 优先（同会话内最新），服务端注入只兜冷启动——判执行语句，不看注释
    stmt = [ln for ln in js.splitlines() if "localStorage.getItem" in ln][0]
    assert stmt.index("localStorage.getItem") < stmt.index("__BIYU_THEME_BOOT__")
