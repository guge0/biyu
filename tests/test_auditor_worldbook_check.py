"""test_auditor_worldbook_check — WorldbookCheckAuditor 单元测试。"""
import pytest

from biyu.auditor.worldbook_check import WorldbookCheckAuditor
from biyu.auditor.base import Severity


class TestWorldbookCheckAuditor:
    def test_no_worldbook(self):
        auditor = WorldbookCheckAuditor()
        ctx = {}
        result = auditor.run("一些正文", ctx)
        assert result.severity == Severity.SKIP
        assert "不存在" in result.message

    def test_protagonist_name_present(self):
        auditor = WorldbookCheckAuditor()
        ctx = {"worldbook": {"facts": ["主角姓名:张今空"]}}
        result = auditor.run("张今空站在那里，望着远方。", ctx)
        assert "未出现" not in result.message

    def test_protagonist_name_missing(self):
        auditor = WorldbookCheckAuditor()
        ctx = {"worldbook": {"facts": ["主角姓名:张今空"]}}
        result = auditor.run("李明站在那里，望着远方。", ctx)
        assert "未出现" in result.message or "漂移" in result.message

    def test_name_property(self):
        auditor = WorldbookCheckAuditor()
        assert auditor.name == "worldbook_check"
