"""S-3 T6 · 周边屏契约(#94–#108、#110 图纸落位补齐项)。"""
from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "biyu" / "ui" / "static"


def _src(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_overview_matrix_view() -> None:
    """#101/#104:章节方阵 + 双视图切换(默认方阵)。"""
    html = _src("overview.html")
    assert 'id="matrix-view"' in html and "matrix-grid" in html
    assert 'id="view-matrix-btn"' in html and 'id="view-list-btn"' in html
    assert "章节方阵" in html and "分档列表" in html
    js = _src("overview.js")
    assert "renderMatrix" in js and "setOverviewView" in js
    for kind in ("mc-need", "mc-note", "mc-done"):
        assert kind in js
    css = _src("overview.css")
    assert ".matrix-cell" in css and ".mc-need" in css


def test_good_sentences_distill_entry() -> None:
    """#108:去蒸馏声纹快捷入口,带当前书跳声纹页。"""
    html = _src("good-sentences.html")
    assert 'id="distill-voiceprint-link"' in html and "去蒸馏声纹 →" in html
    js = _src("good-sentences.js")
    assert "distill-voiceprint-link" in js and "voiceprint.html?book=" in js


def test_settings_contact_card_kept() -> None:
    """决策6A 回归:设置页联系名片卡仍在(壳内嵌也可见)。"""
    html = _src("settings.html")
    assert 'id="contact-card"' in html
