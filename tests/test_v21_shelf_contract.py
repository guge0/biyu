"""S-3 T3 · 书架屏 V2.1 移植契约(图纸 reference/biyu_ai_v2.1.html)。

按自查表锚定:#1 书卡网格 / #2 徽章(含★示例书) / #3 主按钮三态 / #4 概览入口 /
#5 改名 / #6 回收站 / #7 双入口建书 / #8 续写条 / #9 版本徽章 / #10 数据根 /
#11 Key入口 / #12 备份 / #13 回收站胶囊(壳) / 决策5 手动建书 / 决策6A 联系区 /
P0-2A 迎宾笺条 / P0-2B 耕读历 / P0-2C 朱批钤印 / P0-2D 领 Key 锦囊。
前端交互行为由真实起服务走查取证(同 test_v2_shell_contract.py 口径)。
"""
from __future__ import annotations

import json
from pathlib import Path

from biyu.ui_seed.homestead import homestead_stats, seals_state
from biyu.ui_seed.sample_book import maybe_seed_sample_book

STATIC = Path(__file__).resolve().parents[1] / "src" / "biyu" / "ui" / "static"


def _src(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


# ---------- index.html 结构契约 ----------

def test_shelf_welcome_strip_skeleton() -> None:
    """P0-2A:迎宾笺条三去向(领Key锦囊/快检台/手动建书)+ 两态徽章位。"""
    html = _src("index.html")
    assert 'id="welcome-strip"' in html
    assert 'id="key-guide-button"' in html and "30 秒傻瓜式领 Key 锦囊" in html
    assert 'id="welcome-quickcheck-link"' in html and "免 Key 查 AI 味" in html
    assert 'id="welcome-manual-button"' in html
    assert 'id="welcome-mode-badge"' in html


def test_shelf_homestead_card_skeleton() -> None:
    """P0-2B:耕读历卡(连续天数/拦截统计/热力区/印章按钮/收起展开)。"""
    html = _src("index.html")
    assert 'id="homestead-card"' in html and "calendar-strip-card" in html
    assert 'id="homestead-streak"' in html and "连续耕读" in html
    assert 'id="homestead-intercepted"' in html and "累计拦截" in html
    assert 'id="homestead-heatmap"' in html and "近 14 日手稿热力" in html
    assert 'id="homestead-week-words"' in html
    assert 'id="seal-open-button"' in html and "朱批钤印 · 里程碑印章" in html
    assert 'id="homestead-toggle"' in html


def test_shelf_modals_skeleton() -> None:
    """P0-2C/P0-2D:领 Key 锦囊三渠道 + 朱批钤印立轴弹窗。"""
    html = _src("index.html")
    assert 'id="key-guide-overlay"' in html
    # S-7b：内测版三张卡改为写作 / 降 AI 率 / 体检实际用到的三家。
    for tab_text in ("DeepSeek（写作）", "智谱 GLM（降 AI 率 / 写作）", "朱雀（体检）"):
        assert tab_text in html
    assert 'id="key-guide-input"' in html and 'id="key-guide-save"' in html
    assert 'id="seals-overlay"' in html and 'id="seal-scroll"' in html
    assert "复制群晒单文案" in html and "保存纪念日签海报" in html


def test_shelf_toolbar_and_empty_state() -> None:
    """#7/#11/#12/决策5:顶栏工具行与空态三入口。"""
    html = _src("index.html")
    # S-10 3a-2：emoji 换线条 SVG，id 与入口保留
    assert 'id="import-works-button"' in html and "biyu-icon-import" in html  # 决策6B 入口(T4 接向导)
    assert 'id="manual-create-button"' in html and "手动建书" in html
    assert "书架是空的 · 说出一句话想法" in html
    assert 'id="create-book-empty-button"' in html
    assert 'id="manual-create-empty-button"' in html and "跳过 AI，手动建空白书" in html
    assert 'id="import-empty-link"' in html and "导入已有作品 / 旧版迁移" in html


# ---------- app.js 行为契约 ----------

def test_app_js_experience_layer() -> None:
    js = _src("app.js")
    # P0-2A 两态
    assert "免 Key 零门槛畅玩模式" in js and "已配 Key 直连" in js
    # 数据接口
    assert "/api/homestead/stats" in js and "/api/seals/state" in js
    assert "/api/setup/status" in js
    # P0-2B 热力格分级(图纸 cal-lv-0..3,运行时按 level 拼 class)
    assert '"cal-heatmap-cell cal-lv-" + day.level' in js
    # P0-2C 印章 SVG 与晒单/海报
    assert "cinnabar-seal-svg" in js and "复制群晒单文案" in js
    # P0-2D 三渠道步骤与保存走既有 setup
    assert "platform.deepseek.com" in js and "open.bigmodel.cn" in js and "/api/zhuque/key" in js
    assert "setup-overlay" in js


def test_app_js_book_card_contract() -> None:
    """#1-#6:书卡徽章(#2 含★示例书)、主按钮三态(#3)、更多菜单(#5/#17 设定集)。"""
    js = _src("app.js")
    assert "接着写" in js and "开始第 1 章" in js and "去填设定" in js
    assert "★ 预载示例书 · 免Key可玩" in js
    assert "设定集 (" in js and "/9格)" in js
    assert "移到回收站" in js
    assert "全书概览" in js


def test_book_more_menu_flips_upward_near_viewport_bottom() -> None:
    """S-3B 走查修复:书卡贴近视口底时更多菜单向上展开(应用壳页面不可滚动)。

    旧实现固定 top:calc(100% + 6px) 向下展开,最后一行书卡的菜单整条掉到
    视口外,只剩一条白边可见。
    """
    js = _src("app.js")
    assert "rect.bottom > window.innerHeight - 8" in js
    assert 'moreMenu.style.bottom = "calc(100% + 6px)"' in js


# ---------- 壳层联系区(决策6A) ----------

def test_shell_contact_pill() -> None:
    shell = _src("shell.js")
    assert "biyu-contact-pill" in shell
    assert "462502077" in shell
    assert "openContactFeedback" in shell
    css = _src("shell.css")
    assert ".biyu-contact-pill" in css


def test_paper_css_has_p0_components() -> None:
    css = _src("biyu-paper.css")
    for cls in (".welcome-strip", ".calendar-strip-card", ".cal-heatmap-cell",
                ".cal-lv-3", ".seal-scroll-box", ".cinnabar-seal-svg"):
        assert cls in css, f"biyu-paper.css 缺 {cls}"


# ---------- 耕读历/印章后端契约(T8 补降级与重算专项) ----------

def _seeded_root(tmp_path: Path) -> Path:
    root = tmp_path / "shelf"
    root.mkdir()
    out = maybe_seed_sample_book(root, enabled=True)
    assert out["action"] == "seeded", out
    return root


def test_homestead_stats_shape(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path)
    stats = homestead_stats(root)
    assert len(stats["heatmap"]) == 14
    assert all(set(day) >= {"date", "label", "words", "level"} for day in stats["heatmap"])
    assert all(0 <= day["level"] <= 3 for day in stats["heatmap"])
    # 种子书 3 定稿 + 1 候选当天落盘:今日有产出、批准 3 章
    assert stats["approved_chapters"] == 3
    assert stats["heatmap"][-1]["words"] > 0
    # 示例书候选稿触发 3 组词族超标(WARN) → 拦截计数 ≥ 3
    assert stats["intercepted_count"] >= 3


def test_homestead_stats_empty_root_degrades_to_zero(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    stats = homestead_stats(root)
    assert stats["streak_days"] == 0
    assert stats["week_words"] == 0
    assert stats["intercepted_count"] == 0
    assert stats["approved_chapters"] == 0


def test_seals_state_achievements(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path)
    seals = seals_state(root)
    keys = [s["key"] for s in seals["seals"]]
    assert keys == ["first_chapter", "ten_k", "hundred_k", "first_contract"]
    # 种子书 3 章定稿 → 首章印达成;契约未确认 → 契约印未达成
    by_key = {s["key"]: s for s in seals["seals"]}
    assert by_key["first_chapter"]["achieved"] is True
    assert by_key["first_contract"]["achieved"] is False
    assert 1 <= seals["achieved_count"] < len(seals["seals"])


def test_ui_seed_routes_registered() -> None:
    from biyu.ui.ui_seed_routes import router

    paths = {getattr(route, "path", "") for route in router.routes}
    assert paths == {"/api/homestead/stats", "/api/seals/state"}


# ---------- S-3 T8 · 耕读历/印章 删书降级与可重算专项 ----------

def test_homestead_degrades_gracefully_after_book_removal(tmp_path: Path) -> None:
    """spec 场景2:删除示例书后计数与卡仍工作(重算→零值/低值,不报错)。"""
    root = _seeded_root(tmp_path)
    before = homestead_stats(root)
    assert before["approved_chapters"] == 3

    # 模拟用户删书(受保护删除=移出书架目录);耕读历纯文件重算,无状态残留
    import shutil

    for book in list(root.iterdir()):
        if book.is_dir() and (book / "book.json").is_file():
            shutil.rmtree(book)
    after = homestead_stats(root)
    assert after["approved_chapters"] == 0
    assert after["streak_days"] == 0
    assert after["week_words"] == 0
    assert len(after["heatmap"]) == 14  # 热力格照常渲染(全 0)


def test_homestead_recomputes_from_files(tmp_path: Path) -> None:
    """数据可重算:直接改章节文件字数,统计随之变化(无缓存依赖)。"""
    root = _seeded_root(tmp_path)
    book = next(p for p in root.iterdir() if (p / "book.json").is_file())
    chapter = book / "chapters" / "ch1.md"
    chapter.write_text("一笔" * 600, encoding="utf-8")  # 1200 汉字
    stats = homestead_stats(root)
    today_heat = stats["heatmap"][-1]
    # 重写 ch1 后当日字数=新写1200+种子其余两章与候选稿;关键断言:数值随文件内容变化(可重算)
    assert today_heat["words"] > 1200
    assert today_heat["words"] != 898
    assert today_heat["level"] == 1  # 实测 1889 字 <2000 → lv1;分级口径与图纸 cal-lv 一致


def test_seals_state_degrades_after_book_removal(tmp_path: Path) -> None:
    root = _seeded_root(tmp_path)
    import shutil

    for book in list(root.iterdir()):
        if book.is_dir() and (book / "book.json").is_file():
            shutil.rmtree(book)
    seals = seals_state(root)
    assert seals["achieved_count"] == 0
    assert all(not s["achieved"] for s in seals["seals"])
    assert seals["finalized_words"] == 0
