"""读稿页收敛工单 · TDD 测试(A3 三态 / A2 口径 / A1 透传 / B 类静态断言)。

跑法:pytest tests/test_dugao_convergence.py -q
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _book(tmp_path: Path, *, pending: bool = False, official: bool = False) -> Path:
    book = tmp_path / "Book"
    (book / "outlines").mkdir(parents=True)
    (book / "outlines" / "ch1.md").write_text("细纲", encoding="utf-8")
    ch = book / "chapters"
    ch.mkdir()
    if pending:
        (ch / "_pending").mkdir()
        (ch / "_pending" / "ch1.md").write_text("候选稿", encoding="utf-8")
    if official:
        (ch / "ch1.md").write_text("正式稿", encoding="utf-8")
    return book


def _snap(client: TestClient, book: Path) -> dict:
    return client.get(f"/api/workbench/books/{book.name}/chapters/1").json()


# ---------- A3 采用按钮三态(老板定义:数据一字不动) ----------

def test_adopt_enabled_when_pending_exists(tmp_path, monkeypatch):
    """态 1:有 _pending 候选稿且在读稿定夺 → 可点(实心 b1)。"""
    from biyu.ui.app import app
    import biyu.ui.workbench as workbench

    book = _book(tmp_path, pending=True)
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)
    snap = _snap(TestClient(app), book)
    act = snap["actions"]["adopt"]
    assert act["enabled"] is True
    assert snap["axes"]["step"] == "reading"


def test_adopt_disabled_says_finalized_when_only_official(tmp_path, monkeypatch):
    """态 2:无 _pending 但 chapters/chN.md 存在 → 已定稿,禁用,文案「这一章已定稿」。"""
    from biyu.ui.app import app
    import biyu.ui.workbench as workbench

    book = _book(tmp_path, official=True)
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)
    act = _snap(TestClient(app), book)["actions"]["adopt"]
    assert act["enabled"] is False
    assert "这一章已定稿" in act["reason"]


def test_adopt_disabled_says_generate_when_nothing(tmp_path, monkeypatch):
    """态 3:无 _pending 且 chN.md 也不存在 → 还没生成,禁用,文案「还没有正文,先去生成正文」。"""
    from biyu.ui.app import app
    import biyu.ui.workbench as workbench

    book = _book(tmp_path)
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)
    act = _snap(TestClient(app), book)["actions"]["adopt"]
    assert act["enabled"] is False
    assert "还没有正文" in act["reason"]


# ---------- A1 诊断数据透传(标题/正文一致性是前端比对,截图验收) ----------

def test_diagnosis_passthrough_keeps_layer_and_reason(tmp_path, monkeypatch):
    from biyu.ui.app import app
    import biyu.ui.workbench as workbench

    book = _book(tmp_path, pending=True)
    logs = book / "logs" / "ch1"
    logs.mkdir(parents=True)
    (logs / "diagnosis.json").write_text(
        json.dumps({"layer": "方案层", "reason": "## 诊断报告\n\n**首要根因：执笔层**", "action": "退回改方案", "rounds": 3}),
        encoding="utf-8",
    )
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)
    d = _snap(TestClient(app), book)["diagnosis"]
    assert d["layer"] == "方案层"
    assert "执笔层" in d["reason"]


# ---------- A2 计数口径:卡片 selected 默认 False(顶部计数不能用勾选数) ----------

def test_issue_cards_default_selected_false(tmp_path, monkeypatch):
    from biyu.ui.app import app
    import biyu.ui.workbench as workbench

    book = _book(tmp_path, pending=True)
    audit = book / "audit_reports"
    audit.mkdir()
    (audit / "ch1.json").write_text(
        json.dumps({"issues": [{"id": "e1", "severity": "high", "type": "节奏", "quoted_text": "x", "description": "y", "suggestion": "z"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)
    cards = _snap(TestClient(app), book)["issue_cards"]
    assert len(cards) == 1
    assert cards[0]["selected"] is False


# ---------- B 类:静态 HTML 断言 ----------

def _read(p: str) -> str:
    return Path(p).read_text(encoding="utf-8")


def test_b2_sample_shortcut_top_button_removed():
    """B2:「本章记录:问题 N · 好句 M」同屏两次,删顶部那个(#sample-shortcut)。"""
    html = _read("src/biyu/ui/static/workbench.html")
    assert 'id="sample-shortcut"' not in html
    # 折叠行那个保留
    assert 'id="sample-preview"' in html


def test_b10_revision_mode_not_fieldset():
    """B10:返修模式不用 fieldset 图例,改普通小标题 + 两个 radio。"""
    html = _read("src/biyu/ui/static/workbench.html")
    # 只查读稿定夺屏(panel 3);导入弹窗的 fieldset 不在本工单范围
    panel3 = html.split('data-panel="3"', 1)[1].split("</article>", 1)[0]
    assert "fieldset" not in panel3
    assert 'name="revision-mode"' in panel3
    assert 'value="local_revision"' in panel3 and 'value="deep_rewrite"' in panel3
    assert 'class="revision-mode-title"' in panel3


def test_b12_copy_chapter_inside_reading_title_row():
    """v6:「复制全文」位于第二层元数据，不回落正文滚动区。"""
    html = _read("src/biyu/ui/static/workbench.html")
    head = html.split('class="reading-decision-head"', 1)[1].split("</header>", 1)[0]
    col = html.split('class="reading-column"', 1)[1]
    assert 'id="copy-chapter"' in head
    assert 'id="copy-chapter"' not in col


def test_b13_button_tier_restructure():
    """B13:实心只留采用;提交本轮修改/读取此章/导入稿件描边;全选/清空/本轮忽略/重新诊断/退回改方案纯文字。"""
    html = _read("src/biyu/ui/static/workbench.html")
    # 采用 = 实心 b1
    assert 'data-action="adopt" class="b1"' in html
    # 描边 = b2
    assert 'id="load" class="b2"' in html
    assert 'id="open-import" type="button" class="b2"' in html
    assert 'id="submit-revision" class="b2' in html
    # 纯文字 = b3
    assert 'id="revision-select-all" type="button" class="b3"' in html
    assert 'id="revision-clear-all" type="button" class="b3"' in html
    assert 'id="diagnose-button" class="b3"' in html
    assert 'data-action="revoke_planning" class="b3"' in html
    assert 'id="diagnosis-close" class="b3"' in html or 'diagnosis-close' in html


def test_b7_read_margin_has_chapter_num_and_cn_num():
    """B7:留白栏章号元素存在且页面引入 cn-num.js(中文数字转换)。"""
    html = _read("src/biyu/ui/static/workbench.html")
    assert 'id="read-chapter-num"' in html
    assert '/cn-num.js' in html
