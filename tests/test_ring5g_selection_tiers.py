from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from biyu.feedback_ledger import append_feedback


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
JS = (ROOT / "src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")


def test_selection_bar_two_tier() -> None:
    assert 'id="selection-revision"' in HTML and ">让写手改这句<" in HTML
    assert 'data-feedback="note_problem">记下问题（暂不修改）<' in HTML
    assert 'data-feedback="good">记为好句<' in HTML
    assert "记一笔" not in HTML
    assert "两个都要" not in HTML
    assert 'class="selection-secondary"' in HTML


def test_main_action_focuses_note_input() -> None:
    assert 'id="revision-echo"' in HTML
    assert "revisionEcho" in JS
    assert ".author-picked textarea')?.focus()" in JS
    assert "revisionLines.unshift" in JS
    assert "sessionNotes.push({id:entry.id,type:'problem'" in JS


def test_session_notes_are_bound_to_book_chapter_and_candidate() -> None:
    assert "sessionNotesContext" in JS
    assert "`${book}:${incoming.chapter}:${incoming.chapter_sha}`" in JS
    assert "sessionNotesContext!==incomingNotesContext)sessionNotes=[]" in JS


def test_revise_writes_ledger_same_source(tmp_path: Path) -> None:
    entry = append_feedback(
        tmp_path,
        book="fixture",
        chapter=3,
        round_no=2,
        scope="sentence",
        candidate_sha="candidate-sha",
        anchor=4,
        text="这一句需要修改。",
        action="revise",
        author_comment="节奏太慢",
        in_revision_package=True,
    )
    card = {
        "text": entry["text"],
        "book": entry["book"],
        "chapter": entry["chapter"],
        "candidate_sha": entry["candidate_sha"],
        "anchor": entry["anchor"],
    }
    assert (card["text"], card["book"], card["chapter"], card["candidate_sha"], card["anchor"]) == (
        entry["text"],
        entry["book"],
        entry["chapter"],
        entry["candidate_sha"],
        entry["anchor"],
    )


def test_note_writes_ledger_only(tmp_path: Path) -> None:
    negative = tmp_path / "样本库/负例候选.md"
    negative.parent.mkdir(parents=True)
    negative.write_text("存量\n", encoding="utf-8")
    before = (negative.read_bytes(), negative.stat().st_mtime_ns)
    append_feedback(
        tmp_path,
        book="fixture",
        chapter=1,
        round_no=0,
        scope="sentence",
        candidate_sha="sha",
        anchor=1,
        text="只记下问题。",
        action="note_problem",
        in_revision_package=False,
    )
    assert (negative.read_bytes(), negative.stat().st_mtime_ns) == before
    assert json.loads((tmp_path / "反馈账.jsonl").read_text(encoding="utf-8"))["action"] == "note_problem"


def test_good_writes_positive_and_ledger_contract() -> None:
    backend = (ROOT / "src/biyu/ui/workbench.py").read_text(encoding="utf-8")
    assert 'if action == "good":' in backend
    assert "_append_sample_entry(book_dir" in backend
    assert "append_feedback(" in backend


def test_ledger_is_append_only(tmp_path: Path) -> None:
    first = append_feedback(
        tmp_path, book="fixture", chapter=1, round_no=0, scope="sentence", candidate_sha="a",
        anchor=1, text="甲。", action="revise", in_revision_package=True,
    )
    append_feedback(
        tmp_path, book="fixture", chapter=1, round_no=0, scope="sentence", candidate_sha="a",
        anchor=2, text="乙。", action="note_problem", in_revision_package=False,
    )
    lines = (tmp_path / "反馈账.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["id"] == first["id"]
    assert "remove" not in inspect.getsource(__import__("biyu.feedback_ledger", fromlist=["*"]))


def test_ledger_line_is_parseable(tmp_path: Path) -> None:
    append_feedback(
        tmp_path, book="fixture", chapter=7, round_no=3, scope="sentence", candidate_sha="sha",
        anchor=2, text="原句。", action="good", author_comment="", in_revision_package=False,
    )
    item = json.loads((tmp_path / "反馈账.jsonl").read_text(encoding="utf-8"))
    assert {
        "id", "created_at", "book", "chapter", "round", "scope", "candidate_sha",
        "anchor", "text", "action", "author_comment", "in_revision_package",
    } <= item.keys()


def test_ledger_zero_llm_and_has_no_read_api() -> None:
    import biyu.feedback_ledger as ledger

    exported = {name for name, value in vars(ledger).items() if callable(value) and not name.startswith("_")}
    assert "append_feedback" in exported
    assert not any(name.startswith(("read", "load", "list", "get")) for name in exported)
    source = inspect.getsource(ledger)
    assert "adapter" not in source.lower()
    assert ".read_" not in source


def test_ledger_scope_field_required(tmp_path: Path) -> None:
    sentence = append_feedback(
        tmp_path,
        book="fixture",
        chapter=1,
        round_no=0,
        scope="sentence",
        candidate_sha="sha",
        anchor=1,
        text="句级反馈。",
        action="note_problem",
        in_revision_package=False,
    )
    chapter = append_feedback(
        tmp_path,
        book="fixture",
        chapter=1,
        round_no=0,
        scope="chapter",
        verdict="这一章节奏不好",
        action="note_problem",
        in_revision_package=False,
    )
    assert sentence["scope"] == "sentence"
    assert {"candidate_sha", "anchor", "text"} <= sentence.keys()
    assert chapter["scope"] == "chapter" and chapter["verdict"] == "这一章节奏不好"
    assert not ({"candidate_sha", "anchor", "text"} & chapter.keys())


def test_no_direct_negative_write_anywhere() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src").rglob("*.py")
    )
    assert '_append(book_dir / "样本库" / "负例候选.md"' not in sources
    assert 'else "负例候选.md"' not in sources
    assert 'else "负例候选.md")' not in sources


