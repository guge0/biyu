"""核对筛选引擎测试（边界样例、新问法、代词消歧与核心动作）。

F-4 相对 F-3 的改动:
- 视角类复筛改问「不可观察信息」(内心活动/感受/视角人物无法观察的信息),抽片段,答「无」剔除
- 代词消歧:抽取片段含代词必须给 referent;referent=视角人物或不明 → 剔除 + ambiguous 计数
- 非视角类加严:抽取片段必须满足核心动作(解释性陈述/结构性说明),光名词不算;core_action 复述落盘
- md 页眉固定说明:「本表是提示,不是判决」
"""
from __future__ import annotations

import asyncio
import json

import pytest

from biyu.checklist.f4_engine import (
    judge_checklist_f4,
    parse_viewpoint_person,
    render_markdown_f4,
)
from biyu.checklist.parser import parse_checklist
from biyu.llm.base import LLMResponse

PLANNING = """# ch1 戏核

## 必检项

**必须发生**
- 江奇在告示板前拦住豁口佣兵队，说出"心脏不在左胸，在左肋第三道鳞缝之后"
- 姜聆以协会公示的验尸通报为证，当众确认江奇的伤口细节属实

**必须不发生**
- 不出现江奇以外的视角（全章只能落在他的感知内）
- 不在这章解答回溯的原因、代价或循环的目的

**结尾状态**
- 江奇站在拾荒协会门前告示板下，身体无伤

**信息层级**
- 江奇的"死过一次"及回溯能力：在告示板前公开说出；但无人相信复活之说
"""

BODY = (
    "江奇站在告示板下。秦岳回头看了江奇一眼。"
    "她看见江奇的嘴动了动，没有声音。"
    "马文抬手擦了擦汗。"
)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FakeAdapter:
    def __init__(self, responses, name="v3-fake", cost=0.02):
        self.responses = list(responses)
        self.name = name
        self.cost = cost
        self.calls = []

    async def generate(self, messages, **kwargs):
        self.calls.append(messages)
        text = self.responses.pop(0)
        if isinstance(text, Exception):
            raise text
        return LLMResponse(text=text, model=self.name, cost=self.cost)


# ---------- 响应构造 ----------

def _decompose_resp():
    return json.dumps([{"index": i, "question": f"第{i}条成立吗?"} for i in range(6)], ensure_ascii=False)


def _positive_resp(indexes, verdict="met", quotes=None):
    return json.dumps([
        {"index": i, "text": f"第{i}条原文",
         "components": [{"question": f"第{i}条成立吗?", "verdict": verdict, "quotes": quotes or [BODY[:8]]}],
         "verdict": verdict, "quotes": quotes or [BODY[:8]], "reason": "成立"} for i in indexes
    ], ensure_ascii=False)


def _neg_resp(quotes):
    return json.dumps({"quotes": quotes}, ensure_ascii=False)


def _screen_resp(screened, core_action="核心动作"):
    return json.dumps({"core_action": core_action, "screened": screened}, ensure_ascii=False)


def default_responses():
    """8 次调用(6 条):拆解1 + 正向3 + 枚举2 + 复筛2(按调用顺序交错)。"""
    return [
        _decompose_resp(),
        _positive_resp([0, 1]),
        _positive_resp([4]),
        _positive_resp([5]),
        _neg_resp([]),   # 枚举#2(视角)
        _screen_resp([]),  # 复筛#2
        _neg_resp([]),   # 枚举#3(回溯)
        _screen_resp([]),  # 复筛#3
    ]


def judge(spec, body=BODY, responses=None):
    adapter = FakeAdapter(responses or default_responses())
    return run(judge_checklist_f4(spec, body, adapter, version="t1")), adapter


def spec_of():
    return parse_checklist(PLANNING)


def neg_items(result):
    return [i for i in result.items if i.category == "must_not_happen"]


# ---------- 视角类新问法(6.5 雷7) ----------

def test_雷7_action_sentence_removed():
    """动作句(秦岳回头看了江奇一眼)→ 模型抽取「无」→ 剔除 → met。"""
    r = default_responses()
    r[4] = _neg_resp(["秦岳回头看了江奇一眼。"])
    r[5] = _screen_resp([{"quote": "秦岳回头看了江奇一眼。", "extracted": "无", "referent": "", "keep": False}],
                        core_action="不出现江奇以外的视角")
    result, _ = judge(spec_of(), responses=r)
    item = neg_items(result)[0]
    assert item.verdict == "met"
    assert item.quotes == []


