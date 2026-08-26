from __future__ import annotations

from pathlib import Path

import pytest

from tools import check_dataroot


def _source_tree(root: Path) -> None:
    config = root / "src/biyu/config.py"
    trace = root / "src/biyu/editor/multi_agent.py"
    backup = root / "src/biyu/backup_service.py"
    config.parent.mkdir(parents=True)
    trace.parent.mkdir(parents=True)
    backup.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        'def get_data_root():\n    raise RuntimeError("测试进程禁止使用生产数据根")\n',
        encoding="utf-8",
    )
    trace.write_text(
        'trace_dir = Path(book_dir).resolve() / "phase_trace"\n',
        encoding="utf-8",
    )
    backup.write_text(
        'manifest = {"source_path": str(source.resolve())}\n',
        encoding="utf-8",
    )


@pytest.fixture
def checker_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "checkout"
    _source_tree(root)
    monkeypatch.setattr(check_dataroot, "ROOT", root)
    return root


def test_checker_is_green_for_a_clean_production_root(checker_root: Path, tmp_path: Path):
    production = tmp_path / "production"
    book = production / "book-one"
    book.mkdir(parents=True)
    (book / "book.json").write_text("{}", encoding="utf-8")

    results = check_dataroot.collect_results({
        "BIYU_DATA_ROOT": str(production),
        "BIYU_RUNTIME_ROLE": "production",
    })

    assert {result.status for result in results} == {check_dataroot.GREEN}
    assert check_dataroot.exit_code(results) == 0


def test_checker_reports_missing_root_as_red_and_production_scan_as_not_done(
    checker_root: Path,
):
    results = check_dataroot.collect_results({"BIYU_RUNTIME_ROLE": "production"})

    assert results[0] == check_dataroot.Result(
        "显式数据根",
        check_dataroot.RED,
        "environment:BIYU_DATA_ROOT 未设置",
    )
    assert results[-1].status == check_dataroot.NOT_DONE
    assert check_dataroot.exit_code(results) == 1


def test_checker_marks_production_scan_not_done_outside_production(
    checker_root: Path,
    tmp_path: Path,
):
    results = check_dataroot.collect_results({
        "BIYU_DATA_ROOT": str(tmp_path),
        "BIYU_RUNTIME_ROLE": "development",
    })

    assert results[-1].status == check_dataroot.NOT_DONE
    assert "BIYU_RUNTIME_ROLE=development" in results[-1].detail
    assert check_dataroot.exit_code(results) == 0


def test_checker_reports_each_non_book_directory_path(checker_root: Path, tmp_path: Path):
    production = tmp_path / "production"
    stray = production / "phase_trace"
    stray.mkdir(parents=True)

    results = check_dataroot.collect_results({
        "BIYU_DATA_ROOT": str(production),
        "BIYU_RUNTIME_ROLE": "production",
    })

    assert results[-1].status == check_dataroot.RED
    assert str(stray) in results[-1].detail
    assert check_dataroot.exit_code(results) == 1


def test_checker_red_source_result_includes_file_and_line(
    checker_root: Path,
    tmp_path: Path,
):
    config = checker_root / "src/biyu/config.py"
    config.write_text('root = Path.home() / "BiyuData"\n', encoding="utf-8")

    results = check_dataroot.collect_results({
        "BIYU_DATA_ROOT": str(tmp_path),
        "BIYU_RUNTIME_ROLE": "production",
    })

    fallback = next(result for result in results if result.name == "禁止生产根回落")
    assert fallback.status == check_dataroot.RED
    assert fallback.detail.startswith("src/biyu/config.py:1 ")