def test_ledger_and_positive_not_in_package() -> None:
    assert "sample_problem_ids:[]" in JS
    assert "feedback_ledger" not in (
        ROOT / "src/biyu/audit_reports/revisions.py"
    ).read_text(encoding="utf-8")


def test_paragraph_number_starts_at_one() -> None:
    assert "第 ${card.anchor||0} 段" not in JS
    assert "Math.max(1,Number(card.anchor" in JS


def test_quote_snaps_to_sentence_boundary_and_within_paragraph_only() -> None:
    assert "function snapSelectionWithinParagraph" in JS
    assert "range.startContainer" in JS
    assert "range.endContainer" in JS
    assert "startParagraph!==endParagraph" in JS
    assert "return null" in JS


def test_record_section_collapsed_by_default() -> None:
    assert 'id="sample-preview" class="revision-fold sample-preview"' in HTML
    assert "本章记录：问题" in HTML
    assert "· 好句" in HTML


def test_no_view_in_page_button() -> None:
    assert "在本页查看" not in HTML + JS
    assert "已记下问题，暂不修改本章；见右栏「本章记录」。" in JS
    assert "已记为好句；见右栏「本章记录」。" in JS


def test_three_entry_labels() -> None:
    assert "让写手改这句" in HTML
    assert "记下问题（暂不修改）" in HTML
    assert "记为好句" in HTML
    assert "记一笔" not in HTML
    assert "两个都要" not in HTML


def test_record_stays_collapsed_after_good() -> None:
    receipt = JS[JS.index("function showExcerptReceipt"):JS.index("function canOpenStage")]
    assert "openSamplePreview" not in receipt
    assert "$('sample-preview').open=true" not in receipt
    assert "render();showExcerptReceipt(action)" in JS
    # 读稿页收敛 B2:顶部重复按钮已删,计数只在折叠行
    assert "sample-shortcut" not in JS


def test_record_header_counts() -> None:
    # 读稿页收敛 B2:顶部重复按钮已删,只剩折叠行计数
    compact = "sample-shortcut"
    detail = "本章记录：问题 <span id=\"sample-preview-problems\">0</span> · 好句 <span id=\"sample-preview-good\">0</span>"
    assert compact not in HTML
    assert detail in HTML


def test_action_enum_values(tmp_path: Path) -> None:
    for index, action in enumerate(("revise", "note_problem", "good"), start=1):
        entry = append_feedback(
            tmp_path,
            book="fixture",
            chapter=1,
            round_no=0,
            scope="sentence",
            candidate_sha="sha",
            anchor=index,
            text=f"第 {index} 句。",
            action=action,
            in_revision_package=action == "revise",
        )
        assert entry["action"] == action
        assert "polarity" not in entry
    with pytest.raises(ValueError, match="note_problem"):
        append_feedback(
            tmp_path,
            book="fixture",
            chapter=1,
            round_no=0,
            scope="sentence",
            candidate_sha="sha",
            anchor=4,
            text="旧动作。",
            action="note",
            in_revision_package=False,
        )


def test_relabel_and_verdict_map_to_note_problem(tmp_path: Path, monkeypatch) -> None:
    from biyu.cli import verdict_cmd, workbench_cmd
    from biyu.ui import workbench as ui_workbench

    monkeypatch.setattr(workbench_cmd, "resolve_book_dir", lambda _book: tmp_path)
    monkeypatch.setattr(verdict_cmd, "resolve_book_dir", lambda _book: tmp_path)
    workbench_cmd.excerpt(
        chapter=1,
        book="fixture",
        kind="good",
        content="先记为好句。",
        version="sha",
        anchor=2,
    )
    item = ui_workbench._sample_entries(
        (tmp_path / "样本库/正例候选.md").read_text(encoding="utf-8"),
        "",
    )[0]
    workbench_cmd.excerpt_retag(
        book="fixture",
        chapter=1,
        entry_id=item["id"],
        new_kind="problem",
    )
    verdict_cmd.add_verdict(
        chapter=1,
        book="fixture",
        verdict="本章判词",
        negative="这一章节奏有问题",
    )
    entries = [
        json.loads(line)
        for line in (tmp_path / "反馈账.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert entries[0]["action"] == "note_problem"
    assert entries[0]["scope"] == "sentence" and entries[0]["from"] == "good"
    assert entries[1]["action"] == "note_problem"
    assert entries[1]["scope"] == "chapter"


def test_feedback_endpoint_returns_the_exact_visible_card_source(tmp_path: Path, monkeypatch) -> None:
    from biyu.ui import app as ui_app
    from biyu.ui import workbench

    book = tmp_path / "fixture"
    pending = book / "chapters/_pending/ch3.md"
    pending.parent.mkdir(parents=True)
    pending.write_text("第一段。\n\n这一句需要修改。", encoding="utf-8")
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)
    response = TestClient(ui_app.app).post(
        "/api/workbench/books/fixture/chapters/3/feedback",
        json={
            "action": "revise",
            "text": "这一句需要修改。",
            "anchor": 2,
            "candidate_sha": workbench._sha(pending.read_text(encoding="utf-8")),
            "author_comment": "",
        },
    )
    assert response.status_code == 200
    entry = response.json()["entry"]
    ledger = json.loads((book / "反馈账.jsonl").read_text(encoding="utf-8"))
    visible_card = {
        key: entry[key]
        for key in ("text", "book", "chapter", "candidate_sha", "anchor")
    }
    assert visible_card == {
        key: ledger[key]
        for key in ("text", "book", "chapter", "candidate_sha", "anchor")
    }
    assert ledger["action"] == "revise"
    assert ledger["in_revision_package"] is True
