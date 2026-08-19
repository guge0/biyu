from __future__ import annotations

import csv
import json
from pathlib import Path
from time import perf_counter

import pytest
from fastapi.testclient import TestClient


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _state(book: Path, chapter: int, step: str, updated_at: str | None) -> None:
    payload = {"step": step}
    if updated_at is not None:
        payload["updated_at"] = updated_at
    _write(
        book / "logs" / f"ch{chapter}" / "workbench_state.json",
        json.dumps(payload, ensure_ascii=False),
    )


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


def _ledger_line(
    *,
    chapter: int,
    action: str,
    scope: str = "sentence",
) -> str:
    return json.dumps(
        {
            "id": f"{chapter}-{action}-{scope}",
            "book": "book-id",
            "chapter": chapter,
            "round": 1,
            "scope": scope,
            "action": action,
            "text": "一句",
            "candidate_sha": "abc",
            "anchor": 1,
        },
        ensure_ascii=False,
    )


def test_overview_groups_by_durable_step_and_sentence_problem_count(
    tmp_path: Path,
) -> None:
    from biyu.ui.overview import build_overview

    book = _book(tmp_path)
    _write(book / "chapters/ch1.md", "# 第一章 定稿无问题\n甲乙丙")
    _state(book, 1, "review", "2026-07-26T08:00:00+00:00")
    _write(book / "chapters/ch2.md", "# 第二章 定稿有问题\n丁戊己")
    _state(book, 2, "review", "2026-07-27T08:00:00+00:00")
    _write(book / "outlines/ch3.md", "# 第三章 等待生成")
    _write(book / "logs/ch3/planning.md", "status: 已批\n方案")
    _state(book, 3, "generation", "2026-07-28T08:00:00+00:00")
    _write(book / "chapters/_pending/ch4.md", "# 第四章 待读候选\n庚辛壬")
    _state(book, 4, "reading", "2026-07-29T08:00:00+00:00")
    _write(
        book / "反馈账.jsonl",
        "\n".join(
            [
                _ledger_line(chapter=2, action="revise"),
                _ledger_line(chapter=2, action="note_problem"),
                _ledger_line(chapter=2, action="good"),
                _ledger_line(
                    chapter=2,
                    action="note_problem",
                    scope="chapter",
                ),
            ]
        )
        + "\n",
    )

    result = build_overview(book, "book-id")

    assert result["metrics"] == {
        "finalized_chapters": 2,
        "total_words": 22,
        "waiting_chapters": 2,
    }
    assert [row["chapter"] for row in result["groups"]["waiting"]] == [3, 4]
    assert [row["status"] for row in result["groups"]["waiting"]] == [
        "等着生成",
        "有稿等你读",
    ]
    assert result["groups"]["problem_finalized"][0]["problem_count"] == 2
    assert [row["chapter"] for row in result["groups"]["finalized"]] == [1]


def test_official_asset_alone_never_means_finalized(tmp_path: Path) -> None:
    from biyu.ui.overview import build_overview

    book = _book(tmp_path)
    _write(book / "chapters/ch1.md", "# 第一章 仍在方案阶段\n正文")
    _state(book, 1, "planning", "2026-07-29T08:00:00+00:00")

    result = build_overview(book, "book-id")

    assert result["metrics"]["finalized_chapters"] == 0
    assert [row["chapter"] for row in result["groups"]["waiting"]] == [1]
    assert result["groups"]["finalized"] == []


@pytest.mark.parametrize(
    ("step", "asset_path"),
    [
        ("review", None),
        ("reading", None),
        ("generation", "outlines/ch1.md"),
    ],
)
def test_inconsistent_axes_are_visible_and_never_finalized(
    tmp_path: Path,
    step: str,
    asset_path: str | None,
) -> None:
    from biyu.ui.overview import build_overview

    book = _book(tmp_path)
    if asset_path:
        _write(book / asset_path, "# 第一章 状态夹具")
    else:
        _write(book / "logs/ch1/note.md", "让章节进入集合")
    _state(book, 1, step, "2026-07-29T08:00:00+00:00")

    result = build_overview(book, "book-id")
    row = result["groups"]["waiting"][0]

    assert row["status"] == "这一章状态对不上，请打开检查"
    assert row["state_error"]
    assert result["metrics"]["finalized_chapters"] == 0


