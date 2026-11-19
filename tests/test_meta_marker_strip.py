from biyu.pipeline import _strip_meta_markers


def test_keeps_in_text_bracket_terms():
    text = "盯了三四息，字浮出来了：蓝色，【守成】。\n\n【疾】。\n\n他滚了出去。"
    assert _strip_meta_markers(text) == text


def test_strips_echoed_prompt_marker_lines():
    text = "【写作要求】\n他推门进去。\n【Layer 3 结束】\n【本章完】"
    assert _strip_meta_markers(text) == "他推门进去。\n"
