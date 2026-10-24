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


# ---------- S-3 T5 批2:#35 左栏契约 / #53 决策7 词族雷达 ----------

def test_write_step_split_contract_panel() -> None:
    """#35:④写章双栏——左栏 sticky 契约面板,右栏工具与生成。"""
    html = _src("workbench.html")
    assert 'class="workbench-split-grid"' in html
    assert 'id="write-contract-panel"' in html
    assert "本章写作契约" in html
    assert "④ 写章与保真闸" in html
    js = _src("workbench.js")
    assert "renderWriteContractPanel" in js
    css = _src("biyu-paper.css")
    assert ".contract-panel" in css and ".workbench-split-grid" in css


def test_auditor_radar_card_in_reading_step() -> None:
    """#53/决策7:⑤读稿右栏置顶 Auditor 词族密度雷达(进度条+点击)。"""
    html = _src("workbench.html")
    assert 'id="auditor-radar"' in html and "auditor-radar-card" in html
    assert "AI 味与词族密度体检 (Auditor)" in html
    js = _src("workbench.js")
    assert "renderAuditorRadar" in js and "auditor_density" in js
    for key in ("simile_markers", "tic_words", "cliche_expressions"):
        assert key in js
    css = _src("biyu-paper.css")
    assert ".auditor-radar-card" in css and ".density-bar-fill" in css


def test_auditor_density_snapshot_field(tmp_path, monkeypatch) -> None:
    """快照新增字段 auditor_density:超标候选稿三词族密度齐全。"""
    from biyu.ui.workbench import _auditor_density

    report = tmp_path / "ch4.json"
    report.write_text('{"results": [{"checker": "style_repeat", "severity": "WARN", '
                      '"details": {"density": {"simile_markers": {"count": 9, "per_kchar": 9.0, "limit": 3.0}}, '
                      '"density_violations": ["『明喻』密度 9.0/千字"]}}]}', encoding="utf-8")
    out = _auditor_density(report)
    assert out["severity"] == "WARN"
    assert out["density"]["simile_markers"]["per_kchar"] == 9.0
    assert len(out["violations"]) == 1
    missing = tmp_path / "none.json"
    assert _auditor_density(missing) is None