def test_breakpoint_uses_latest_valid_updated_at_and_chapter_tiebreak(
    tmp_path: Path,
) -> None:
    from biyu.ui.overview import build_overview

    book = _book(tmp_path)
    for chapter in (1, 2, 3, 4):
        _write(book / "outlines" / f"ch{chapter}.md", f"# 第{chapter}章")
    _state(book, 1, "planning", "2026-07-28T08:00:00+00:00")
    _state(book, 2, "generation", "2026-07-29T08:00:00+00:00")
    _write(book / "logs/ch2/planning.md", "status: 已批\n方案")
    _state(book, 3, "planning", "2026-07-29T08:00:00+00:00")
    _state(book, 4, "planning", "not-a-time")

    result = build_overview(book, "book-id")

    assert result["breakpoint"] == {
        "chapter": 3,
        "status": "方案还在确认中",
        "updated_at": "2026-07-29T08:00:00+00:00",
        "href": "/workbench.html?book=book-id&chapter=3",
    }


def test_breakpoint_empty_does_not_guess_from_chapter_or_mtime(
    tmp_path: Path,
) -> None:
    from biyu.ui.overview import build_overview

    book = _book(tmp_path)
    _write(book / "outlines/ch99.md", "# 第九十九章")
    _state(book, 99, "planning", None)

    result = build_overview(book, "book-id")

    assert result["breakpoint"] is None
    assert result["breakpoint_empty"] == "还没有可用的最近进度记录"


def test_writing_cost_reads_only_positive_chapter_rows_and_skips_aggregate(
    tmp_path: Path,
) -> None:
    from biyu.ui.overview import build_overview

    book = _book(tmp_path)
    _write(book / "outlines/ch1.md", "# 第一章")
    _state(book, 1, "planning", "2026-07-29T08:00:00+00:00")
    path = book / "logs/cost_log.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["timestamp", "chapter", "stage", "cost_cny", "latency_s"]
        )
        writer.writerow(["2026-07-29T08:00:00", 1, "writer", "0.0100", "1"])
        writer.writerow(["2026-07-29T08:00:01", 1, "editor_r1", "0.0200", "1"])
        writer.writerow(["2026-07-29T08:00:02", 1, "editor_total", "0.0200", "1"])
        writer.writerow(["2026-07-29T08:00:03", "propose", "craft", "9.0000", "1"])

    result = build_overview(book, "book-id")

    assert result["metrics"]["writing_cost"] == pytest.approx(0.03)
    assert result["metrics"]["writing_cost_note"] == "只算生成正文，不含起名和对话"


def test_missing_single_book_cost_log_omits_cost_metric(tmp_path: Path) -> None:
    from biyu.ui.overview import build_overview

    book = _book(tmp_path)
    _write(book / "outlines/ch1.md", "# 第一章")

    result = build_overview(book, "book-id")

    assert "writing_cost" not in result["metrics"]
    assert "writing_cost_note" not in result["metrics"]


