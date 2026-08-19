"""F-1 必检项核对引擎测试(埋雷三雷 + 修订 A/B/C 规则)。

埋雷两态:注掉修复三条全红,装上三条全绿。
- 雷1:正向条目模型判 unmet(quote 空)→ 引擎必须保持 unmet,不得误改判 unclear
- 雷2:不同措辞实现 → 模型判 met(quote 为正文内不同措辞句)→ 引擎必须 met,不得退化成关键词匹配
- 雷3:模型返回编造 quote(正文中不存在)→ 引擎必须强制改判 unclear + reason「引证无效」
"""
from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from biyu.checklist.engine import judge_checklist
from biyu.checklist.f4_engine import F4Result
from biyu.checklist.parser import (
    ChecklistMissingError,
    ChecklistSpec,
    parse_checklist,
)
from biyu.llm.base import LLMResponse
from biyu.checklist.runner import run_and_save_checklist

PLANNING_V1 = """# ch1 戏核

## 必检项

**必须发生**
- 江奇在告示板前拦住豁口佣兵队，说出"心脏不在左胸，在左肋第三道鳞缝之后"
- 姜聆以协会公示的验尸通报为证，当众确认江奇的伤口细节属实

**必须不发生**
- 不出现江奇以外的视角（全章只能落在他的感知内）

**结尾状态**
- 江奇站在拾荒协会门前告示板下，身体无伤

**信息层级**
- 江奇的"死过一次"及回溯能力：在告示板前公开说出；但无人相信复活之说
"""

PLANNING_NO_BLOCK = "# ch1 戏核\n\n## 方案\n\n- 随便写\n"

PLANNING_MISSING_CAT = """# ch1 戏核

## 必检项

**必须发生**
- 一件事

**必须不发生**
- 不出现视角越界
"""


PLANNING_NESTED = """# ch1 戏核

## 必检项
- **必须发生**：
  - 主角当众说出关键事实
  - 对手承认账册属实
- **必须不发生**：
  - 不切换到配角视角
- **结尾状态**：主角站在协会门前
- **信息层级**：真相只公开第一层
"""


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FakeAdapter:
    """返回脚本化 JSON 文本的假 adapter。"""

    def __init__(self, responses, name="v3-fake", cost=0.03):
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


# ---------- parser ----------

def test_parse_full_spec():
    spec = parse_checklist(PLANNING_V1)
    assert len(spec.must_happen) == 2
    assert len(spec.must_not_happen) == 1
    assert len(spec.ending_state) == 1
    assert len(spec.info_layers) == 1
    assert spec.must_happen[0].startswith("江奇在告示板前")
    assert len(spec.planning_hash) == 12


def test_parse_nested_planner_markdown_contract():
    """兼容 Planner 真实产出的「项目符号分类 + 缩进条目」形态。"""
    spec = parse_checklist(PLANNING_NESTED)
    assert spec.must_happen == ["主角当众说出关键事实", "对手承认账册属实"]
    assert spec.must_not_happen == ["不切换到配角视角"]
    assert spec.ending_state == ["主角站在协会门前"]
    assert spec.info_layers == ["真相只公开第一层"]
    assert spec.missing_category == []


def test_planning_hash_stable():
    assert parse_checklist(PLANNING_V1).planning_hash == parse_checklist(PLANNING_V1).planning_hash
    assert parse_checklist(PLANNING_V1).planning_hash != parse_checklist(PLANNING_MISSING_CAT).planning_hash


def test_missing_block_raises():
    with pytest.raises(ChecklistMissingError):
        parse_checklist(PLANNING_NO_BLOCK)


def test_missing_category_flagged():
    spec = parse_checklist(PLANNING_MISSING_CAT)
    assert spec.missing_category == ["ending_state", "info_layers"]
    assert spec.ending_state == []
    assert spec.info_layers == []


# ---------- 修订 B:禁项 met/unmet 语义 ----------

def test_must_not_happen_met_means_absent():
    """禁项:模型判 met → 引擎保持 met(确实没出现)。"""
    body = "江奇独自站在告示板下,眼前只有告示。"
    resp_json = '[{"category":"must_not_happen","index":0,"text":"不出现江奇以外的视角","verdict":"met","quote":"","reason":"全文只有江奇感知"}]'
    adapter = FakeAdapter([resp_json])
    spec = parse_checklist(PLANNING_V1)
    result = run(judge_checklist(spec, body, adapter, version="t1"))
    item = result.items[0]
    assert item.verdict == "met"
    assert item.quote == ""