def test_viewpoint_keeps_unobservable_info():
    """「她看见江奇的嘴动了动」→ 抽取「她看见」→ 保留 → unmet。"""
    r = default_responses()
    r[4] = _neg_resp(["她看见江奇的嘴动了动，没有声音。"])
    r[5] = _screen_resp([{"quote": "她看见江奇的嘴动了动，没有声音。", "extracted": "她看见", "referent": "姜聆", "keep": True}],
                        core_action="不出现江奇以外的视角")
    result, _ = judge(spec_of(), responses=r)
    item = neg_items(result)[0]
    assert item.verdict == "unmet"
    assert item.quotes == ["她看见江奇的嘴动了动，没有声音。"]


# ---------- 代词消歧(6.5 雷8) ----------

def test_雷8_pronoun_referent_viewpoint_removed_ambiguous():
    """代词「他」指视角人物 → 剔除并计入 ambiguous。"""
    body2 = BODY + "熊腹腔就在他眼前。肋骨背面的黑色肉团还在泵血。"
    r = default_responses()
    r[4] = _neg_resp(["熊腹腔就在他眼前。肋骨背面的黑色肉团还在泵血。"])
    r[5] = _screen_resp([{"quote": "熊腹腔就在他眼前。肋骨背面的黑色肉团还在泵血。",
                          "extracted": "他眼前", "referent": "江奇", "keep": True}],
                        core_action="不出现江奇以外的视角")
    result, _ = judge(spec_of(), body=body2, responses=r)
    item = neg_items(result)[0]
    assert item.verdict == "met"  # 剔除(指代=视角人物)
    assert item.negative_screening.ambiguous == 0  # 指代明确,不计 ambiguous


def test_pronoun_unresolved_removed_ambiguous():
    """指代不明 → 剔除并计入 ambiguous(不判违规)。"""
    body2 = BODY + "他四十出头，左眉骨上有一道旧疤。"
    r = default_responses()
    r[4] = _neg_resp(["他四十出头，左眉骨上有一道旧疤。"])
    r[5] = _screen_resp([{"quote": "他四十出头，左眉骨上有一道旧疤。",
                          "extracted": "他", "referent": "", "keep": True}],
                        core_action="不出现江奇以外的视角")
    result, _ = judge(spec_of(), body=body2, responses=r)
    item = neg_items(result)[0]
    assert item.verdict == "met"
    assert item.negative_screening.ambiguous == 1


def test_pronoun_referent_other_kept():
    """代词指代他人(姜聆)→ 保留 → unmet。"""
    r = default_responses()
    r[4] = _neg_resp(["她看见江奇的嘴动了动，没有声音。"])
    r[5] = _screen_resp([{"quote": "她看见江奇的嘴动了动，没有声音。",
                          "extracted": "她看见", "referent": "姜聆", "keep": True}],
                        core_action="不出现江奇以外的视角")
    result, _ = judge(spec_of(), responses=r)
    item = neg_items(result)[0]
    assert item.verdict == "unmet"
    assert item.negative_screening.ambiguous == 0


# ---------- 非视角类加严(6.2 依据) ----------

def test_core_action_recorded():
    """core_action 复述必须落盘。"""
    r = default_responses()
    r[6] = _neg_resp(["马文抬手擦了擦汗。"])
    r[7] = _screen_resp([{"quote": "马文抬手擦了擦汗。", "extracted": "无", "referent": "", "keep": False}],
                        core_action="解释回溯发生的原因、代价或目的")
    result, _ = judge(spec_of(), responses=r)
    item = neg_items(result)[1]
    assert item.negative_screening.core_action == "解释回溯发生的原因、代价或目的"


def test_phenomenon_statement_not_kept():
    """现象陈述(「我死过一次」)不算解答原因 → 模型 keep=false → met。"""
    r = default_responses()
    r[6] = _neg_resp(["我死过一次。"])
    r[7] = _screen_resp([{"quote": "我死过一次。", "extracted": "无", "referent": "", "keep": False}],
                        core_action="解释回溯发生的原因、代价或目的")
    result, _ = judge(spec_of(), responses=r)
    item = neg_items(result)[1]
    assert item.verdict == "met"