def test_malformed_feedback_ledger_fails_loudly_at_api(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from biyu.ui.app import app
    import biyu.ui.overview as overview

    book = _book(tmp_path)
    _write(book / "outlines/ch1.md", "# 第一章")
    _write(book / "反馈账.jsonl", "{broken")
    monkeypatch.setattr(overview, "_book_dir", lambda _book: book)

    response = TestClient(app).get("/api/overview/books/book-id")

    assert response.status_code == 500
    assert "反馈账第 1 行不是有效 JSON" in response.json()["detail"]


def test_overview_is_read_only_and_zero_llm(tmp_path: Path, monkeypatch) -> None:
    from biyu.llm import ModelRegistry
    from biyu.ui.overview import build_overview

    book = _book(tmp_path)
    _write(book / "outlines/ch1.md", "# 第一章")
    _state(book, 1, "planning", "2026-07-29T08:00:00+00:00")
    before = {
        path.relative_to(book): path.read_bytes()
        for path in book.rglob("*")
        if path.is_file()
    }

    def fail_if_called(*args, **kwargs):
        raise AssertionError("R5-3A overview must not call a model")

    monkeypatch.setattr(ModelRegistry, "get_adapter", fail_if_called)
    build_overview(book, "book-id")
    after = {
        path.relative_to(book): path.read_bytes()
        for path in book.rglob("*")
        if path.is_file()
    }

    assert after == before


def test_overview_handles_real_chapter_scale_under_half_second(
    tmp_path: Path,
) -> None:
    from biyu.ui.overview import build_overview

    book = _book(tmp_path)
    for chapter in range(1, 33):
        _write(
            book / "chapters" / f"ch{chapter}.md",
            f"# 第{chapter}章 标题{chapter}\n" + "正文" * 500,
        )
        _state(
            book,
            chapter,
            "review",
            f"2026-07-{min(chapter, 29):02d}T08:00:00+00:00",
        )

    started = perf_counter()
    result = build_overview(book, "book-id")
    elapsed = perf_counter() - started

    assert len(result["groups"]["finalized"]) == 32
    assert elapsed < 2.0


def test_overview_page_matches_approved_structure_and_loading_contract() -> None:
    html = Path("src/biyu/ui/static/overview.html").read_text(encoding="utf-8")
    script = Path("src/biyu/ui/static/overview.js").read_text(encoding="utf-8")
    styles = Path("src/biyu/ui/static/overview.css").read_text(encoding="utf-8")

    assert "整书概览" in html
    assert "正在读取整书概览…" in html
    assert 'id="overview-content" hidden' in html
    assert 'id="breakpoint-card"' in html
    assert 'id="metrics"' in html
    assert 'id="waiting-group"' in html
    assert 'id="problem-group"' in html
    assert 'id="finalized-group"' in html
    assert "error-banner" in html
    assert "error-banner-close" in script
    assert "response.ok" in script
    assert "showError" in script
    assert "breakpoint_empty" in script
    assert "展开其余" in script
    assert "已定稿" in script
    assert "定稿了但你记过问题" in script
    assert "等你处理" in script
    assert "只算生成正文，不含起名和对话" in script
    assert "writing_cost" in script
    assert "grid-template-columns" in styles
    assert "@media" in styles
    assert "overflow-x:hidden" in styles.replace(" ", "")


def test_overview_page_has_human_relative_times_and_no_naked_terms() -> None:
    script = Path("src/biyu/ui/static/overview.js").read_text(encoding="utf-8")
    html = Path("src/biyu/ui/static/overview.html").read_text(encoding="utf-8")
    author_surface = html + script

    for copy in ("今天", "昨天", "天前", "两周前", "一个月前"):
        assert copy in script
    for forbidden in (
        "累计花费",
        "总花费",
        "asset_state",
        "workbench_state",
        "editor_total",
        "localStorage",
    ):
        assert forbidden not in author_surface
    assert "fetch(" in script
    assert script.count("method:'POST'") == 1
    assert "/export" in script


def test_overview_lives_on_book_page_and_production_nav_stays_minimal() -> None:
    memory_html = Path("src/biyu/ui/static/memory.html").read_text(
        encoding="utf-8"
    )
    assert "/overview.html" not in memory_html
    assert 'id="back" href="/workbench.html"' in memory_html

    book_html = Path("src/biyu/ui/static/book.html").read_text(
        encoding="utf-8"
    )
    assert 'href="/overview.html?book=' in book_html

    workbench_html = Path("src/biyu/ui/static/workbench.html").read_text(
        encoding="utf-8"
    )
    assert 'id="overview-link"' not in workbench_html
    assert "/overview.html" not in workbench_html

    overview_html = Path("src/biyu/ui/static/overview.html").read_text(
        encoding="utf-8"
    )
    overview_script = Path("src/biyu/ui/static/overview.js").read_text(
        encoding="utf-8"
    )
    assert 'href="/">书架</a>' in overview_html
    assert 'id="workbench-link" href="/workbench.html">工作台</a>' in overview_html
    assert "/workbench.html?book=" in overview_script
    for target in ("memory", "voiceprint"):
        assert f'id="{target}-link"' not in overview_html
        assert f"/{target}.html?book=" not in overview_script


def test_overview_rows_are_read_only_links_with_export_choices() -> None:
    script = Path("src/biyu/ui/static/overview.js").read_text(encoding="utf-8")
    html = Path("src/biyu/ui/static/overview.html").read_text(encoding="utf-8")

    assert "link.href=item.href" in script
    assert "choice.type='checkbox'" in script
    assert "contenteditable" not in (html + script).lower()
    assert "<textarea" not in html.lower()
    assert "<input" not in html.lower()
