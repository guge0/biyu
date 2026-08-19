from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient


def _file(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_severity_contract_has_no_fake_warning_and_real_issue_is_a_card(tmp_path: Path) -> None:
    from biyu.audit_reports.builder import build_audit_report
    from biyu.auditor.base import Severity

    assert [s.value for s in Severity] == ["PASS", "SKIP", "BLOCK", "WARN"]
    path = build_audit_report(
        tmp_path,
        1,
        audit_results=[
            {"checker": "ok", "severity": "PASS", "message": "通过"},
            {"checker": "na", "severity": "SKIP", "message": "不适用"},
        ],
    )
    text = path.read_text(encoding="utf-8")
    assert "检查完成 2 项" in text
    assert "⚠️" not in text and "问题卡" not in text

    path = build_audit_report(
        tmp_path,
        2,
        audit_results=[{"checker": "mine", "severity": "WARN", "message": "埋入的真问题"}],
    )
    text = path.read_text(encoding="utf-8")
    assert "问题卡" in text and "埋入的真问题" in text


def test_revision_package_is_one_round_one_directory_and_rejects_stale_candidate(tmp_path: Path) -> None:
    from biyu.audit_reports.revisions import create_revision_package

    pending = _file(tmp_path / "chapters/_pending/ch1.md", "候选 v1")
    _file(tmp_path / "logs/ch1/planning.md", "status: 已批\n方案")
    report = {
        "chapter": 1,
        "issues": [{"id": "ch1-001", "description": "问题", "suggestion": "建议"}],
    }
    _file(tmp_path / "audit_reports/ch1.json", json.dumps(report, ensure_ascii=False))

    package = create_revision_package(
        tmp_path,
        1,
        selected_issue_ids=["ch1-001"],
        issue_comments={"ch1-001": "按人物动机改"},
        general_comment="节奏收紧",
        candidate_sha=_sha("候选 v1"),
    )
    assert package.name == "round_1"
    assert {p.name for p in package.iterdir()} == {
        "manifest.json", "issues.json", "comments.md", "candidate.md", "planning.md"
    }
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["candidate_sha"] == _sha("候选 v1")
    assert manifest["selected_issue_ids"] == ["ch1-001"]

    pending.write_text("候选 v2", encoding="utf-8")
    try:
        create_revision_package(
            tmp_path, 1, selected_issue_ids=["ch1-001"], issue_comments={},
            general_comment="", candidate_sha=_sha("候选 v1"),
        )
    except ValueError as exc:
        assert "新版本" in str(exc)
    else:
        raise AssertionError("stale candidate must be rejected")


def test_conditional_pen_targets_candidate_and_locks_official(tmp_path: Path, monkeypatch) -> None:
    from biyu.ui.app import app
    import biyu.ui.workbench as wb

    book = tmp_path / "Book"
    _file(book / "book.json", "{}")
    official = _file(book / "chapters/ch1.md", "正式 v1")
    monkeypatch.setattr(wb, "get_data_root", lambda: tmp_path)
    client = TestClient(app)

    snap = client.get("/api/workbench/books/Book/chapters/1").json()
    assert snap["chapter_target"] == "official"
    saved = client.put(
        "/api/workbench/books/Book/chapters/1/chapter",
        json={"content": "正式手改", "base_sha": snap["chapter_sha"], "target": "official"},
    )
    assert saved.status_code == 200 and official.read_text(encoding="utf-8") == "正式手改"

    pending = _file(book / "chapters/_pending/ch1.md", "候选 v1")
    snap = client.get("/api/workbench/books/Book/chapters/1").json()
    assert snap["chapter_target"] == "pending" and snap["official_locked"] is True
    blocked = client.put(
        "/api/workbench/books/Book/chapters/1/chapter",
        json={"content": "偷改正式", "base_sha": _sha("正式手改"), "target": "official"},
    )
    assert blocked.status_code == 409
    assert "候选" in blocked.json()["detail"]
    assert official.read_text(encoding="utf-8") == "正式手改"
    assert pending.read_text(encoding="utf-8") == "候选 v1"


def test_pending_and_official_snapshots_expose_issue_cards_and_s5_excerpt(tmp_path: Path) -> None:
    import biyu.ui.workbench as wb

    _file(tmp_path / "outlines/ch1.md", "细纲")
    _file(tmp_path / "logs/ch1/planning.md", "status: 已批\n方案")
    _file(tmp_path / "chapters/ch1.md", "正式")
    _file(tmp_path / "chapters/_pending/ch1.md", "候选")
    _file(
        tmp_path / "audit_reports/ch1.json",
        json.dumps({
            "chapter": 1,
            "results": [
                {"checker": "ok", "severity": "PASS", "message": "通过"},
                {"checker": "mine", "severity": "WARN", "message": "真问题"},
            ],
            "issues": [{
                "id": "ch1-001", "type": "逻辑常识", "paragraph": 3,
                "description": "前后打架", "suggestion": "统一说法", "severity": "medium",
                "quoted_text": "原句", "status": "open",
            }],
        }, ensure_ascii=False),
    )
    snap = wb.chapter_snapshot(tmp_path, 1)
    assert snap["axes"]["asset"] == "both"
    assert snap["axes"]["step"] == "reading"
    assert snap["actions"]["excerpt"]["enabled"] is True
    assert snap["official_text"] == "正式"
    assert len(snap["issue_cards"]) == 2
    assert {c["source"] for c in snap["issue_cards"]} == {"editor", "auditor"}


def test_whole_revision_calls_writer_once_rereviews_and_never_touches_official(tmp_path: Path, monkeypatch) -> None:
    import asyncio
    import biyu.editor.editor as editor_module
    from biyu.audit_reports.revisions import create_revision_package
    from biyu.pipeline import revise_chapter_from_package

    _file(tmp_path / "book.json", "{}")
    official = _file(tmp_path / "chapters/ch1.md", "正式不得碰")
    _file(tmp_path / "chapters/_pending/ch1.md", "候选 v1")
    _file(tmp_path / "logs/ch1/planning.md", "status: 已批\n方案")
    _file(tmp_path / "audit_reports/ch1.json", json.dumps({
        "chapter": 1,
        "issues": [{"id": "ch1-001", "description": "问题", "suggestion": "建议"}],
    }, ensure_ascii=False))
    package = create_revision_package(
        tmp_path, 1, selected_issue_ids=["ch1-001"], issue_comments={},
        general_comment="整体收紧", candidate_sha=_sha("候选 v1"),
    )
    prompt = _file(tmp_path / "revision-prompt.md", "只输出修订后的完整正文")

    class Adapter:
        def __init__(self) -> None:
            self.calls = []

        async def generate(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(text="候选 v2", cost=0.01)

    writer = Adapter()

    async def fake_review(**_kwargs):
        return SimpleNamespace(issues=[], cost=0.02)

    monkeypatch.setattr(editor_module, "review_chapter", fake_review)
    result = asyncio.run(revise_chapter_from_package(
        tmp_path, 1, package, writer_adapter=writer, editor_adapter=object(), prompt_path=prompt,
    ))
    assert len(writer.calls) == 1
    assert "整体收紧" in writer.calls[0]["messages"][1]["content"]
    assert official.read_text(encoding="utf-8") == "正式不得碰"
    assert (tmp_path / "chapters/_pending/ch1.md").read_text(encoding="utf-8") == "候选 v2"
    assert result["candidate_sha"] == _sha("候选 v2")
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "complete"


def test_signed_revision_prompt_is_the_default_consumer_and_enters_writer_payload(tmp_path: Path) -> None:
    from biyu.pipeline import build_whole_revision_messages

    package = tmp_path / "round_1"
    _file(package / "manifest.json", '{"round":1,"candidate_sha":"test"}')
    _file(package / "issues.json", '[{"id":"ch1-001","description":"事实打架"}]')
    _file(package / "comments.md", "## 作者逐条意见\n按人物动机改\n\n## 作者整体意见\n保住结尾")
    _file(package / "planning.md", "status: 已批\n保留本章戏核")
    _file(package / "candidate.md", "当前候选稿")

    messages = build_whole_revision_messages(package)

    assert messages[0]["role"] == "system"
    assert messages[0]["content"].startswith("你是这本中文网文的作者。现在不是另写一章")
    assert "只输出修订后的完整正文" in messages[0]["content"]
    payload = messages[1]["content"]
    assert all(text in payload for text in ("事实打架", "按人物动机改", "保住结尾", "保留本章戏核", "当前候选稿"))
