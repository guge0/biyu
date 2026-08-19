"""test_wenyan_fixer — WenyanFixer 单元测试。"""
import pytest

from biyu.postproc.wenyan_fixer import fix_wenyan


class TestWenyanFixer:
    def test_replace_yi(self):
        """'他亦去了' -> '他也去了'（亦→也）"""
        result = fix_wenyan("他亦去了")
        assert result.fixed_text == "他也去了"
        assert any(r["from"] == "亦" for r in result.replacements)

    def test_replace_bian(self):
        """'便走了' -> '就走了'"""
        result = fix_wenyan("便走了")
        assert result.fixed_text == "就走了"
        assert any(r["from"] == "便" for r in result.replacements)

    def test_protect_quotes_in_secret_realm(self):
        """秘境内:引号内'吾乃曹孟德也'保留"""
        text = '"吾乃曹孟德也"他介绍道。'
        result = fix_wenyan(text, in_secret_realm=True)
        # 引号内的"吾"和"乃"应保留
        assert '"吾乃曹孟德也"' in result.fixed_text

    def test_replace_outside_quotes_in_secret_realm(self):
        """秘境内:叙述中'他亦举刀'应替换"""
        text = "他亦举刀斩去。"
        result = fix_wenyan(text, in_secret_realm=True)
        assert "他也举刀斩去。" == result.fixed_text

    def test_preserve_que(self):
        """'却'和'则'不替换(保留)"""
        result = fix_wenyan("他却不知此事，则是另一回事")
        assert "却" in result.fixed_text
        assert "则" in result.fixed_text

    def test_no_wenyan_words(self):
        """无文言词时不替换"""
        text = "他看到前面有个人走过来了"
        result = fix_wenyan(text)
        assert result.fixed_text == text
        assert len(result.replacements) == 0
