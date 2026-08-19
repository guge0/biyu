from pathlib import Path


def test_outline_fact_cards_are_nonblocking_and_explain_coverage() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    script = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
    reader = Path("src/biyu/outline_fact_reader.py").read_text(encoding="utf-8")

    assert 'id="outline-fact-status"' in html
    assert "renderOutlineFactCheck" in script
    assert "和前面对不上" in script
    assert "我知道，继续" in script
    assert "回去改这一条" in script
    assert "改记忆" not in script
    assert "checked" in script and "reason" in script
    assert "这本书目前还没有带章节依据的死亡记录；有死亡记录后会自动检查" in reader
    assert "这类记录还不是机器能读准的格式" in reader


def test_outline_save_still_advances_with_a_fact_warning(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    import biyu.ui.workbench as workbench
    from biyu.ui.app import app

    book = tmp_path / "Book"
    (book / "outlines").mkdir(parents=True)
    (book / "book.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)
    response = TestClient(app).put(
        "/api/workbench/books/Book/chapters/1/outline",
        json={"content": "有矛盾的细纲", "base_sha": ""},
    )
    assert response.status_code == 200
    assert response.json()["axes"]["step"] == "planning"
