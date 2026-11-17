"""S-6 · 报告 PDF 解析与窗口映射(对「已抽出的文本行」的纯函数单测,不碰真 PDF)。"""
from __future__ import annotations

from biyu.zhuque.report_pdf import map_scores_to_windows, parse_fragments

# 模拟 pypdf 从朱雀报告单抽出的文本行:页眉页脚/表头/图例 + 两个片段
RAW = "\n".join([
    "2026/11/15 10:23",
    "朱雀AI生成检测报告单",
    "https://matrix.tencent.com/ai-detect/ai_gen",
    "1/3",
    "第1页 共3页",
    "NO. 2026111510",
    "检测时间",
    "2026/11/15 10:20:01",
    "检测结果",
    "AI分布图",
    "片段解析",
    "检测片段详情",
    "序号",
    "片段",
    "占全文比例",
    "占字符数",
    "AIGC值",
    "片段1 AIGC值 0.9123",
    "片段1",
    "12.5%",
    "320",
    "0.9123",
    "夜色深沉，南城旧武馆的后院里静得可怕，张今空站在石阶旁，",
    "嘴角勾起一抹三分薄凉七分讥诮的弧度，眼神微眯透出危险的气息，",
    "某种意义上来说，昨晚那场死亡回溯的阴影似乎还在他心头萦绕。",
    "片段2 AIGC值 0.1024",
    "片段2",
    "8.1%",
    "210",
    "0.1024",
    "方圆端着茶碗走过来，她的身影在月光下宛如一尊凝固的雕塑，",
    "张今空心里仿佛闪过一丝莫名的悲凉，却只是缓缓低头擦刀。",
    "人工特征 (82%)",
    "疑似AI (6%)",
    "AI特征 (12%)",
])


def test_parse_fragments_extracts_number_text_value() -> None:
    fragments = parse_fragments(RAW)
    assert [f["no"] for f in fragments] == [1, 2]
    assert [f["score"] for f in fragments] == [0.9123, 0.1024]
    text1 = fragments[0]["text"]
    assert "夜色深沉" in text1 and "萦绕" in text1
    assert "方圆" not in text1
    text2 = fragments[1]["text"]
    assert "方圆" in text2 and "擦刀" in text2
    assert "夜色深沉" not in text2


def test_parse_fragments_drops_furniture_lines() -> None:
    """页码/NO./占比/图例等家具行不得混进片段正文。"""
    fragments = parse_fragments(RAW)
    all_text = "\n".join(f["text"] for f in fragments)
    for furniture in ("报告单", "matrix.tencent", "第1页", "NO.", "12.5%", "0.9123",
                      "人工特征", "AI分布图", "片段解析", "AIGC值"):
        assert furniture not in all_text, furniture


def test_parse_fragments_empty_or_markerless() -> None:
    assert parse_fragments("") == []
    assert parse_fragments("没有任何标记的普通文本\n第二行") == []


def test_map_scores_ordered_windows() -> None:
    fragments = [
        {"no": 1, "score": 0.9, "text": "ABCD"},
        {"no": 2, "score": 0.1, "text": "EFGH"},
    ]
    windows = [
        {"order": 1, "start": 0, "end": 2, "text": "AB"},
        {"order": 2, "start": 2, "end": 4, "text": "CD"},
        {"order": 3, "start": 4, "end": 8, "text": "EFGH"},
    ]
    mapped = map_scores_to_windows(fragments, windows)
    assert mapped[0] == {"score": 0.9, "fragment": 1}
    assert mapped[1] == {"score": 0.9, "fragment": 1}
    assert mapped[2] == {"score": 0.1, "fragment": 2}


def test_map_scores_takes_worst_when_window_spans_fragments() -> None:
    """一窗横跨两个片段时取更差(更高)的 AIGC 值,不哄作者。"""
    fragments = [
        {"no": 1, "score": 0.3, "text": "ABC"},
        {"no": 2, "score": 0.8, "text": "DEF"},
    ]
    windows = [{"order": 1, "start": 0, "end": 6, "text": "BCDE"}]
    assert map_scores_to_windows(fragments, windows)[0]["score"] == 0.8


def test_map_scores_normalizes_whitespace() -> None:
    fragments = [{"no": 1, "score": 0.5, "text": "夜色深沉，\n南城旧武馆"}]
    windows = [{"order": 1, "start": 0, "end": 9, "text": "夜色深沉， 南城旧武馆"}]
    assert map_scores_to_windows(fragments, windows)[0]["score"] == 0.5


def test_map_scores_unmatched_window_is_none() -> None:
    fragments = [{"no": 1, "score": 0.5, "text": "ABCD"}]
    windows = [{"order": 1, "start": 0, "end": 4, "text": "完全对不上"}]
    assert map_scores_to_windows(fragments, windows)[0] == {"score": None, "fragment": None}


def test_map_scores_empty_inputs() -> None:
    assert map_scores_to_windows([], []) == []
    windows = [{"order": 1, "start": 0, "end": 2, "text": "AB"}]
    assert map_scores_to_windows([], windows) == [{"score": None, "fragment": None}]
