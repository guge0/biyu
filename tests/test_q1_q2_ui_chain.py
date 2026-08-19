from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _book(tmp_path: Path) -> Path:
    book = tmp_path / "fixture-book"
    _write(
        book / "book.json",
        json.dumps(
            {"id": "book-id", "display_name": "测试书"},
            ensure_ascii=False,
        ),
    )
    return book


def _state(book: Path, chapter: int, step: str) -> None:
    _write(
        book / "logs" / f"ch{chapter}" / "workbench_state.json",
        json.dumps(
            {"step": step, "updated_at": "2026-08-04T10:00:00+08:00"},
            ensure_ascii=False,
        ),
    )


def test_export_rechecks_finalized_and_sorts_numeric_chapters(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from biyu.ui.app import app
    import biyu.ui.overview as overview

    book = _book(tmp_path)
    _write(book / "chapters/ch10.md", "# 第十章 后章\n后章正文")
    _write(book / "chapters/ch2.md", "# 第二章 前章\n前章正文")
    _state(book, 10, "review")
    _state(book, 2, "review")
    monkeypatch.setattr(overview, "_book_dir", lambda _book: book)

    response = TestClient(app).post(
        "/api/overview/books/book-id/export",
        json={"chapters": [10, 2, 10]},
    )

    assert response.status_code == 200
    assert response.content.decode("utf-8").startswith("《测试书》")
    text = response.content.decode("utf-8")
    assert text.index("第 2 章 前章") < text.index("第 10 章 后章")
    assert "前章正文" in text and "后章正文" in text
    assert "# 第二章" not in text and "# 第十章" not in text
    assert response.headers["content-type"].startswith("text/plain")
    assert "UTF-8''" in response.headers["content-disposition"]


def test_export_rejects_nonfinalized_chapter_without_partial_download(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from biyu.ui.app import app
    import biyu.ui.overview as overview

    book = _book(tmp_path)
    _write(book / "chapters/ch1.md", "# 第一章 已定稿\n正文一")
    _write(book / "chapters/ch2.md", "# 第二章 未定稿\n正文二")
    _state(book, 1, "review")
    _state(book, 2, "planning")
    monkeypatch.setattr(overview, "_book_dir", lambda _book: book)

    response = TestClient(app).post(
        "/api/overview/books/book-id/export",
        json={"chapters": [1, 2]},
    )

    assert response.status_code == 409
    assert "第 2 章还没有定稿" in response.json()["detail"]
    assert "正文一" not in response.text


def test_good_sentences_reads_only_good_sentence_and_sorts_by_chapter_time(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from biyu.ui.app import app
    import biyu.ui.good_sentences as good_sentences

    book = _book(tmp_path)
    entries = [
        {"chapter": 2, "scope": "sentence", "action": "good", "text": "第二章晚", "created_at": "2026-08-04T12:00:00+08:00"},
        {"chapter": 1, "scope": "sentence", "action": "good", "text": "第一章", "created_at": "2026-08-04T11:00:00+08:00"},
        {"chapter": 2, "scope": "sentence", "action": "good", "text": "第二章早", "created_at": "2026-08-04T10:00:00+08:00"},
        {"chapter": 1, "scope": "chapter", "action": "good", "text": "章评", "created_at": "2026-08-04T09:00:00+08:00"},
        {"chapter": 1, "scope": "sentence", "action": "note_problem", "text": "问题句", "created_at": "2026-08-04T09:00:00+08:00"},
    ]
    _write(
        book / "反馈账.jsonl",
        "\n".join(json.dumps(item, ensure_ascii=False) for item in entries) + "\n",
    )
    monkeypatch.setattr(good_sentences, "_book_dir", lambda _book: book)

    response = TestClient(app).get("/api/good-sentences/books/book-id")

    assert response.status_code == 200
    assert response.json() == {
        "book": {"id": "book-id", "display_name": "测试书"},
        "chapters": [1, 2],
        "entries": [
            {"chapter": 1, "text": "第一章", "created_at": "2026-08-04T11:00:00+08:00"},
            {"chapter": 2, "text": "第二章早", "created_at": "2026-08-04T10:00:00+08:00"},
            {"chapter": 2, "text": "第二章晚", "created_at": "2026-08-04T12:00:00+08:00"},
        ],
    }


def test_q2_book_navigation_and_q1_copy_export_ui_contracts() -> None:
    static = Path("src/biyu/ui/static")
    book = (static / "book.html").read_text(encoding="utf-8")
    workbench = (static / "workbench.html").read_text(encoding="utf-8")
    workbench_js = (static / "workbench.js").read_text(encoding="utf-8")
    overview = (static / "overview.html").read_text(encoding="utf-8")
    overview_js = (static / "overview.js").read_text(encoding="utf-8")

    for label in (
        "章节工作台",
        "整书概览",
        "好句",
        "起名/改名",
        "纪要",
        "设定集",
    ):
        assert f'<div class="entry-label">{label}</div>' in book
    assert book.count('class="entry-card"') == 7
    assert '<div class="entry-label">打开 Claude Code</div>' in book
    assert 'id="overview-link"' not in workbench
    assert 'id="voiceprint-link"' in workbench
    assert 'id="copy-chapter"' in workbench
    assert "navigator.clipboard" in workbench_js
    assert "document.execCommand('copy')" in workbench_js
    assert "input.type='radio'" in workbench_js
    assert "JSON.stringify({active})" in workbench_js
    assert "profile_state?.order" not in workbench_js
    assert 'id="export-selected"' in overview
    assert "正在导出…" in overview_js
    assert "/export" in overview_js
    assert "finally" in overview_js


def test_good_sentences_page_is_read_only_and_has_ui_floor() -> None:
    static = Path("src/biyu/ui/static")
    html = (static / "good-sentences.html").read_text(encoding="utf-8")
    script = (static / "good-sentences.js").read_text(encoding="utf-8")

    assert "全书好句" in html
    assert 'id="chapter-filter"' in html
    assert 'id="load-status"' in html
    assert 'id="error-banner"' in html
    assert "error-banner-close" in script
    assert "response.ok" in script
    assert "textContent=item.text" in script
    assert "contenteditable" not in (html + script).lower()
    assert "<textarea" not in html.lower()
    assert "method:'POST'" not in script and 'method: "POST"' not in script


def test_reviews_page_is_deleted_but_standalone_core_is_retained() -> None:
    assert not Path("src/biyu/ui/static/reviews.html").exists()
    assert Path("src/biyu/editor/standalone.py").exists()
    assert Path("src/biyu/cli/review_standalone_cmd.py").exists()


def test_shelf_and_book_detail_ignore_last_reviewed() -> None:
    app_js = Path("src/biyu/ui/static/app.js").read_text(encoding="utf-8")
    book_html = Path("src/biyu/ui/static/book.html").read_text(encoding="utf-8")

    assert "last_reviewed" not in app_js
    assert "last_reviewed" not in book_html
    assert "已审到" not in app_js + book_html