def test_explanation_statement_kept():
    """解释性陈述(因为…造成)→ keep=true → unmet。"""
    body2 = BODY + "因为他死过一次，所以回溯才发生。"
    r = default_responses()
    r[6] = _neg_resp(["因为他死过一次，所以回溯才发生。"])
    r[7] = _screen_resp([{"quote": "因为他死过一次，所以回溯才发生。", "extracted": "所以回溯才发生",
                          "referent": "", "keep": True}],
                        core_action="解释回溯发生的原因、代价或目的")
    result, _ = judge(spec_of(), body=body2, responses=r)
    item = neg_items(result)[1]
    assert item.verdict == "unmet"


# ---------- F-3 六雷保留 ----------

def test_雷1_positive_unmet_empty_quotes_kept():
    r = default_responses()
    r[1] = _positive_resp([0, 1], verdict="unmet", quotes=[])
    result, _ = judge(spec_of(), responses=r)
    assert result.items[0].verdict == "unmet"


def test_雷2_different_wording_met_kept():
    r = default_responses()
    r[1] = _positive_resp([0, 1], quotes=["马文抬手擦了擦汗。"])
    result, _ = judge(spec_of(), responses=r)
    assert result.items[0].verdict == "met"


def test_雷3_fabricated_quote_invalid():
    r = default_responses()
    r[1] = json.dumps([
        {"index": 0, "text": "第0条原文",
         "components": [{"question": "第0条成立吗?", "verdict": "met", "quotes": ["编造"]}],
         "verdict": "met", "quotes": ["马文抬手擦了擦汗。"], "reason": "成立"},
    ], ensure_ascii=False)
    r.insert(2, json.dumps({"index": 0, "text": "第0条原文", "verdict": "met", "quotes": ["还是编造"], "reason": "成立"},
                           ensure_ascii=False))
    result, _ = judge(spec_of(), responses=r)
    assert result.items[0].verdict == "invalid"
    assert result.items[0].model_verdict == "met"


def test_雷4_neg_enumeration_nonempty_unmet():
    r = default_responses()
    r[4] = _neg_resp(["她看见江奇的嘴动了动，没有声音。"])
    r[5] = _screen_resp([{"quote": "她看见江奇的嘴动了动，没有声音。", "extracted": "她看见",
                          "referent": "姜聆", "keep": True}], core_action="不出现江奇以外的视角")
    result, _ = judge(spec_of(), responses=r)
    item = neg_items(result)[0]
    assert item.verdict == "unmet"


def test_雷5_overload_fuse_unclear():
    r = default_responses()
    candidates = [BODY[:8]] * 30
    r[4] = _neg_resp(candidates)
    r[5] = _screen_resp([{"quote": BODY[:8], "extracted": BODY[:8], "referent": "", "keep": True} for _ in range(30)],
                        core_action="不出现江奇以外的视角")
    result, _ = judge(spec_of(), responses=r)
    item = neg_items(result)[0]
    assert item.verdict == "unclear"
    assert "枚举过载" in item.reason


def test_雷6_screening_filters_noise():
    r = default_responses()
    r[4] = _neg_resp(["马文抬手擦了擦汗。", "她看见江奇的嘴动了动，没有声音。"])
    r[5] = _screen_resp([
        {"quote": "马文抬手擦了擦汗。", "extracted": "无", "referent": "", "keep": False},
        {"quote": "她看见江奇的嘴动了动，没有声音。", "extracted": "她看见", "referent": "姜聆", "keep": True},
    ], core_action="不出现江奇以外的视角")
    result, _ = judge(spec_of(), responses=r)
    item = neg_items(result)[0]
    assert item.verdict == "unmet"
    assert item.quotes == ["她看见江奇的嘴动了动，没有声音。"]


# ---------- 汇总与 md ----------

def test_engine_version_f4():
    result, _ = judge(spec_of())
    assert result.engine_version == "f4"


def test_parse_viewpoint_person():
    assert parse_viewpoint_person("不出现江奇以外的视角（全章只能落在他的感知内）") == "江奇"


def test_md_header_disclaimer():
    result, _ = judge(spec_of())
    md = render_markdown_f4(result)
    assert "本表是提示，不是判决" in md
