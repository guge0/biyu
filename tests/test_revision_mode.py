from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _package(tmp_path: Path, *, mode: object) -> Path:
    from biyu.audit_reports.revisions import create_revision_package

    _write(tmp_path / "book.json", "{}")
    _write(tmp_path / "chapters/ch1.md", "正式稿")
    _write(tmp_path / "chapters/_pending/ch1.md", "候选稿")
    _write(tmp_path / "logs/ch1/planning.md", "status: 已批\n甲与乙在北坊争执。")
    _write(
        tmp_path / "audit_reports/ch1.json",
        json.dumps(
            {"issues": [{"id": "ch1-001", "description": "节奏拖沓", "suggestion": "压短"}]},
            ensure_ascii=False,
        ),
    )
    return create_revision_package(
        tmp_path,
        1,
        selected_issue_ids=["ch1-001"],
        issue_comments={"ch1-001": "保留结尾"},
        general_comment="重写表达和场面组织",
        candidate_sha=_sha("候选稿"),
        mode=mode,
    )


def test_mode_reaches_writer_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import biyu.editor.editor as editor_module
    from biyu.pipeline import revise_chapter_from_package

    package = _package(tmp_path, mode="deep_rewrite")
    calls: list[dict] = []

    class Adapter:
        async def generate(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(text="重写后的候选稿", cost=0.0)

    async def fake_review(**_kwargs):
        return SimpleNamespace(issues=[], cost=0.0)

    monkeypatch.setattr(editor_module, "review_chapter", fake_review)
    asyncio.run(
        revise_chapter_from_package(
            tmp_path,
            1,
            package,
            writer_adapter=Adapter(),
            editor_adapter=object(),
            prompt_path=Path("prompts/writer/revision.md"),
        )
    )

    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "deep_rewrite"
    assert len(calls) == 1
    writer_messages = calls[0]["messages"]
    assert "【深度重写】" in writer_messages[1]["content"]
    assert "【局部返修】" not in writer_messages[1]["content"]


@pytest.mark.parametrize("mode", [None, "", "automatic", ["local_revision", "deep_rewrite"]])
def test_missing_mode_fails_loud(tmp_path: Path, mode: object) -> None:
    with pytest.raises(ValueError, match="返修模式无效"):
        _package(tmp_path, mode=mode)
    assert not (tmp_path / "logs/ch1/revisions/round_1").exists()


def test_local_mode_unchanged(tmp_path: Path) -> None:
    from biyu.pipeline import build_whole_revision_messages

    package = _package(tmp_path, mode="local_revision")
    messages = build_whole_revision_messages(package)
    payload = messages[1]["content"]
    assert "【局部返修】" in payload
    assert "【深度重写】" not in payload
    assert all(
        text in payload
        for text in ("节奏拖沓", "保留结尾", "重写表达和场面组织", "甲与乙在北坊争执", "候选稿")
    )


def test_revision_ui_requires_explicit_mode() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
    # 读稿页收敛 B10:fieldset 改普通小标题+radio(div#revision-mode)
    mode_block = html.split('id="revision-mode"', 1)[1].split("</div>", 1)[0]
    assert 'value="local_revision"' in mode_block
    assert 'value="deep_rewrite"' in mode_block
    assert "checked" not in mode_block
    assert "返修模式无效" in js
    assert "mode:revisionMode" in js


def test_signed_writer_and_planning_text_installed_verbatim() -> None:
    writer = Path("prompts/writer/revision.md").read_text(encoding="utf-8")
    planning = Path("src/biyu/prompts/v3_opening.py").read_text(encoding="utf-8")
    assert "返修模式只有两种：" in writer
    assert "【深度重写】以作者整体意见统领重写" in writer
    assert "不得新增方案之外的重要事件、设定、人物决定或伏笔回收" in writer
    assert "6. **不要把普通表演动作写成验收计数。**" in planning
    assert "普通表演动作写作用与情绪变化，不写第几次动作或必须出现几次" in planning