def test_must_not_happen_unmet_carries_quote():
    """禁项:模型判 unmet(违规出现)→ 引擎保持 unmet 并保留违规原句。"""
    body = "她看见江奇的嘴动了动,却没有声音。"
    resp_json = '[{"category":"must_not_happen","index":0,"text":"不出现江奇以外的视角","verdict":"unmet","quote":"她看见江奇的嘴动了动","reason":"出现姜聆视角"}]'
    adapter = FakeAdapter([resp_json])
    spec = parse_checklist(PLANNING_V1)
    result = run(judge_checklist(spec, body, adapter, version="t1"))
    item = result.items[0]
    assert item.verdict == "unmet"
    assert item.quote == "她看见江奇的嘴动了动"


# ---------- 修订 C:quote 校验 ----------

def test_quote_normalized_substring_match():
    """quote 与正文空白/标点归一化后匹配即通过。"""
    body = "姜聆站起来,她把掰了一半的饼搁在石板凳上。"
    resp_json = (
        '[{"category":"must_happen","index":1,'
        '"text":"姜聆以协会公示的验尸通报为证,当众确认江奇的伤口细节属实",'
        '"verdict":"met","quote":"姜聆站起来,她把掰了一半的饼搁在石板凳上。",'
        '"reason":"姜聆当众动作落实"}]'
    )
    adapter = FakeAdapter([resp_json])
    spec = parse_checklist(PLANNING_V1)
    result = run(judge_checklist(spec, body, adapter, version="t1"))
    assert result.items[0].verdict == "met"


def test_雷3_fabricated_quote_forced_unclear():
    """埋雷雷3:模型返回编造 quote(正文中不存在)→ 强制改判 unclear + 引证无效。"""
    body = "江奇站在告示板下,一言不发。"
    resp_json = (
        '[{"category":"must_happen","index":0,'
        '"text":"江奇在告示板前拦住豁口佣兵队,说出...",'
        '"verdict":"met","quote":"江奇以协会公示的验尸通报为证,当众宣布",'
        '"reason":"当众说出"}]'
    )
    adapter = FakeAdapter([resp_json])
    spec = parse_checklist(PLANNING_V1)
    result = run(judge_checklist(spec, body, adapter, version="t1"))
    item = result.items[0]
    assert item.verdict == "unclear"
    assert "引证无效" in item.reason


def test_雷1_unmet_with_empty_quote_kept():
    """埋雷雷1:正向条目模型判 unmet 且 quote 为空 → 引擎保持 unmet,不改判 unclear。"""
    body = "江奇站在告示板下,一言不发。"
    resp_json = (
        '[{"category":"must_happen","index":0,'
        '"text":"江奇在告示板前拦住豁口佣兵队,说出...",'
        '"verdict":"unmet","quote":"","reason":"没有拦住任何人"}]'
    )
    adapter = FakeAdapter([resp_json])
    spec = parse_checklist(PLANNING_V1)
    result = run(judge_checklist(spec, body, adapter, version="t1"))
    assert result.items[0].verdict == "unmet"


def test_雷2_different_wording_met_kept():
    """埋雷雷2:不同措辞实现 → 模型判 met 且 quote 在正文 → 引擎 met(非关键词匹配)。"""
    body = "他把嘴凑到告示板前,朝那队背着豁口刀的佣兵喝道:鳞缝在左肋第三道之后。"
    resp_json = (
        '[{"category":"must_happen","index":0,'
        '"text":"江奇在告示板前拦住豁口佣兵队,说出...",'
        '"verdict":"met","quote":"鳞缝在左肋第三道之后",'
        '"reason":"不同措辞说出关键弱点"}]'
    )
    adapter = FakeAdapter([resp_json])
    spec = parse_checklist(PLANNING_V1)
    result = run(judge_checklist(spec, body, adapter, version="t1"))
    assert result.items[0].verdict == "met"


# ---------- 修订 A:多成分规则 ----------

