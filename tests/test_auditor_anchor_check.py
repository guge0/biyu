"""Tests for AnchorCheckAuditor — P6-A2 正文层转正。"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from biyu.auditor.anchor_check import AnchorCheckAuditor
from biyu.auditor.base import Severity


@pytest.fixture()
def book_with_anchors(tmp_path):
    """临时书目录, 含 anchors.yaml(T1 一个锚 + distractor)。"""
    data = {
        "T1": {
            "atomic": [
                {
                    "id": "T1-H16", "type": "数字", "canonical": "A-113",
                    "aliases": ["A113"], "mismatch_aliases": ["A-131"],
                },
                {
                    "id": "T1-H14", "type": "地点", "canonical": "市档案馆三楼",
                    "aliases": ["档案馆三楼"],
                },
            ],
        }
    }
    (tmp_path / "anchors.yaml").write_text(
        yaml.dump(data, allow_unicode=True), encoding="utf-8"
    )
    return tmp_path


class TestAnchorCheckAuditor:
    def test_name(self):
        assert AnchorCheckAuditor().name == "anchor_check"

    def test_value_mismatch_is_block(self, book_with_anchors):
        """正文出现错值 distractor → BLOCK(事实矛盾, 需人审)。"""
        ctx = {"book_dir": str(book_with_anchors), "chapter_num": 1}
        text = "他翻到案卷编号A-131,在市档案馆三楼查阅。"
        result = AnchorCheckAuditor().run(text, ctx)
        assert result.severity == Severity.BLOCK
        assert result.checker == "anchor_check"
        # 详情带三态计数
        assert result.details["value_mismatch"] >= 1
        assert result.details["mismatches"]

    def test_all_present_is_warn_pass(self, book_with_anchors):
        """全部锚点在场(无错值) → WARN 通过。"""
        ctx = {"book_dir": str(book_with_anchors), "chapter_num": 1}
        text = "案卷A-113就存放在市档案馆三楼。"
        result = AnchorCheckAuditor().run(text, ctx)
        assert result.severity == Severity.PASS
        assert result.details["value_mismatch"] == 0

    def test_missing_only_is_warn(self, book_with_anchors):
        """有缺失但无错值 → WARN(漏提, 非矛盾)。"""
        ctx = {"book_dir": str(book_with_anchors), "chapter_num": 1}
        text = "他在街上漫无目的地走,什么也没提。"
        result = AnchorCheckAuditor().run(text, ctx)
        assert result.severity == Severity.WARN
        assert result.details["missing"] >= 1
        assert result.details["value_mismatch"] == 0

    def test_no_anchors_yaml_skips_gracefully(self, tmp_path):
        """书目录无 anchors.yaml → WARN 跳过, 不抛异常。"""
        ctx = {"book_dir": str(tmp_path), "chapter_num": 1}
        result = AnchorCheckAuditor().run("任意正文", ctx)
        assert result.severity == Severity.SKIP
        assert "跳过" in result.message or "无" in result.message

    def test_explicit_anchors_path_override(self, book_with_anchors, tmp_path):
        """ctx/config 指定 anchors_path 时优先用它(支持 eval 集中放 anchors)。"""
        elsewhere = tmp_path / "eval_anchors.yaml"
        data = {
            "T1": {
                "atomic": [
                    {"id": "X1", "type": "设定", "canonical": "黑色手套",
                     "aliases": [], "mismatch_aliases": ["白手套"]},
                ]
            }
        }
        elsewhere.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
        ctx = {
            "book_dir": str(book_with_anchors),
            "chapter_num": 1,
            "anchor_check": {"anchors_path": str(elsewhere)},
        }
        result = AnchorCheckAuditor().run("他戴着白手套", ctx)
        assert result.severity == Severity.BLOCK
        assert result.details["value_mismatch"] == 1

    def test_chapter_key_map(self, book_with_anchors):
        """chapter_key_map 显式映射 chapter_num → T-key。"""
        ctx = {
            "book_dir": str(book_with_anchors),
            "chapter_num": 5,
            "anchor_check": {"chapter_key_map": {5: "T1"}},
        }
        result = AnchorCheckAuditor().run("案卷A-131在市档案馆三楼", ctx)
        # chapter 5 → T1, 命中 A-131 distractor
        assert result.severity == Severity.BLOCK
