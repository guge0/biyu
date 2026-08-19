"""Tests for chapter_ending auditor."""
from biyu.auditor.chapter_ending import ChapterEndingAuditor


def test_short_chapter_skips():
    text = "短文本" * 100  # 300 chars, < 5800
    auditor = ChapterEndingAuditor()
    result = auditor.run(text, {"config": {}})
    assert "过短" in result.message


def test_normal_ending_passes():
    # 前 5000 字和末 800 字不同,总长度 > 5800
    head = "他站在城楼上，看着远方的山峦。远方有连绵起伏的山脉。天空中飘着几朵白云。" * 200
    tail = "夕阳西下，一切归于平静。他转身离去，不再回头。脚步声渐渐消失在暮色中。" * 50
    text = head + tail
    assert len(text) >= 5800
    auditor = ChapterEndingAuditor()
    result = auditor.run(text, {"config": {}})
    assert result.details.get("jaccard") is not None


def test_restart_ending_detected():
    # 构造末尾和前文重复的场景,总长度 > 5800
    repeated = "赤壁之战开始了，火焰吞噬了一切，战船在江面上燃烧。士兵们四散奔逃。" * 40  # ~1200 chars
    middle = "中间段落内容完全不同于此，这里有独特的描述和叙事。没有战争的场景。" * 200  # ~5000 chars
    text = repeated + middle + repeated  # head 和 tail 使用相同内容
    assert len(text) >= 5800
    auditor = ChapterEndingAuditor()
    result = auditor.run(text, {"config": {"chapter_ending": {"jaccard_threshold": 0.3}}})
    assert result.details.get("jaccard") is not None
    assert result.details["jaccard"] > 0.3
