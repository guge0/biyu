"""S-1 令牌零差异校验：shell.js 的 THEME_PRESETS / WALLPAPER_PRESETS 必须与
视觉规范 v2.0 事实源（reference_biyu_ai_v2.html）逐字节一致；biyu-paper.css 的
:root 默认令牌必须等于 default 主题预设。反糊弄第 1 条的自动化闸。

期望值从 E:\\webnovel\\_biyu协作\\商业化派单\\S-1_shell_v2_foundation\\
reference_biyu_ai_v2.html 的 THEME_PRESETS（2087-2235 行）与 WALLPAPER_PRESETS
（2238-2243 行）逐项抄录，禁止从 shell.js 反向复制。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "biyu" / "ui" / "static"

TOKEN_KEYS = [
    "--paper", "--surface", "--surface-subtle", "--ink", "--ink-solid",
    "--ink-soft", "--ink-mute", "--ink-faint", "--rule", "--rule-strong",
    "--rule-soft", "--numeral", "--mark", "--mark-bg", "--accent",
    "--accent-fg", "--btn-border", "--outer-bg",
]

EXPECTED_THEME_PRESETS: dict[str, dict[str, str]] = {
    "default": {
        "name": "温润手稿 · 云宣白卡 (默认)",
        "--paper": "#F3F1EA",
        "--surface": "#FFFFFF",
        "--surface-subtle": "#F9F8F3",
        "--ink": "#1F1C18",
        "--ink-solid": "#26221C",
        "--ink-soft": "#524C42",
        "--ink-mute": "#615B50",
        "--ink-faint": "#676156",
        "--rule": "rgba(38, 33, 25, 0.08)",
        "--rule-strong": "#DED8CA",
        "--rule-soft": "#EFECE4",
        "--numeral": "#C4BDAE",
        "--mark": "#A64B38",
        "--mark-bg": "#F6E6E1",
        "--accent": "#26221C",
        "--accent-fg": "#FAF8F3",
        "--btn-border": "#D5CEBF",
        "--outer-bg": "#E5E1D6",
        # S-10 段3a 方向 B：玻璃令牌（工单指定只增不改；值与 static/glass.css :root 一致，
        # 3g 工单第 1 条起卡片 .38 / 栏弹窗 .45——老板「卡片透明度放到 0.4 之下」）
        "--glass-bg": "rgba(255, 255, 255, 0.38)",
        "--glass-strong": "rgba(255, 255, 255, 0.45)",
        "--glass-border": "rgba(255, 255, 255, 0.70)",
        "--glass-blur": "18px",
        "--glass-shadow": "0 8px 32px rgba(40, 36, 28, 0.10)",
        "--glass-blob-a": "#D6AA8C",
        "--glass-blob-b": "#96B4AA",
        "--glass-blob-c": "#C8BED7",
    },
    "lingshu": {
        "name": "灵枢青瓷 · 松石绿 (对标竞品)",
        "--paper": "#F4F5F0",
        "--surface": "#FFFFFF",
        "--surface-subtle": "#F8FAF7",
        "--ink": "#1A2421",
        "--ink-solid": "#1D5B50",
        "--ink-soft": "#42544E",
        "--ink-mute": "#53635D",
        "--ink-faint": "#596961",
        "--rule": "rgba(29, 91, 80, 0.09)",
        "--rule-strong": "#D5DFDC",
        "--rule-soft": "#EBF0EE",
        "--numeral": "#B5C4BF",
        "--mark": "#1D5B50",
        "--mark-bg": "#E1F0EC",
        "--accent": "#1D5B50",
        "--accent-fg": "#FFFFFF",
        "--btn-border": "#C4D4CE",
        "--outer-bg": "#E2E7E4",
        "--glass-bg": "rgba(255, 255, 255, 0.38)",
        "--glass-strong": "rgba(255, 255, 255, 0.45)",
        "--glass-border": "rgba(255, 255, 255, 0.70)",
        "--glass-blur": "18px",
        "--glass-shadow": "0 8px 32px rgba(40, 36, 28, 0.10)",
        "--glass-blob-a": "#BFD3BC",
        "--glass-blob-b": "#9CC6B4",
        "--glass-blob-c": "#C6CBB8",
    },
    "parchment": {
        "name": "古籍羊皮 · 暖杏护眼",
        "--paper": "#F3ECD8",
        "--surface": "#FCF8EE",
        "--surface-subtle": "#F7F1E1",
        "--ink": "#2B2318",
        "--ink-solid": "#30271B",
        "--ink-soft": "#5E513F",
        "--ink-mute": "#655947",
        "--ink-faint": "#6B5F4A",
        "--rule": "rgba(48, 39, 27, 0.09)",
        "--rule-strong": "#DDD3BC",
        "--rule-soft": "#EAE1CC",
        "--numeral": "#BFB399",
        "--mark": "#9E4735",
        "--mark-bg": "#F2DCD4",
        "--accent": "#382B1E",
        "--accent-fg": "#FCF8EE",
        "--btn-border": "#C8B99E",
        "--outer-bg": "#DFD5BE",
        "--glass-bg": "rgba(255, 255, 255, 0.38)",
        "--glass-strong": "rgba(255, 255, 255, 0.45)",
        "--glass-border": "rgba(255, 255, 255, 0.70)",
        "--glass-blur": "18px",
        "--glass-shadow": "0 8px 32px rgba(40, 36, 28, 0.10)",
        "--glass-blob-a": "#DEC08E",
        "--glass-blob-b": "#C6B48E",
        "--glass-blob-c": "#D1BFA6",
    },
    "celadon": {
        "name": "宋刻竹青 · 润眼茶白",
        "--paper": "#EBF0EA",
        "--surface": "#F9FBF9",
        "--surface-subtle": "#F1F5F0",
        "--ink": "#1F2821",
        "--ink-solid": "#232D25",
        "--ink-soft": "#4A594D",
        "--ink-mute": "#546257",
        "--ink-faint": "#5A685C",
        "--rule": "rgba(35, 45, 37, 0.09)",
        "--rule-strong": "#CFDAD1",
        "--rule-soft": "#E1EAE2",
        "--numeral": "#B0C0B3",
        "--mark": "#8E4A3B",
        "--mark-bg": "#EFE0DC",
        "--accent": "#2B4738",
        "--accent-fg": "#F9FBF9",
        "--btn-border": "#B8C7BB",
        "--outer-bg": "#D8E2D9",
        "--glass-bg": "rgba(255, 255, 255, 0.38)",
        "--glass-strong": "rgba(255, 255, 255, 0.45)",
        "--glass-border": "rgba(255, 255, 255, 0.70)",
        "--glass-blur": "18px",
        "--glass-shadow": "0 8px 32px rgba(40, 36, 28, 0.10)",
        "--glass-blob-a": "#BCCFAE",
        "--glass-blob-b": "#A6C8B4",
        "--glass-blob-c": "#C9D0B6",
    },
    "stone": {
        "name": "澄心冷灰 · 碑拓质感",
        "--paper": "#EFECE6",
        "--surface": "#FAF9F6",
        "--surface-subtle": "#F4F2ED",
        "--ink": "#22201C",
        "--ink-solid": "#262420",
        "--ink-soft": "#54514B",
        "--ink-mute": "#605C54",
        "--ink-faint": "#66625C",
        "--rule": "rgba(38, 36, 32, 0.08)",
        "--rule-strong": "#D8D4CC",
        "--rule-soft": "#E6E2DA",
        "--numeral": "#BDB8AE",
        "--mark": "#964B3B",
        "--mark-bg": "#EFE0DC",
        "--accent": "#262420",
        "--accent-fg": "#FAF9F6",
        "--btn-border": "#C4BFB5",
        "--outer-bg": "#DAD6CE",
        "--glass-bg": "rgba(255, 255, 255, 0.38)",
        "--glass-strong": "rgba(255, 255, 255, 0.45)",
        "--glass-border": "rgba(255, 255, 255, 0.70)",
        "--glass-blur": "18px",
        "--glass-shadow": "0 8px 32px rgba(40, 36, 28, 0.10)",
        "--glass-blob-a": "#C9C0B4",
        "--glass-blob-b": "#B7BFC4",
        "--glass-blob-c": "#CBBFC8",
    },
    "pure": {
        "name": "素练极简 · 现代纯白",
        "--paper": "#F6F7F9",
        "--surface": "#FFFFFF",
        "--surface-subtle": "#F9FAFB",
        "--ink": "#111827",
        "--ink-solid": "#1E293B",
        "--ink-soft": "#4B5563",
        "--ink-mute": "#545B68",
        "--ink-faint": "#626A78",
        "--rule": "rgba(17, 24, 39, 0.07)",
        "--rule-strong": "#E5E7EB",
        "--rule-soft": "#F3F4F6",
        "--numeral": "#CBD5E1",
        "--mark": "#B93829",
        "--mark-bg": "#FEE2E2",
        "--accent": "#18181B",
        "--accent-fg": "#FFFFFF",
        "--btn-border": "#D1D5DB",
        "--outer-bg": "#E5E7EB",
        "--glass-bg": "rgba(255, 255, 255, 0.38)",
        "--glass-strong": "rgba(255, 255, 255, 0.45)",
        "--glass-border": "rgba(255, 255, 255, 0.70)",
        "--glass-blur": "18px",
        "--glass-shadow": "0 8px 32px rgba(40, 36, 28, 0.10)",
        "--glass-blob-a": "#CFD9E4",
        "--glass-blob-b": "#CAD4CC",
        "--glass-blob-c": "#DCD8E4",
    },
    "dark": {
        "name": "玄墨夜读 · 暗色纸感",
        "--paper": "#181614",
        "--surface": "#221F1C",
        "--surface-subtle": "#282420",
        "--ink": "#DDD5C7",
        "--ink-solid": "#E8E0D2",
        "--ink-soft": "#B0A797",
        "--ink-mute": "#948B7C",
        "--ink-faint": "#948B7C",
        "--rule": "rgba(255, 248, 235, 0.08)",
        "--rule-strong": "#36312A",
        "--rule-soft": "#2C2822",
        "--numeral": "#4A4339",
        "--mark": "#D47660",
        "--mark-bg": "#38221C",
        "--accent": "#D47660",
        "--accent-fg": "#181614",
        "--btn-border": "#484138",
        "--outer-bg": "#0F0E0C",
        "--glass-bg": "rgba(34, 31, 28, 0.38)",
        "--glass-strong": "rgba(30, 28, 26, 0.45)",
        "--glass-border": "rgba(255, 255, 255, 0.10)",
        "--glass-blur": "18px",
        "--glass-shadow": "0 8px 32px rgba(0, 0, 0, 0.35)",
        "--glass-blob-a": "#A05A3C",
        "--glass-blob-b": "#325A50",
        "--glass-blob-c": "#463C64",
    },
}


def _extract_json_between(source: str, begin: str, end: str) -> dict:
    match = re.search(re.escape(begin) + r"(.*?)" + re.escape(end), source, re.S)
    assert match, f"shell.js 缺少标记 {begin}"
    return json.loads(match.group(1))


def _load_shell_js() -> str:
    return (STATIC / "shell.js").read_text(encoding="utf-8")


def test_theme_presets_match_reference_exactly():
    shell = _load_shell_js()
    actual = _extract_json_between(shell, "/*S1-THEME-BEGIN*/", "/*S1-THEME-END*/")
    assert set(actual) == set(EXPECTED_THEME_PRESETS), "主题键必须恰为七套预设"
    for key, expected in EXPECTED_THEME_PRESETS.items():
        assert actual[key] == expected, f"主题 {key} 与规范 v2.0 不一致"


def test_wallpaper_presets_match_reference_exactly():
    shell = _load_shell_js()
    actual = _extract_json_between(shell, "/*S1-WALLPAPER-BEGIN*/", "/*S1-WALLPAPER-END*/")
    assert set(actual) == {"none", "xuan", "mist", "bamboo"}
    assert actual["none"] == "none"
    for key in ("xuan", "mist", "bamboo"):
        value = actual[key]
        assert value.startswith('url("data:image/svg+xml,') and value.endswith('")'), (
            f"纹理 {key} 必须是内嵌 SVG data URI（免外链）"
        )


def test_paper_css_root_defaults_equal_default_preset():
    css = (STATIC / "biyu-paper.css").read_text(encoding="utf-8")
    root_match = re.search(r":root\{(.*?)\}", css, re.S)
    assert root_match, "biyu-paper.css 必须有 :root 令牌块"
    root_block = root_match.group(1)
    defined: dict[str, str] = {}
    for raw in root_block.split(";"):
        raw = raw.strip()
        if raw.startswith("--"):
            name, _, value = raw.partition(":")
            defined[name.strip()] = value.strip()
    for token in TOKEN_KEYS:
        expected = EXPECTED_THEME_PRESETS["default"][token]
        assert defined.get(token) == expected, f":root 令牌 {token} 应为 {expected}"
    assert defined.get("--bg-image") == "none"
    assert defined.get("--bg-overlay-alpha") == "0.90"
    assert defined.get("--bg-blur") == "0px"
    assert defined.get("--display-font") == "var(--serif)"


def test_safe_color_tokens_exactly_five():
    """REQ-2：只许暴露五个安全令牌的取色入口，语义状态色不得出现。"""
    shell = _load_shell_js()
    match = re.search(
        r"/\*S1-SAFE-TOKENS-BEGIN\*/\s*(\[[^\]]*\])\s*/\*S1-SAFE-TOKENS-END\*/", shell
    )
    assert match, "shell.js 缺少 S1-SAFE-TOKENS 标记"
    safe = json.loads(match.group(1))
    assert safe == ["--paper", "--surface", "--ink", "--mark", "--mark-bg"]
    for forbidden in ("--ok", "--amber", "--rule", "--accent"):
        assert forbidden not in safe
