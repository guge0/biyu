"""2026-10 本书/单章花费:统一口径的成本读取与快照注入。

- read_chapter_costs: 按章聚合管线 CSV,跳过聚合行与书级行,坏金额报错
- read_book_extra_cost: 根级 CSV 中属于本书的起名/对话合计,缺文件为 0
- chapter_snapshot 注入 chapter_cost_cny(读稿页「本章共 ¥x.xx」)
"""
from __future__ import annotations

import csv
from pathlib import Path


def _write_pipeline_csv(book: Path, rows: list[list[str]]) -> None:
    path = book / "logs" / "cost_log.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "chapter", "stage", "cost_cny", "latency_s"])
        writer.writerows(rows)


def test_chapter_costs_skip_aggregate_and_book_rows(tmp_path: Path) -> None:
    from biyu.ui.cost_log import read_chapter_costs

    book = tmp_path / "Book"
    _write_pipeline_csv(book, [
        ["2026-10-12T10:00:00", 1, "architect", "0.0600", "12"],
        ["2026-10-12T10:01:00", 1, "writer", "0.0200", "60"],
        ["2026-10-12T10:02:00", 1, "editor_total", "0.0800", "30"],
        ["2026-10-12T10:03:00", 2, "writer", "0.0300", "55"],
        ["2026-10-12T10:04:00", "propose", "craft", "9.0000", "1"],
    ])
    by_chapter = read_chapter_costs(book)
    assert by_chapter is not None
    assert by_chapter[1] == 0.08
    assert by_chapter[2] == 0.03
    assert len(by_chapter) == 2


def test_chapter_costs_missing_file_returns_none(tmp_path: Path) -> None:
    from biyu.ui.cost_log import read_chapter_costs

    assert read_chapter_costs(tmp_path / "Book") is None


def test_book_extra_cost_sums_only_matching_book(tmp_path: Path) -> None:
    from biyu.ui.cost_log import read_book_extra_cost

    root = tmp_path / "root"
    root.mkdir()
    with (root / "cost_log.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ts", "task", "book", "session", "model", "cost"])
        writer.writerow(["2026-10-12T10:00:00", "naming", "mybook", "s1", "v4_flash", "0.0040"])
        writer.writerow(["2026-10-12T10:01:00", "chat", "otherbook", "s2", "v4_flash", "9.0000"])
        writer.writerow(["2026-10-12T10:02:00", "summarize", "mybook", "s3", "v3", "0.0100"])

    assert read_book_extra_cost("mybook", data_root=root) == 0.014
    assert read_book_extra_cost("mybook", data_root=tmp_path / "missing") == 0.0


def test_snapshot_injects_chapter_cost(tmp_path: Path, monkeypatch) -> None:
    from biyu.ui import workbench

    book = tmp_path / "Book"
    (book / "outlines").mkdir(parents=True)
    (book / "logs" / "ch1").mkdir(parents=True)
    (book / "book.json").write_text('{"id":"book","title":"Book","genre":"dushi"}', encoding="utf-8")
    _write_pipeline_csv(book, [
        ["2026-10-12T10:00:00", 1, "architect", "0.0600", "12"],
        ["2026-10-12T10:01:00", 2, "writer", "0.0300", "55"],
    ])
    monkeypatch.setattr(workbench, "_book_dir", lambda _book: book)
    snapshot = workbench.chapter_snapshot(book, 1)
    assert snapshot["chapter_cost_cny"] == 0.06


def test_snapshot_cost_survives_corrupt_log(tmp_path: Path, monkeypatch) -> None:
    """坏台账不应把整个工作台快照打挂:花费归零,页面其余照常。"""
    from biyu.ui import workbench

    book = tmp_path / "Book"
    (book / "outlines").mkdir(parents=True)
    (book / "book.json").write_text('{"id":"book","title":"Book","genre":"dushi"}', encoding="utf-8")
    path = book / "logs" / "cost_log.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("timestamp,chapter,stage,cost_cny,latency_s\n1,1,writer,not-a-number,1\n", encoding="utf-8")
    monkeypatch.setattr(workbench, "_book_dir", lambda _book: book)
    snapshot = workbench.chapter_snapshot(book, 1)
    assert snapshot["chapter_cost_cny"] == 0.0
