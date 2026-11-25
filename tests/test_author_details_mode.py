"""S-9「人定细节」开关：book.json 的 author_details_locked，默认关。"""
import json

from biyu.prompts.chapter_writer import build_writer_prompt_v4
from biyu.prompts.director_prompt import build_planning_prompt
from biyu.ui.workbench import _author_details_locked


def _writer(**kw):
    return build_writer_prompt_v4(
        chapter_num=1, worldbook={}, worldbook_prompt="", characters=[],
        truth_files_block="", prev_tail="", context_block="", outline="方案", planning="", **kw,
    )


def test_writer_default_has_no_details_rule():
    system, _ = _writer()
    assert "作者定了细节" not in system


def test_writer_locked_appends_details_rule():
    system, _ = _writer(author_details_locked=True)
    assert "作者定了细节" in system
    assert system.index("只输出正文") < system.index("作者定了细节")


def test_director_locked_adds_rule_only_when_on():
    assert "亲自定了细节" not in build_planning_prompt(outline="x", chapter_num=1)
    assert "亲自定了细节" in build_planning_prompt(outline="x", chapter_num=1, author_details_locked=True)


def test_book_flag_reader(tmp_path):
    assert _author_details_locked(tmp_path) is False
    (tmp_path / "book.json").write_text(json.dumps({"author_details_locked": True}), encoding="utf-8")
    assert _author_details_locked(tmp_path) is True
    (tmp_path / "book.json").write_text("{坏", encoding="utf-8")
    assert _author_details_locked(tmp_path) is False
