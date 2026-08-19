from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _book(tmp_path: Path) -> Path:
    book = tmp_path / "demo"
    _write(book / "book.json", '{"title":"隔离书"}')
    _write(book / "chapters/_pending/ch1.md", "候选正文")
    for number in range(1, 4):
        root = book / f"logs/ch1/revisions/round_{number}"
        _write(root / "manifest.json", json.dumps({"round": number, "status": "complete"}))
        _write(root / "comments.md", "# 本轮作者意见\n\n压节奏\n\n## 逐条意见\n")
        _write(root / "issues.json", "[]")
        _write(root / "candidate.md", "候选正文")
    return book


class Adapter:
    def __init__(self, text: str):
        self.text = text

    async def generate(self, **kwargs):
        return SimpleNamespace(text=self.text, cost=0)


def test_layer_from_structured_field_only(tmp_path: Path) -> None:
    from biyu.ui.diagnosis import diagnose_chapter

    book = _book(tmp_path)
    text = json.dumps({
        "layer": "执笔层",
        "action": "继续修订",
        "reason": "细纲层和方案层均已核对，正式结论仍是执笔层。",
    }, ensure_ascii=False)
    result = asyncio.run(diagnose_chapter(book, 1, adapter=Adapter(text)))
    assert result["layer"] == "执笔层"


def test_conclusion_wins_over_mentions(tmp_path: Path) -> None:
    from biyu.ui.diagnosis import diagnose_chapter

    book = _book(tmp_path)
    result = asyncio.run(diagnose_chapter(book, 1, adapter=Adapter(
        '{"layer":"执笔层","action":"继续修订","reason":"论证核对过方案层与细纲层，问题仍在执笔。"}'
    )))
    assert result["layer"] == "执笔层"
    assert result["action"] == "继续修订"


def test_inconsistent_triple_fails_loud(tmp_path: Path) -> None:
    from biyu.ui.diagnosis import diagnose_chapter

    book = _book(tmp_path)
    with pytest.raises(RuntimeError, match="不一致"):
        asyncio.run(diagnose_chapter(book, 1, adapter=Adapter(
            '{"layer":"执笔层","action":"退回改方案","reason":"结论是执笔层。"}'
        )))
    assert not (book / "logs/ch1/diagnosis.json").exists()


def test_stale_diagnosis_blocks_routing(tmp_path: Path, monkeypatch) -> None:
    from biyu.ui import app as ui_app
    from biyu.ui import workbench
    from biyu.ui.diagnosis import candidate_sha

    book = _book(tmp_path)
    _write(book / "logs/ch1/diagnosis.json", json.dumps({
        "layer": "执笔层", "action": "继续修订", "reason": "执笔问题",
        "rounds": 3, "candidate_sha": candidate_sha(book, 1),
    }, ensure_ascii=False))
    _write(book / "chapters/_pending/ch1.md", "候选正文已经变化")
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)
    response = TestClient(ui_app.app).post(
        "/api/workbench/books/demo/chapters/1/diagnosis/route",
        json={"layer": "执笔层"},
    )
    assert response.status_code == 409
    assert "过期" in response.json()["detail"]


def test_route_preserves_assets_and_undo_restores_reading(tmp_path: Path, monkeypatch) -> None:
    from biyu.ui import app as ui_app
    from biyu.ui import workbench
    from biyu.ui.diagnosis import candidate_sha

    book = _book(tmp_path)
    diagnosis = {
        "layer": "方案层", "action": "退回改方案", "reason": "方案问题",
        "rounds": 3, "candidate_sha": candidate_sha(book, 1),
    }
    _write(book / "logs/ch1/diagnosis.json", json.dumps(diagnosis, ensure_ascii=False))
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)
    client = TestClient(ui_app.app)
    before = (book / "chapters/_pending/ch1.md").read_bytes()
    routed = client.post("/api/workbench/books/demo/chapters/1/diagnosis/route", json={"layer": "方案层"})
    assert routed.status_code == 200
    restored = client.post("/api/workbench/books/demo/chapters/1/diagnosis/restore")
    assert restored.status_code == 200
    assert restored.json()["axes"]["step"] == "reading"
    assert (book / "chapters/_pending/ch1.md").read_bytes() == before