def test_prompt_contains_multicomponent_instruction():
    """提示词必须包含多成分指令与三态定义(修订 A/B)。"""
    from biyu.checklist.engine import build_prompt

    spec = parse_checklist(PLANNING_V1)
    prompt = build_prompt(spec, "正文")
    assert "成分" in prompt
    assert "met" in prompt and "unmet" in prompt and "unclear" in prompt
    assert "引" in prompt  # 强制引证


def test_multicomponent_partial_met_kept_unmet():
    """多成分:模型判 unmet(成分被替换)→ 引擎透传 unmet 并保留 reason。"""
    body = "姜聆当众确认江奇的伤口细节属实。"
    resp_json = (
        '[{"category":"must_happen","index":1,'
        '"text":"姜聆以协会公示的验尸通报为证,当众确认江奇的伤口细节属实",'
        '"verdict":"unmet","quote":"",'
        '"reason":"证据成分被替换:以收尸登记簿为证,非协会公示通报"}]'
    )
    adapter = FakeAdapter([resp_json])
    spec = parse_checklist(PLANNING_V1)
    result = run(judge_checklist(spec, body, adapter, version="t1"))
    assert result.items[0].verdict == "unmet"
    assert "证据成分" in result.items[0].reason


# ---------- 解析失败与重试 ----------

def test_bad_json_retried_once():
    body = "正文。"
    spec = parse_checklist(PLANNING_V1)
    adapter = FakeAdapter(["not json at all", '[{"category":"must_happen","index":0,"text":"江奇在告示板前拦住豁口佣兵队,说出...","verdict":"unmet","quote":"","reason":"x"}]'])
    result = run(judge_checklist(spec, body, adapter, version="t1"))
    assert len(adapter.calls) == 2
    assert result.items[0].verdict == "unmet"


def test_double_bad_json_raises_no_partial():
    body = "正文。"
    spec = parse_checklist(PLANNING_V1)
    adapter = FakeAdapter(["not json", "still not json"])
    with pytest.raises(RuntimeError):
        run(judge_checklist(spec, body, adapter, version="t1"))
    assert len(adapter.calls) == 2


# ---------- 结果结构 ----------

def test_summary_counts_and_hash():
    body = "江奇站在告示板下。她看见江奇的脸。"
    resp_json = (
        '[{"category":"must_happen","index":0,"text":"江奇在告示板前拦住豁口佣兵队,说出...","verdict":"met","quote":"江奇站在告示板下","reason":"a"},'
        '{"category":"must_not_happen","index":0,"text":"不出现江奇以外的视角","verdict":"unmet","quote":"她看见江奇的脸","reason":"b"}]'
    )
    adapter = FakeAdapter([resp_json])
    spec = parse_checklist(PLANNING_V1)
    result = run(judge_checklist(spec, body, adapter, version="t1"))
    assert result.summary["total"] == 2
    assert result.summary["met"] == 1
    assert result.summary["unmet"] == 1
    assert result.summary["unclear"] == 0
    assert result.planning_hash == spec.planning_hash
    assert result.version == "t1"
    assert result.model == "v3-fake"


def test_runner_binds_saved_result_to_exact_candidate_sha(tmp_path, monkeypatch):
    """落盘结果必须绑定本次核对的正文版本，供读稿页精确采用。"""
    chapter_text = "当前候选正文\n第二行"
    result = F4Result(
        planning_hash="planning-sha",
        chapter=1,
        version="sha-fixture",
        summary={
            "total": 0,
            "met": 0,
            "unmet": 0,
            "unclear": 0,
            "invalid": 0,
            "invalid_rate": 0.0,
            "missing_category": [],
        },
    )

    async def fake_judge(*args, **kwargs):
        return result

    monkeypatch.setattr("biyu.checklist.runner.judge_checklist_f4", fake_judge)
    returned, warnings = run(
        run_and_save_checklist(
            book_dir=tmp_path,
            chapter_num=1,
            planning_text=PLANNING_V1,
            chapter_text=chapter_text,
            adapter=FakeAdapter([]),
            version="sha-fixture",
        )
    )

    assert returned is result
    assert warnings == []
    saved = json.loads(
        (tmp_path / "logs/ch1/candidates/sha-fixture_checklist.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved["candidate_sha"] == hashlib.sha256(
        chapter_text.encode("utf-8")
    ).hexdigest()
