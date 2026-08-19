from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


SIGNED_PROMPT = "你是独立的章节返工诊断员，不参与创作。先读历次作者意见、作者勾选的问题卡和本章问题句索引，归纳反复出现的症状；再围绕这些症状按需读取对应轮次候选稿及上下文，必要时核对当前写作方案和本章细纲，不得无目的通读全部材料。问题句只作作者不满意的定位证据：仅查看本章内带候选版本和段落锚点的记录；当意见涉及措辞、节奏或人物表达，或同类问题跨轮重复时才展开原句。不得读取全书或作者级负例库，也不得只凭单个问题句把根因判为执笔层。综合证据后，只选一个首要根因：“细纲层”“方案层”或“执笔层”；用一句人话说明依据，再给出对应动作：细纲层→退回细纲，方案层→退回改方案，执笔层→继续修订。不得改写正文，不得虚构输入中没有的事实。"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _round(book: Path, number: int, *, anchor: int = 2, general: str = "（无整体意见）") -> None:
    root = book / f"logs/ch1/revisions/round_{number}"
    _write(root / "manifest.json", json.dumps({"round": number, "status": "complete", "candidate_sha": f"sha-{number}"}))
    _write(root / "comments.md", f"# 本轮作者意见\n\n{general}\n\n## 逐条意见\n- issue-{number}: 中段节奏拖\n")
    _write(root / "issues.json", json.dumps([{"id": f"issue-{number}", "paragraph": anchor, "description": "中段节奏拖", "author_comment": "压紧"}], ensure_ascii=False))
    _write(root / "candidate.md", "第一段。\n\n第二段需要检查。\n\n第三段。\n\n第四段不相关。")


def test_signed_prompt_bytes_are_installed() -> None:
    assert Path("prompts/workbench/diagnosis.md").read_text(encoding="utf-8").rstrip("\n") == SIGNED_PROMPT


def test_evidence_is_opinion_first_and_candidate_context_is_anchor_scoped(tmp_path: Path) -> None:
    from biyu.ui.diagnosis import build_diagnosis_messages

    for number in range(1, 4):
        _round(tmp_path, number)
    _write(tmp_path / "outlines/ch1.md", "本章细纲")
    _write(tmp_path / "logs/ch1/planning.md", "status: 已批\n当前方案")
    _write(tmp_path / "样本库/负例候选.md", '- {"id":"bad-1","type":"problem","text":"问题原句","chapter":1,"version_sha":"sha-2","anchor":2}\n')
    _write(tmp_path / "样本库/全书负例.md", "绝不能进入诊断的整库内容")

    messages = build_diagnosis_messages(tmp_path, 1)
    user = messages[1]["content"]
    assert user.index("作者意见与问题卡索引") < user.index("按需读取的候选上下文")
    assert "第二段需要检查" in user
    assert "第四段不相关" not in user
    assert "绝不能进入诊断的整库内容" not in user
    assert "问题句索引" in user


def test_broad_round_opinion_loads_that_round_full_candidate(tmp_path: Path) -> None:
    from biyu.ui.diagnosis import build_diagnosis_messages

    _round(tmp_path, 1, general="整章人物动机都不成立")
    _round(tmp_path, 2)
    _round(tmp_path, 3)
    messages = build_diagnosis_messages(tmp_path, 1)
    assert "第四段不相关" in messages[1]["content"]


def test_diagnosis_requires_three_complete_rounds_and_persists_single_layer(tmp_path: Path) -> None:
    from biyu.ui.diagnosis import diagnose_chapter

    _round(tmp_path, 1)
    _round(tmp_path, 2)
    with pytest.raises(ValueError, match="第 3 轮"):
        asyncio.run(diagnose_chapter(tmp_path, 1, adapter=object()))

    _round(tmp_path, 3)

    class Adapter:
        async def generate(self, messages, **kwargs):
            assert messages[0]["content"] == SIGNED_PROMPT + "\n"
            return SimpleNamespace(text="方案层：三轮都要求补足战斗，但当前方案只给了很少篇幅。", cost=0.002)

    costs = []
    result = asyncio.run(diagnose_chapter(tmp_path, 1, adapter=Adapter(), log_cost_fn=lambda cost, latency: costs.append(cost)))
    assert result["layer"] == "方案层"
    assert result["action"] == "退回改方案"
    assert costs == [0.002]
    saved = json.loads((tmp_path / "logs/ch1/diagnosis.json").read_text(encoding="utf-8"))
    assert saved["layer"] == "方案层"


def test_invalid_diagnosis_is_loud_but_still_logs_spend(tmp_path: Path) -> None:
    from biyu.ui.diagnosis import diagnose_chapter

    for number in range(1, 4):
        _round(tmp_path, number)

    class Adapter:
        async def generate(self, messages, **kwargs):
            assert kwargs["max_tokens"] == 1500
            return SimpleNamespace(text="", cost=0.008)

    costs = []
    with pytest.raises(RuntimeError, match="没有给出"):
        asyncio.run(diagnose_chapter(tmp_path, 1, adapter=Adapter(), log_cost_fn=lambda cost, latency: costs.append(cost)))
    assert costs == [0.008]


def test_snapshot_exposes_third_round_diagnosis_without_changing_asset(tmp_path: Path, monkeypatch) -> None:
    from biyu.ui import workbench

    book = tmp_path / "demo"
    for number in range(1, 4):
        _round(book, number)
    _write(book / "book.json", json.dumps({"title": "诊断测试"}))
    _write(book / "chapters/_pending/ch1.md", "候选正文")
    _write(book / "logs/ch1/diagnosis.json", json.dumps({
        "layer": "方案层", "reason": "三轮意见都指向篇幅分配。", "action": "退回改方案", "rounds": 3,
    }, ensure_ascii=False))
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)

    before = (book / "chapters/_pending/ch1.md").read_bytes()
    snapshot = workbench.chapter_snapshot(book, 1, "demo")

    assert snapshot["revision_rounds"] == 3
    assert snapshot["actions"]["diagnose"]["enabled"] is True
    assert snapshot["diagnosis"]["action"] == "退回改方案"
    assert (book / "chapters/_pending/ch1.md").read_bytes() == before


def test_diagnosis_route_changes_only_step_and_preserves_candidate(tmp_path: Path, monkeypatch) -> None:
    from biyu.ui import app as ui_app
    from biyu.ui import workbench

    book = tmp_path / "demo"
    _write(book / "book.json", json.dumps({"title": "诊断测试"}))
    _write(book / "chapters/_pending/ch1.md", "候选正文")
    _write(book / "logs/ch1/diagnosis.json", json.dumps({
        "layer": "细纲层", "reason": "冲突来自细纲。", "action": "退回细纲", "rounds": 3,
    }, ensure_ascii=False))
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)
    before = (book / "chapters/_pending/ch1.md").read_bytes()

    response = TestClient(ui_app.app).post("/api/workbench/books/demo/chapters/1/diagnosis/route", json={"layer": "细纲层"})

    assert response.status_code == 200
    assert response.json()["axes"]["step"] == "outline"
    assert (book / "chapters/_pending/ch1.md").read_bytes() == before


def test_frontend_has_visible_diagnosis_and_explicit_route() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")

    assert 'id="diagnosis-card"' in html
    assert 'id="diagnose-button"' in html
    assert "stream('diagnose')" in js
    assert "/diagnosis/route" in js
