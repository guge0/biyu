from __future__ import annotations

from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_first_generation_voiceprint_ui_static_contract() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")

    assert 'id="generation-voiceprint"' in html
    assert "第一次生成正文前" in html
    assert "first_generation" in js
    assert "/api/voiceprint/books/" in js
    assert "/selection" in js
    assert "prepareFirstGenerationVoiceprint" in js
    assert js.count("prepareFirstGenerationVoiceprint") >= 2
    assert js.rindex("prepareFirstGenerationVoiceprint") < js.index('stream("write")')


def test_single_voiceprint_ui_surfaces_author_contracts() -> None:
    html = Path("src/biyu/ui/static/voiceprint.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/voiceprint.js").read_text(encoding="utf-8")

    assert "从导入的作品提取" in html
    assert "先看字数和费用" in html
    assert "最多可能" in js
    assert "提取出的写法（可以逐条修改）" in js
    assert "你改过" in js
    assert all(text in html for text in ("当前生效", "我的声纹", "新建一份"))
    assert all(text in html for text in ("从导入的作品提取", "从本书好坏句蒸馏", "合并已有的几份", "从零手写"))
    assert "data-tab" not in html + js
    assert "data-panel" not in html + js
    assert "设为当前" in js
    assert "来源已有变化，可重合并" in js
    assert "同一维度的不同写法" in html
    assert "上移" not in html + js
    assert "下移" not in html + js
    assert "suppressed" not in html + js
    assert "profile" not in html.lower()
    assert "stance" not in html.lower()
    assert "prohibition" not in html.lower()


def test_first_generation_flag_changes_after_a_candidate_exists(tmp_path: Path) -> None:
    from biyu.ui.workbench import chapter_snapshot
    from biyu.ui.workbench_state import write_workbench_step

    book = tmp_path / "fixture"
    book.mkdir()
    _write(book / "outlines/ch1.md", "# 第一章\n")
    _write(book / "logs/ch1/planning.md", "status: 已批\n方案\n")
    write_workbench_step(book, 1, "generation")

    assert chapter_snapshot(book, 1)["first_generation"] is True

    _write(book / "logs/ch1/candidates/candidate_v1.md", "候选正文")
    _write(
        book / "logs/ch1/candidates/candidate_v1.json",
        '{"version": 1, "created_at": "2026-07-31T12:00:00+00:00"}',
    )
    assert chapter_snapshot(book, 1)["first_generation"] is False
