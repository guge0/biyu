"""Tests for dialogue_ratio auditor."""
from biyu.auditor.dialogue_ratio import DialogueRatioAuditor


def test_normal_ratio():
    text = "他走进了房间，环顾四周。墙上挂着画，桌上放着茶杯。" * 50
    auditor = DialogueRatioAuditor()
    result = auditor.run(text, {"config": {}})
    assert "正常" in result.message


def test_high_dialogue_ratio():
    dialogue = "\u201c你怎么来了？\u201d\n\u201c我来找你。\u201d\n\u201c什么事？\u201d\n\u201c大事。\u201d\n"
    narration = "他点点头。" * 5
    text = (dialogue * 20) + narration
    auditor = DialogueRatioAuditor()
    result = auditor.run(text, {"config": {}})
    assert "对话" in result.message


def test_no_chinese_chars():
    text = "hello world 123"
    auditor = DialogueRatioAuditor()
    result = auditor.run(text, {"config": {}})
    assert "无中文" in result.message


def test_custom_threshold():
    text = "正文内容\u201c对话\u201d" * 50
    auditor = DialogueRatioAuditor()
    result = auditor.run(text, {"config": {"dialogue_ratio": {"ratio_threshold": 0.1}}})
    assert "对话" in result.message
