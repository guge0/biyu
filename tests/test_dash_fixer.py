"""Tests for dash_fixer."""
from biyu.postproc.dash_fixer import fix_dashes


def test_保留_对话内戛然停顿():
    text = '\u201c这——\u201d张今空话到嘴边又咽回去了'
    result = fix_dashes(text)
    assert result.fixed_count == 1  # 引号内短句末尾,保留


def test_修复_句末延长():
    text = '洒了江面一片——'
    result = fix_dashes(text)
    assert '——' not in result.fixed_text
    assert result.fixed_text == '洒了江面一片。'


def test_修复_句中补充():
    text = '是物理上的——空气变得滞重'
    result = fix_dashes(text)
    assert result.fixed_text == '是物理上的。空气变得滞重'


def test_修复_等等转折():
    text = '等等——北岸?'
    result = fix_dashes(text)
    assert result.fixed_text == '等等!北岸?'


def test_修复_啊():
    text = '啊——他叫了一声'
    result = fix_dashes(text)
    assert '——' not in result.fixed_text


def test_修复_对话内情绪():
    text = '\u201c卧槽——\u201d周大龙打了个激灵'
    result = fix_dashes(text)
    assert '——' not in result.fixed_text
    assert '卧槽!' in result.fixed_text


def test_整段修复_战斗场景():
    """模拟 ch3 一段。"""
    text = '张今空猛地拽住林溪——空气中传来焦糊味——他知道,火来了。'
    result = fix_dashes(text)
    assert result.fixed_count == 0
    assert '。' in result.fixed_text


def test_密度计算():
    """6.0/千字 输入 → 应该降到 ≤1.5/千字。"""
    text = "他想说——但说不出。她看着他——眼神复杂。风停了——周围安静。" + "测试" * 200
    result = fix_dashes(text)
    char_count = sum(1 for c in result.fixed_text if '\u4e00' <= c <= '\u9fff')
    density = result.fixed_count / (char_count / 1000)
    assert density < 1.5
