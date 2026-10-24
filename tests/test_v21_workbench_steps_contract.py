"""S-3 T5 批1 · 工作台五步结构契约（图纸五步 Stepper + 一页两级 + ①②前置步 + 草稿闸）。

锚点:#74 五步阶段条(①设定→⑤读稿) / 决策2 契约一页两级(面板0+1 同屏) /
决策3 AI 草稿闸 / #81-82 书级两格+扩写续写 / #70-73 评章区并入⑤读稿 /
#90 设定集内嵌(?embed=1)。交互行为由真实起服务走查取证。
"""
from __future__ import annotations

from pathlib import Path

import fastapi
from fastapi.testclient import TestClient

STATIC = Path(__file__).resolve().parents[1] / "src" / "biyu" / "ui" / "static"


def _src(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_workbench_five_step_stepper() -> None:
    """#74:五步 Stepper ①设定 ②大纲 ③细纲 ④写章与保真闸 ⑤读稿。"""
    js = _src("workbench.js")
    assert "DISPLAY_STEPS" in js
    for label in ("设定", "大纲", "细纲", "写章与保真闸", "读稿"):
        assert label in js
    assert "displayKeyForStage" in js and "showPrepStep" in js
    # 后端 stage 语义未动:数字阶段常量仍在
    assert "STAGES = ['细纲', '写作方案', '生成正文', '读稿定夺', '评章摘句']" in js


def test_contract_page_one_page_two_tiers() -> None:
    """决策2:③细纲=一页两级——面板0+1 同屏且带两级徽章。"""
    js = _src("workbench.js")
    assert "key === '0' || key === '1'" in js
    html = _src("workbench.html")
    assert "第一级 · 作者细纲（本章本意）" in html
    assert "第二级 · 导演执行方案（保真闸核对准绳）" in html
    assert 'data-panel="1"' in html


def test_setting_step_embeds_settings() -> None:
    """#90:①设定步内嵌 settings 页(?embed=1),壳在嵌入态只保留主题。"""
    html = _src("workbench.html")
    assert 'data-panel="setting"' in html and 'id="setting-embed"' in html
    assert "embed=1" in _src("workbench.js")
    shell = _src("shell.js")
    assert "biyu-embedded" in shell and "embed') === '1'" in shell
    css = _src("biyu-paper.css")
    assert "body.biyu-embedded .margin-col" in css


def test_outline_step_cells_and_draft_gate() -> None:
    """#81/#82/决策3:②大纲=书级两格 + AI 扩写/续写草稿闸(批准才落盘)。"""
    js = _src("workbench.js")
    assert "north_star" in js and "book_outline" in js
    assert "扩写大纲" in js and "续写后卷" in js and "帮我补全" in js
    assert "AI 起草待审稿" in js and "批准并追加合入" in js and "放弃草稿" in js
    assert "/cells/" in js  # 保存走既有 PUT 链(版本 409 保护)


def test_review_summary_folded_into_reading_step() -> None:
    """#70-73:评章摘句与归档收尾并入⑤读稿页,独立面板4退役。"""
    html = _src("workbench.html")
    assert 'id="review-summary"' in html and "评章摘句与归档收尾" in html
    assert 'data-panel="4"' not in html
    js = _src("workbench.js")
    assert "n <= 1 ? 'contract' : n === 2 ? 'write' : 'read'" in js  # stage4 归入 read


def test_cell_draft_endpoint_registered() -> None:
    """决策3 后端:草稿闸端点挂载且只读既有格内容。"""
    from biyu.ui.cell_draft import router

    paths = {getattr(r, "path", "") for r in router.routes}
    assert any("draft" in p for p in paths)
    src = Path(__file__).resolve().parents[1] / "src" / "biyu" / "ui" / "cell_draft.py"
    text = src.read_text(encoding="utf-8")
    assert "_DRAFTABLE" in text
    for cell in ("north_star", "book_outline", "world_facts"):
        assert cell in text
