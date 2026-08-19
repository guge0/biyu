"""Tests for punctuation_density auditor."""
from biyu.auditor.punctuation_density import PunctuationDensityAuditor


def test_no_violation():
    text = "这是一段正常的中文文本。" * 100
    auditor = PunctuationDensityAuditor()
    result = auditor.run(text, {"config": {}})
    assert result.checker == "punctuation_density"
    assert "正常" in result.message


def test_em_dash_violation():
    text = "正文——破折号——很多——内容——测试" * 100
    auditor = PunctuationDensityAuditor()
    result = auditor.run(text, {"config": {}})
    assert result.checker == "punctuation_density"
    assert "破折号" in result.message
    assert result.details["em_dash_per_k"] > 3.0


def test_exclamation_violation():
    text = "他大喊！然后又喊！继续喊！太夸张了！" * 100
    auditor = PunctuationDensityAuditor()
    result = auditor.run(text, {"config": {}})
    assert "感叹号" in result.message


def test_custom_threshold():
    text = "正文——少量" * 200
    auditor = PunctuationDensityAuditor()
    result = auditor.run(text, {"config": {"punctuation_density": {"em_dash_threshold": 0.5}}})
    assert "破折号" in result.message
