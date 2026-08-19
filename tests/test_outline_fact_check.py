from pathlib import Path

from biyu.outline_fact_reader import check_outline_facts


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _book(tmp_path: Path) -> Path:
    book = tmp_path / "Book"
    _write(book / "characters.yaml", "characters:\n  - name: 沈舟\n    status: dead\n")
    _write(book / "truth_files/history/ch7/current_state.md", "| 沈舟 | 已死 | 北桥身亡 |\n")
    _write(book / "truth_files/history/ch8/pending_hooks.md", "| 雨夜信 | closed | 真相已揭开 |\n")
    return book


def test_outline_check_detects_evidenced_death_and_closed_hook(tmp_path: Path) -> None:
    result = check_outline_facts(_book(tmp_path), "沈舟在酒馆开口说话。\n本章回收雨夜信。")

    assert [item["category"] for item in result["issues"]] == ["角色状态", "未回收伏笔"]
    assert all("第 " in item["evidence"] for item in result["issues"])


def test_outline_check_allows_recollection_and_explains_unavailable_categories(tmp_path: Path) -> None:
    result = check_outline_facts(_book(tmp_path), "沈舟的回忆在酒馆响起。")

    assert not result["issues"]
    unavailable = {item["key"]: item["reason"] for item in result["categories"] if not item["checked"]}
    assert "timeline" in unavailable and "events" in unavailable


def test_outline_check_disconnects_when_the_evidence_history_is_missing(tmp_path: Path) -> None:
    book = _book(tmp_path)
    disconnected = check_outline_facts(book, "沈舟在酒馆开口说话。")
    assert disconnected["issues"]
    for path in (book / "truth_files/history").rglob("*"):
        if path.is_file():
            path.unlink()
    restored_to_missing = check_outline_facts(book, "沈舟在酒馆开口说话。")
    assert not restored_to_missing["issues"]
    _write(book / "truth_files/history/ch7/current_state.md", "| 沈舟 | 已死 | 北桥身亡 |\n")
    restored = check_outline_facts(book, "沈舟在酒馆开口说话。")
    assert restored["issues"]


def test_outline_fact_reader_has_no_model_dependency() -> None:
    source = Path("src/biyu/outline_fact_reader.py").read_text(encoding="utf-8")
    for forbidden in ("adapter", "_call_with_retry", "registry.get_adapter"):
        assert forbidden not in source
