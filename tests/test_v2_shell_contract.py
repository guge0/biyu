"""S-1 全局壳静态契约：壳资产接线、导航分组、引擎常量与降级路径。

服务端行为见 test_ui_appearance.py；令牌零差异见 test_v2_theme_tokens.py；
本文件钉住「每页都接壳、壳只有规定导航项、护栏常量在位」的结构事实，
前端交互行为由真实起服务走查取证（design.md 预案：无 JS 测试基建）。
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "biyu" / "ui" / "static"

AUTHOR_PAGES = (
    "index.html", "book.html", "workbench.html", "settings.html",
    "voiceprint.html", "overview.html", "good-sentences.html", "memory.html",
    "editor.html", "trash.html", "prompts.html", "propose.html",
    "preferences.html", "summaries.html",
)


def _src(page: str) -> str:
    return (STATIC / page).read_text(encoding="utf-8")


def test_shell_assets_wired_on_every_author_visible_page():
    for page in AUTHOR_PAGES:
        html = _src(page)
        assert '/shell.css?v=' in html, f"{page} 缺 shell.css"
        assert '/shell.js?v=' in html, f"{page} 缺 shell.js"
        assert '/biyu-paper.css?v=' in html, f"{page} 缺 biyu-paper.css"
        paper_at = html.index('/biyu-paper.css?v=')
        shell_at = html.index('/shell.css?v=')
        assert paper_at < shell_at, f"{page}: shell.css 必须在 biyu-paper.css 之后"
        if '/styles.css?v=' in html:
            styles_at = html.index('/styles.css?v=')
            last_styles_at = html.rindex('/styles.css?v=')
            assert last_styles_at < paper_at, (
                f"{page}: biyu-paper.css 必须是最后的令牌定义层（styles.css 不得再出现于其后）"
            )
            assert styles_at > 0


def test_shell_js_renders_exactly_the_spec_nav_groups():
    shell = _src("shell.js")
    for required in (
        "书架", "抽卡模式", "外观与背景", "设置",
        "全书概览", "声纹", "好句", "回收站",
        "本地自动落盘", "笔驭",
    ):
        assert required in shell, f"shell.js 缺导航组元素：{required}"


def test_shell_js_takes_over_legacy_nav():
    shell = _src("shell.js")
    assert "nav.top-nav" in shell
    assert "style.display = 'none'" in shell or "style.display='none'" in shell


def test_shell_engine_guards_match_spec():
    shell = _src("shell.js")
    # REQ-3 滑杆范围：蒙层 65-98、柔焦 0-20
    overlay = re.search(r"const OVERLAY = \{[^}]*\}", shell)
    blur = re.search(r"const BLUR = \{[^}]*\}", shell)
    assert overlay and "min: 65" in overlay.group(0) and "max: 98" in overlay.group(0)
    assert "uploadAuto: 82" in overlay.group(0), "上传后自动蒙层必须为 82%"
    assert blur and "min: 0" in blur.group(0) and "max: 20" in blur.group(0)
    # REQ-1 反向：未知主题键回落默认
    assert "THEME_PRESETS[raw] ? raw : 'default'" in shell
    # REQ-3 反向：非图片提示
    assert "仅支持图片" in shell
    # REQ-2 豁免：重置入口
    assert "恢复默认" in shell
    # REQ-3 降级：custom 背景缺文件回落 none
    assert "state.background.type = 'none'" in shell
    # REQ-4 反向：无书时书名与二级胶囊不渲染
    assert "if (book)" in shell


def test_no_cdn_font_references_anywhere():
    for asset in list(STATIC.glob("*.html")) + [STATIC / "shell.js", STATIC / "biyu-paper.css", STATIC / "shell.css"]:
        text = asset.read_text(encoding="utf-8")
        assert "fonts.googleapis" not in text, f"{asset.name} 引用了 Google CDN"
        assert "fonts.gstatic" not in text, f"{asset.name} 引用了 gstatic CDN"


def test_index_bookshelf_is_v2():
    html = _src("index.html")
    assert "page-title" in html
    assert "我的书架" in html
    assert "empty-state" in html
    assert "新建第一部作品" in html
    assert 'id="settings-entry"' in html
    assert 'id="create-book-empty-button"' in html
    # 旧导航契约锚点保留（运行时由壳接管，见 test_runtime_navigation）
    assert 'class="top-nav"' in html


def test_app_js_book_card_hides_missing_fields():
    app_js = _src("app.js")
    # 书卡不再渲染字数/花费/更新时间占位
    assert "累计" not in app_js.split("function renderBookCard")[1].split("function renderContinue")[0]
    assert "card book-card" in app_js
    assert "book-cover-char" in app_js
