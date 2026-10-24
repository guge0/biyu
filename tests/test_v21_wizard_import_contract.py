"""S-3 T4 · 开书向导/三合一导入/设置联系区契约(决策6A/6B、#7/#16–#25 分流)。"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import HTTPException

from biyu.ui.legacy_migrate import _find_legacy_books
from biyu.ui.wizard import (
    _extract_json,
    _generate_premise,
    wizard_create_book,
)
from biyu.ui.wizard import CreateFromPremiseRequest

STATIC = Path(__file__).resolve().parents[1] / "src" / "biyu" / "ui" / "static"


def _src(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


# ---------- 屏2 开书向导 ----------

def test_wizard_page_three_steps_skeleton() -> None:
    html = _src("wizard.html")
    assert 'id="wizard-step1"' in html and 'id="wizard-step2"' in html and 'id="wizard-step3"' in html
    assert "一句话核心脑洞" in html
    for sample in ("社恐死亡回溯", "钦天监伪造节气", "义体医生解剖记忆"):
        assert sample in html
    for tier in ("短 · 约 2,000", "标准 · 约 3,000", "长 · 约 4,000"):
        assert tier in html
    # 决策5:手动建书双入口
    assert "跳过 AI，手动建空白书" in html and "手动建书（不调模型）" in html
    # REQ-W1:失败不建残书文案
    assert "没有在磁盘上建立残缺空书目录" in html
    assert "重抽一版立项" in html and "候选" in html


def test_wizard_js_flow_contract() -> None:
    js = _src("wizard.js")
    assert "/api/wizard/premise" in js and "/api/wizard/books" in js
    assert "/api/books" in js  # 手动建书走既有建书接口
    assert "就这样，开写第一章" in js


def test_wizard_extract_json_variants() -> None:
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('前缀 {"titles": ["x"]} 后缀')["titles"] == ["x"]


def test_wizard_premise_with_fake_adapter(monkeypatch) -> None:
    import asyncio

    class FakeResp:
        text = json.dumps({
            "titles": ["甲", "乙", "丙"], "summary": "一句话",
            "worldview": ["设定一", "设定二"], "protagonist": "张三 · 主角",
            "vol1": "第一卷方向",
        }, ensure_ascii=False)
        cost = 0.0

    class FakeAdapter:
        async def generate(self, messages, **kwargs):
            return FakeResp()

    class FakeRegistry:
        def get_adapter_for_stage(self, stage, override=None):
            return FakeAdapter()

    import biyu.ui.wizard as wizard_mod
    monkeypatch.setattr(
        "biyu.config.get_registry", lambda: FakeRegistry(), raising=True,
    )
    result = asyncio.run(_generate_premise("想法", ""))
    assert result["titles"] == ["甲", "乙", "丙"]
    assert len(result["worldview"]) == 2


def test_wizard_create_book_fills_assets_and_rolls_back(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIYU_DATA_ROOT", str(tmp_path))
    from biyu.config import get_data_root

    get_data_root.cache_clear() if hasattr(get_data_root, "cache_clear") else None
    request = CreateFromPremiseRequest(
        title="测试开书", genre="悬疑智斗", summary="北极星一句话",
        worldview="硬设定A\n硬设定B", protagonist="李四 · 冷面捕快", vol1="第一卷",
    )
    out = wizard_create_book(request)
    assert out["ok"] is True
    book_dir = tmp_path / out["id"]
    assert (book_dir / "北极星.md").exists() or (book_dir / "north_star.md").exists()
    meta = json.loads((book_dir / "book.json").read_text(encoding="utf-8"))
    assert meta["genre"] == "xuanyi"
    import yaml

    wb = yaml.safe_load((book_dir / "worldbook.yaml").read_text(encoding="utf-8"))
    assert wb["facts"] == ["硬设定A", "硬设定B"]
    chars = yaml.safe_load((book_dir / "characters.yaml").read_text(encoding="utf-8"))["characters"]
    assert any(c["tier"] == "protagonist" for c in chars)

    # REQ-W1 门:空书名/空北极星 → 400,磁盘不留任何目录(建书只发生在校验全过后)
    empty_title = CreateFromPremiseRequest(title="  ", genre="", summary="x")
    try:
        wizard_create_book(empty_title)
        raise AssertionError("空书名应 400")
    except HTTPException as exc:
        assert exc.status_code == 400
    empty_summary = CreateFromPremiseRequest(title="坏书", genre="", summary=" ")
    try:
        wizard_create_book(empty_summary)
        raise AssertionError("空北极星应 400")
    except HTTPException as exc:
        assert exc.status_code == 400
    leftovers = [p.name for p in tmp_path.iterdir() if p.is_dir() and not p.name.startswith(".")]
    assert leftovers == [out["id"]]


# ---------- 决策6B 三合一导入 ----------

def test_shell_import_wizard_contract() -> None:
    shell = _src("shell.js")
    assert "导入向导" in shell
    for tab in ("① 粘贴正文", "② 本地 .txt/.md 批量", "③ 旧版 biyu 数据根迁移"):
        assert tab in shell
    assert "/api/migrate/legacy/scan" in shell and "/api/migrate/legacy/commit" in shell
    assert "/imports/preview" in shell and "biyu-import-wizard-trigger" in shell
    assert "作为候选稿" in shell and "作为正式稿" in shell  # 身份必选
    html = _src("index.html")
    assert 'biyu-import-wizard-trigger' in html


def test_legacy_migrate_scan_commit(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIYU_DATA_ROOT", str(tmp_path / "target"))
    (tmp_path / "target").mkdir()
    source = tmp_path / "oldroot"
    book_a = source / "book-a"
    book_a.mkdir(parents=True)
    (book_a / "book.json").write_text('{"title": "旧书A"}', encoding="utf-8")
    (book_a / "chapters").mkdir()
    (book_a / "chapters" / "ch1.md").write_text("第一章", encoding="utf-8")
    (source / "not-a-book").mkdir()

    books = _find_legacy_books(source)
    assert [b["id"] for b in books] == ["book-a"]
    assert books[0]["chapter_count"] == 1

    from biyu.ui.legacy_migrate import legacy_commit
    from biyu.ui.legacy_migrate import CommitRequest

    out = legacy_commit(CommitRequest(source_root=str(source), ids=["book-a"]))
    assert out["ok"] is True
    assert (tmp_path / "target" / "book-a" / "chapters" / "ch1.md").exists()
    assert (book_a / "chapters" / "ch1.md").exists()  # 源目录不动

    # 重名迁移 → -2 后缀
    out2 = legacy_commit(CommitRequest(source_root=str(source), ids=["book-a"]))
    assert out2["imported"][0]["id"] == "book-a-2"


# ---------- 决策6A 设置页联系区 ----------

def test_settings_contact_card() -> None:
    html = _src("settings.html")
    assert 'id="contact-card"' in html
    assert "892467108" in html and "feedback@biyu.studio" in html
    assert "复制 Q 群号" in html and "提交问题与建议" in html
    js = _src("settings.js")
    assert "contact-copy-group" in js
