from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_asset_axis_has_exactly_four_file_derived_values(tmp_path: Path) -> None:
    from biyu.ui.workbench_state import asset_state

    book = tmp_path / "Book"
    assert asset_state(book, 1) == "none"
    official = _write(book / "chapters/ch1.md", "正式")
    assert asset_state(book, 1) == "official"
    pending = _write(book / "chapters/_pending/ch1.md", "候选")
    assert asset_state(book, 1) == "both"
    official.unlink()
    assert asset_state(book, 1) == "candidate"
    pending.unlink()
    assert asset_state(book, 1) == "none"


def test_step_axis_is_durable_and_never_overridden_by_assets(tmp_path: Path) -> None:
    import biyu.ui.workbench as wb
    from biyu.ui.workbench_state import write_workbench_step

    book = tmp_path / "Book"
    _write(book / "outlines/ch1.md", "细纲")
    _write(book / "logs/ch1/planning.md", "status: 待批\n方案")
    write_workbench_step(book, 1, "planning")

    for official, pending, expected_asset in (
        (False, False, "none"),
        (True, False, "official"),
        (False, True, "candidate"),
        (True, True, "both"),
    ):
        official_path = book / "chapters/ch1.md"
        pending_path = book / "chapters/_pending/ch1.md"
        for path, exists, text in ((official_path, official, "正式"), (pending_path, pending, "候选")):
            if exists:
                _write(path, text)
            elif path.exists():
                path.unlink()
        snapshot = wb.chapter_snapshot(book, 1)
        assert snapshot["axes"] == {"asset": expected_asset, "step": "planning", "run": "idle"}
        assert snapshot["stage"] == 1


def test_failure_and_return_to_planning_never_change_asset_axis(tmp_path: Path) -> None:
    import biyu.ui.workbench as wb
    from biyu.ui.workbench_state import write_workbench_step

    book = tmp_path / "Book"
    _write(book / "chapters/ch1.md", "正式")
    _write(book / "chapters/_pending/ch1.md", "候选")
    _write(
        book / "logs/ch1/runs/run_fail.log",
        "run_id=run_fail\naction=write\nstatus=running\n---\nstatus=failed\nreturncode=1\nerror=模型连接中断\n",
    )
    write_workbench_step(book, 1, "generation")

    failed = wb.chapter_snapshot(book, 1)
    assert failed["axes"] == {"asset": "both", "step": "generation", "run": "fail"}
    assert failed["failure_card"]["reason"] == "模型连接中断"

    write_workbench_step(book, 1, "planning")
    returned = wb.chapter_snapshot(book, 1)
    assert returned["axes"]["asset"] == "both"
    assert returned["axes"]["step"] == "planning"


def test_official_no_change_save_is_a_human_noop(tmp_path: Path, monkeypatch) -> None:
    import biyu.ui.workbench as wb
    from biyu.ui.app import app
    from biyu.ui.workbench_state import write_workbench_step

    book = tmp_path / "Book"
    _write(book / "book.json", "{}")
    _write(book / "chapters/ch1.md", "正文完全没有变化")
    write_workbench_step(book, 1, "review")
    monkeypatch.setattr(wb, "get_data_root", lambda: tmp_path)
    client = TestClient(app)
    snapshot = client.get("/api/workbench/books/Book/chapters/1").json()

    response = client.put(
        "/api/workbench/books/Book/chapters/1/chapter",
        json={
            "content": "正文完全没有变化",
            "base_sha": snapshot["chapter_sha"],
            "target": "official",
        },
    )

    assert response.status_code == 200
    assert response.json()["save_notice"] == "没有变化，没有新版本"


def test_three_axis_frontend_has_failure_card_and_no_s_state_dependency() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")

    assert 'id="failure-card"' in html
    assert "current.axes.run" in js
    assert "current.axes.step" in js
    assert "current.state === 'S4'" not in js


def test_snapshot_exposes_central_verdict_layer_and_precise_stage(tmp_path: Path) -> None:
    import biyu.ui.workbench as wb
    from biyu.ui.workbench_state import write_workbench_step

    book = tmp_path / "Book"
    _write(book / "outlines/ch1.md", "细纲")
    expected = {
        "outline": ("细纲层", "细纲"),
        "planning": ("方案层", "写作方案"),
        "generation": ("执笔层", "生成正文"),
        "reading": ("读稿层", "读稿定夺"),
        "revision": ("执笔层", "返修候选稿"),
        "adoption": ("读稿层", "采用正式正文"),
        "review": ("读稿层", "评章摘句"),
    }
    for step, (layer, stage_label) in expected.items():
        write_workbench_step(book, 1, step)
        snapshot = wb.chapter_snapshot(book, 1)
        assert snapshot["layer"] == layer
        assert snapshot["stage_label"] == stage_label


def test_layer_status_is_visible_and_uses_snapshot_with_legacy_fallback() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    script = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
    assert 'id="workbench-layer-status"' in html
    assert 'id="workbench-layer"' in html
    assert 'id="workbench-stage"' in html
    assert "function renderLayerStatus()" in script
    assert "current.layer || STEP_LAYERS[step]" in script
    assert "current.stage_label || STEP_LABELS[step]" in script
