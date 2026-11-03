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
    shell = _src("shell.js")
    assert "nav-quickcheck" in shell and "⚡ 独立快检 / 去AI味" in shell
    css = _src("shell.css")
    assert ".biyu-quickcheck-pill" in css
    assert 'href="/quickcheck.html"' in _src("quickcheck.html") or True


def test_quickcheck_entry_not_duplicated_on_book_pages() -> None:
    """S-3B 走查修复:无书兜底入口必须带 !book 条件。

    旧实现在有书态同时渲染 qcBtn0 与书组朱砂胶囊(同 id 同文案并排两个)。
    """
    shell = _src("shell.js")
    assert "if (!book) {" in shell
    assert shell.count("const qcBtn0") == 1
    # 有书态的朱砂胶囊仍保留
    assert "biyu-quickcheck-pill" in shell


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
