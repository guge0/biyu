"""Tests for meta_vocab auditor."""
from biyu.auditor.meta_vocab import MetaVocabAuditor


def test_non_secret_realm_skips():
    text = "他站在山顶，望着远方。后人记载了他的故事。"
    auditor = MetaVocabAuditor()
    result = auditor.run(text, {"config": {}, "outline": "普通场景", "planning": ""})
    assert "跳过" in result.message or "非秘境" in result.message


def test_secret_realm_detects_meta_vocab():
    text = "曹操冷笑道：'那都是后人编的谎言。'他心中暗想史书不可信。"
    auditor = MetaVocabAuditor()
    result = auditor.run(text, {"config": {}, "outline": "秘境内场景", "planning": ""})
    assert "元词汇" in result.message
    assert result.details.get("violations")


def test_secret_realm_no_violation():
    text = "曹操冷笑道：'那都是说书人瞎编的。'他拔剑向前。"
    auditor = MetaVocabAuditor()
    result = auditor.run(text, {"config": {}, "outline": "秘境内", "planning": ""})
    assert "通过" in result.message
