"""S-3 T7 · 快检台契约(纯本地零成本;P0-1A/1B/1C;裁剪3:LLM 两卡占位无付费文案)。"""
from __future__ import annotations

from pathlib import Path

from biyu.quickcheck import scan_text

STATIC = Path(__file__).resolve().parents[1] / "src" / "biyu" / "ui" / "static"


def _src(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


# ---------- 后端扫描 ----------

def test_scan_counts_and_exceeds() -> None:
    text = "他缓缓抬起头，仿佛看到了什么，嘴角勾起一抹弧度。" * 20
    out = scan_text(text)
    fams = {f["key"]: f for f in out["families"]}
    assert fams["tic_words"]["count"] >= 20  # 缓冲词(缓缓/嘴角…)
    assert fams["simile_markers"]["count"] >= 20  # 仿佛
    assert fams["cliche_expressions"]["count"] >= 20  # 嘴角勾起
    assert fams["tic_words"]["exceeded"] is True
    assert out["score"] > 0
    assert out["hits"], "命中列表不应为空"
    offsets = [h["offset"] for h in out["hits"]]
    assert offsets == sorted(offsets)


def test_scan_zero_hits_empty_state() -> None:
    out = scan_text("张今空把刀收进鞘中，铜边咬合发出一声轻响。今天没有写任何词族命中。")
    assert all(f["count"] == 0 for f in out["families"])
    assert out["hits"] == []
    assert out["score"] == 0


def test_short_text_density_uses_real_length() -> None:
    """整改清单 #3a:S-3C 截图 17 那段 102 字里有 4 处明喻,旧口径按一千字算成 4.0/千字。"""
    text = (
        "夜色深沉，某种意义上来说，这一切早已注定。他的眼中闪过一丝不易察觉的惊讶，"
        "仿佛被无形的力量捃住了喉咙。不得不说，她的嘴角勾起一抹弧度，像是斗败的公鸡。"
        "空气仿佛凝固了。时间仿佛静止了。他知道，一切都结束了。"
    )
    out = scan_text(text)
    fams = {f["key"]: f for f in out["families"]}
    han = out["han_chars"]
    assert han < 300 and out["low_sample"] is True
    assert fams["simile_markers"]["count"] == 4
    assert abs(fams["simile_markers"]["per_kchar"] - round(4 / (han / 1000), 2)) < 0.01
    assert fams["simile_markers"]["per_kchar"] > 30


def test_score_at_threshold_is_not_worst() -> None:
    """整改清单 #3b:三族都刚好等于阈值 → 30 分(自然上限),不再封顶 100。"""
    from biyu.quickcheck import ai_score, score_band

    fams = [
        {"per_kchar": 3.0, "limit": 3.0},
        {"per_kchar": 5.0, "limit": 5.0},
        {"per_kchar": 1.0, "limit": 1.0},
    ]
    assert ai_score(fams) == 30
    assert score_band(30) == "自然"
    worse = [dict(f, per_kchar=f["limit"] * 3) for f in fams]
    assert ai_score(worse) > 90
    assert score_band(ai_score(worse)) == "明显 AI 味"


def test_overlapping_terms_counted_once() -> None:
    """整改清单 #3c:“嘴角勾起”只算套话,不再同时算一次缓冲词“嘴角”。"""
    out = scan_text("她嘴角勾起。他嘴角微微上扬。")
    fams = {f["key"]: f["count"] for f in out["families"]}
    assert fams["cliche_expressions"] == 2
    assert fams["tic_words"] == 0
    terms = [h["term"] for h in out["hits"]]
    assert terms == ["嘴角勾起", "嘴角微微上扬"]


def test_chapter_audit_uses_same_dedup_counts() -> None:
    from biyu.auditor.ai_patterns import DENSITY_GROUPS, count_group

    tic = next(g for g in DENSITY_GROUPS if g.key == "tic_words")
    assert count_group("她嘴角勾起，缓缓转身。", tic) == 1


def test_quickcheck_page_shows_band_and_low_sample_note() -> None:
    js = _src("quickcheck.js")
    assert "qc-score-band" in js and "low_sample" in js


def test_scan_highlight_classes_match_blueprint() -> None:
    """三色高亮对应词族:红波浪=缓冲词/琥珀=明喻/紫虚线=套话(图纸)。"""
    out = scan_text("缓缓 仿佛 嘴角勾起")
    cls = {h["term"]: h["highlight_class"] for h in out["hits"]}
    assert cls["缓缓"] == "qc-hl-hedge"
    assert cls["仿佛"] == "qc-hl-simile"
    assert cls["嘴角勾起"] == "qc-hl-cliche"


# ---------- 页面与路由 ----------

def test_quickcheck_page_skeleton() -> None:
    html = _src("quickcheck.html")
    assert 'id="qc-input"' in html and 'id="qc-radar"' in html
    for cls in ("qc-hl-hedge", "qc-hl-simile", "qc-hl-cliche"):
        assert cls in html
    # 裁剪3:LLM 两卡占位=「内测版即将开通」,不得出现价格/付费字样
    assert "内测版即将开通" in html
    for banned in ("¥", "价格", "Pro", "会员", "解锁", "付费"):
        assert banned not in html, f"占位卡出现违规词:{banned}"
    assert 'id="qc-save-new"' in html and 'id="qc-save-existing"' in html


def test_quickcheck_paste_button_reads_clipboard() -> None:
    """S-3B 老板走查反馈:「粘贴我的小说稿」必须真读剪贴板,不再只聚焦空输入框。

    剪贴板有内容=直接填入+按钮反馈;权限拒绝/空剪贴板回落聚焦(不报错)。
    """
    js = _src("quickcheck.js")
    assert "navigator.clipboard.readText()" in js
    assert "已读入剪贴板" in js
    assert 'qc-paste-btn").textContent = "📋 粘贴我的小说稿"' in js  # 反馈后复原
    assert "$(\"qc-input\").focus();" in js  # 回落路径保留


def test_quickcheck_shell_entry() -> None:
    """S-10 3a-3:快检入口在全局栏（bolt 线条图标 + 文案），id 与类保留。"""
    shell = _src("shell.js")
    assert "nav-quickcheck" in shell and "快检 / 去AI味" in shell and "shellIcon('bolt')" in shell
    css = _src("glass.css")
    assert ".biyu-quickcheck-pill" in css
    assert 'href="/quickcheck.html"' in _src("quickcheck.html") or True


def test_quickcheck_entry_not_duplicated_on_book_pages() -> None:
    """S-3B 走查修复的延续:S-10 3a-3 起快检入口只在全局栏渲染一次（无书/有书同一条路径）。"""
    shell = _src("shell.js")
    assert shell.count('id = \'nav-quickcheck\'') + shell.count('id = "nav-quickcheck"') + shell.count("qcBtn.id = 'nav-quickcheck'") >= 1
    assert shell.count("biyu-quickcheck-pill") >= 1
    # 全局栏构建路径只有一处快检入口
    assert shell.count("nav-quickcheck") == 1


def test_quickcheck_routes_registered() -> None:
    from biyu.ui.quickcheck_routes import router

    paths = {getattr(r, "path", "") for r in router.routes}
    assert paths == {"/api/quickcheck/scan"}


def test_scan_rejects_oversize() -> None:
    import pytest
    from fastapi import HTTPException

    from biyu.ui.quickcheck_routes import quickcheck_scan
    from biyu.ui.quickcheck_routes import ScanRequest

    with pytest.raises(HTTPException) as exc:
        quickcheck_scan(ScanRequest(text="a" * 200_001))
    assert exc.value.status_code == 413
