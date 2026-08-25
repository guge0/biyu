from __future__ import annotations

from pathlib import Path
import json

from fastapi.testclient import TestClient
from tests.support.workbench_assets import assert_workbench_js_src


def test_workbench_accepts_product_book_id_and_lists_identity(tmp_path, monkeypatch) -> None:
    from biyu.ui.app import app
    import biyu.ui.workbench as workbench

    book = tmp_path / "book-directory"
    book.mkdir()
    (book / "book.json").write_text(
        json.dumps({"id": "stable-book-id", "display_name": "Visible Book"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)
    client = TestClient(app)

    listed = client.get("/api/workbench/books").json()["books"]
    assert listed == [{
        "name": "book-directory",
        "id": "stable-book-id",
        "display_name": "Visible Book",
    }]
    assert client.get("/api/workbench/books/stable-book-id/chapters/1").status_code == 200


def test_workbench_frontend_selects_product_book_id() -> None:
    script = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")

    assert "new Option(b.display_name,b.id" in script
    assert "b.id===wanted" in script


def test_pending_wins_and_planning_save_cannot_steal_status(tmp_path, monkeypatch) -> None:
    from biyu.ui.app import app
    import biyu.ui.workbench as workbench

    book = tmp_path / "Book"
    (book / "outlines").mkdir(parents=True)
    (book / "outlines" / "ch1.md").write_text("细纲", encoding="utf-8")
    (book / "chapters" / "_pending").mkdir(parents=True)
    (book / "chapters" / "ch1.md").write_text("正式正文", encoding="utf-8")
    (book / "chapters" / "_pending" / "ch1.md").write_text("待收正文", encoding="utf-8")
    planning = book / "logs" / "ch1" / "planning.md"
    planning.parent.mkdir(parents=True)
    planning.write_text("status: 待批\n旧正文", encoding="utf-8")
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)
    client = TestClient(app)

    snap = client.get("/api/workbench/books/Book/chapters/1").json()
    assert snap["chapter_text"] == "待收正文"
    # 九号裁定：候选生成后立即回到读稿与批注，不被待批方案遮住。
    assert snap["axes"]["asset"] == "both"
    assert snap["axes"]["step"] == "reading"
    saved = client.put("/api/workbench/books/Book/chapters/1/planning", json={"content": "status: 已批\n老板红笔"})
    assert saved.status_code == 200
    assert planning.read_text(encoding="utf-8") == "status: 待批\nsource: 作者改过\n老板红笔"


def test_action_registry_requires_a_real_confirmation_before_approve() -> None:
    from biyu.ui.action_registry import action_for

    action = action_for("approve_chapter", book="Book", chapter=1)
    assert action.confirm is True
    assert action.stdin_after_confirm == "y\n"


def test_cli_executor_never_imports_pipeline_editor_or_writer() -> None:
    """雷3：工作台只能启动 CLI，不能直连业务模块。"""
    source = Path("src/biyu/ui/cli_executor.py").read_text(encoding="utf-8")

    for forbidden in (
        "from biyu.pipeline import",
        "from biyu.editor import",
        "from biyu.writer import",
    ):
        assert forbidden not in source
    assert '"from biyu.cli.main import app; app()"' in source


def test_product_has_one_fixed_author_launcher() -> None:
    assert not Path("工作台.bat").exists()
    assert not Path("start_biyu_ui_dev.bat").exists()
    text = Path("start_biyu_ui.bat").read_text(encoding="ascii")
    assert "-Port 8080" in text
    assert "-Mode" not in text
    assert "8080,1,8089" not in text


def test_normal_pages_link_to_the_generic_workbench() -> None:
    index = Path("src/biyu/ui/static/index.html").read_text(encoding="utf-8")
    detail = Path("src/biyu/ui/static/book.html").read_text(encoding="utf-8")
    app_script = Path("src/biyu/ui/static/app.js").read_text(encoding="utf-8")

    assert '<a href="/workbench.html">工作台</a>' in index
    assert 'href="/workbench.html?book=' in detail
    assert 'link.href = "/workbench.html?book="' in app_script


def test_workbench_entry_is_self_explanatory_and_has_a_visible_read_receipt() -> None:
    """§八B：老板不必猜“第 2 步”在哪，也能看见读取是否成功。"""
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    script = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")

    assert 'id="entry-status"' in html
    assert 'id="stage-bar"' in html
    assert 'id="stage-shell"' in html
    assert "书籍" in html
    assert "读取此章" not in html
    assert_workbench_js_src(html)
    for label in ("继续改现有候选稿", "归档候选稿，按新方案重写", "暂不确认"):
        assert label in html
    assert "细纲" in script
    assert "写作方案" in script
    assert "已读取第" in script
    assert "正在读取本章…" in script


def test_snapshot_derives_a_single_next_step_from_files(tmp_path, monkeypatch) -> None:
    import biyu.ui.workbench as workbench

    book = tmp_path / "Book"
    book.mkdir()
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)

    assert workbench.chapter_snapshot(book, 1)["next_step"]["id"] == "prefill_outline"
    (book / "outlines").mkdir()
    (book / "outlines" / "ch1.md").write_text("细纲", encoding="utf-8")
    assert workbench.chapter_snapshot(book, 1)["next_step"]["id"] == "talk"
    planning = book / "logs" / "ch1" / "planning.md"
    planning.parent.mkdir(parents=True)
    planning.write_text("status: 待批\n合同", encoding="utf-8")
    assert workbench.chapter_snapshot(book, 1)["next_step"]["id"] == "approve_planning"


def test_outline_template_refuses_to_overwrite_existing_outline(tmp_path, monkeypatch) -> None:
    from biyu.ui.app import app
    import biyu.ui.workbench as workbench

    book = tmp_path / "Book"
    outline = book / "outlines" / "ch1.md"
    outline.parent.mkdir(parents=True)
    outline.write_text("老板已有细纲", encoding="utf-8")
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)

    response = TestClient(app).get("/api/workbench/books/Book/chapters/1/outline-template")
    assert response.status_code == 409
    assert "已有细纲" in response.json()["detail"]


def test_snapshot_reads_back_verdict_destinations_and_candidate_counts(tmp_path, monkeypatch) -> None:
    import biyu.ui.workbench as workbench

    book = tmp_path / "Book"
    verdict = book / "判词" / "ch1.md"
    positive = book / "样本库" / "正例候选.md"
    verdict.parent.mkdir(parents=True)
    positive.parent.mkdir(parents=True)
    verdict.write_text("- 判词\n", encoding="utf-8")
    positive.write_text("- 好段\n", encoding="utf-8")
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)

    receipt = workbench.chapter_snapshot(book, 1)["verdict_receipt"]
    assert receipt["verdict_path"].replace("\\", "/").endswith("判词/ch1.md")
    assert receipt["positive_count"] == 1
    assert receipt["negative_count"] == 0


def test_workbench_uses_server_detail_for_in_place_conflict_guidance() -> None:
    script = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")

    assert "body.detail" in script
    assert "盘面出现了新版本" in script
    assert "当前内容不会被改写" in script
