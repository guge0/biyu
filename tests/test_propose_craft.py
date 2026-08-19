"""Tests for biyu.propose.craft — 创作规律对照.

覆盖:T4 读蒸馏+模板渲染(降级路径);T5 LLM 调用 + 异常/格式错/长度异常降级。
所有 LLM 调用通过注入 mock adapter 测试,零烧钱。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from biyu.propose.craft import (
    CraftHints,
    build_craft_hints,
    read_craft_file,
    render_craft_template,
)


# ---------------------------------------------------------------------------
# T4: 模板降级路径(render_craft_template)
# ---------------------------------------------------------------------------


def test_read_craft_file_uses_prompts_assets_single_home():
    root = Path(__file__).resolve().parents[1]
    content = read_craft_file(root)

    assert "全文消费者" in content
    assert (root / "prompts" / "assets" / "网文Craft蒸馏_v0.md").is_file()
    assert not (root / "docs" / "craft" / "网文Craft蒸馏_v0.md").exists()


def test_read_craft_file_missing_fails_loudly(tmp_path):
    expected = tmp_path / "prompts" / "assets" / "网文Craft蒸馏_v0.md"
    with pytest.raises(RuntimeError, match="Required prompt asset could not be read") as exc:
        read_craft_file(tmp_path)
    assert str(expected) in str(exc.value)


def test_render_craft_template_returns_markdown_with_distillate_sections():
    """模板渲染的产出含蒸馏的五大骨架:节奏/目标/爽点/开篇/七维。

    蒸馏文件第一/三部分的核心点必须在模板里出现(中性参考,不是规则清单)。
    """
    idea = "校车进秘境、轻喜剧爽文"

    md = render_craft_template(idea)

    assert isinstance(md, str)
    assert len(md) > 200  # 模板有实质内容
    # 蒸馏五节关键短语应在
    assert "节奏" in md
    assert "目标" in md
    assert "爽点" in md
    assert "开篇" in md


def test_render_craft_template_keeps_neutral_tone_no_must():
    """模板语气是'参考提示',附加的 wrapper 不含硬指令词。

    现在 render_craft_template 直接从 prompts/assets/网文Craft蒸馏_v0.md 读原始内容,
    蒸馏文件中自然含有"必须"/"禁止"等分析性用语(如"必须刻意提醒读者"、
    "禁止剧透结局"),这些是参考材料本身的合法表述,不应过滤。
    wrapper 段(标题、来源声明、适用设想)保持中性。
    """
    md = render_craft_template("某题材")

    # 只检查 wrapper 部分(前几行)的中性语气;蒸馏正文是参考材料,允许其自有表述
    wrapper = "\n".join(md.split("\n")[:5])  # 标题 + 来源 + 适用设想行
    for word in ["应当", "要求你", "不得"]:
        assert word not in wrapper, f"wrapper 里出现硬指令词 '{word}',违反中性语气"
    # 正文应有实质性参考内容(来自蒸馏文件)
    assert "节奏" in md
    assert len(md) > 500


def test_render_craft_template_echoes_idea():
    """模板回显作者的 idea 文本,让作者能识别这是针对自己设想的提示。"""
    idea = "都市异能+悬疑+轻喜剧"
    md = render_craft_template(idea)
    assert idea in md


# ---------------------------------------------------------------------------
# T5: LLM 调用 + 降级路径
# ---------------------------------------------------------------------------


class _FakeAdapter:
    """Mock LLM adapter,记录调用 + 返回预设响应。"""

    def __init__(self, response_text: str, cost: float = 0.001):
        self._response = response_text
        self._cost = cost
        self.calls: list = []

    async def generate(self, messages, **kwargs):
        self.calls.append(messages)
        # 模拟 LLMResponse 的最小接口
        class _R:
            text = self._response
            cost = self._cost
        return _R()


class _FailingAdapter:
    """Mock adapter that raises to trigger fallback."""

    def __init__(self, exc: Exception):
        self._exc = exc

    async def generate(self, messages, **kwargs):
        raise self._exc


def test_build_craft_hints_uses_llm_when_valid_json():
    """LLM 返回合法 JSON 且字段齐全 → 走 LLM 输出,不走模板降级。"""
    good_json = (
        '{"rhythm": "校车+秘境适合每章一小高潮,万字小高潮、三章一局的节奏'
        '配合轻喜剧爽文比较抓人;3000字一章时,2500字处开始埋钩子。", '
        '"goals": "短期目标:让校车出秘境(1万字内立);中期:揭开秘境规则'
        '(3万字内);长期:角色成长/秘境起源(6万字内)。", '
        '"cool_points": "可主打暧昧/情和送菜流;打脸先抑后扬已被写烂,慎用。", '
        '"opening": "凤头:开头简单精要,场景设定推到第5章后;主角聚光压到2-3人;'
        '双伏笔:一长一短,短线3万字内揭开。", '
        '"dimensions": "脸面:书名要好记;基础:错字少;开头:前3万字抓人。"}'
    )
    adapter = _FakeAdapter(good_json)

    result = build_craft_hints(idea="某设想", llm_adapter=adapter)

    assert isinstance(result, CraftHints)
    assert result.source == "llm"
    assert "万字小高潮" in result.markdown
    assert adapter.calls  # 确实调过 LLM


def test_build_craft_hints_fallback_to_template_when_llm_raises():
    """LLM 异常 → 降级模板,不崩,source='template_fallback'。"""
    adapter = _FailingAdapter(RuntimeError("model offline"))

    result = build_craft_hints(idea="某设想", llm_adapter=adapter)

    assert result.source == "template_fallback"
    assert "节奏" in result.markdown  # 模板内容仍在


def test_build_craft_hints_fallback_when_llm_returns_invalid_json():
    """LLM 返回非合法 JSON 且无法 repair → 降级模板。"""
    adapter = _FakeAdapter("这不是 JSON,就是一坨话。")

    result = build_craft_hints(idea="某设想", llm_adapter=adapter)

    assert result.source == "template_fallback"


def test_build_craft_hints_fallback_when_llm_output_too_short():
    """LLM 输出过短(<200 字)→ 视为低质量,降级模板。"""
    # 短的合法 JSON,渲染出来不足 200 字
    short_json = '{"rhythm":"短","goals":"短","cool_points":"短","opening":"短","dimensions":"短"}'
    adapter = _FakeAdapter(short_json)

    result = build_craft_hints(idea="某设想", llm_adapter=adapter)

    assert result.source == "template_fallback"


def test_build_craft_hints_fallback_when_llm_output_too_long():
    """LLM 输出过长(>2000 字)→ 视为啰嗦,降级模板。"""
    long_json = (
        '{"rhythm": "' + "节" * 3000 + '", '
        '"goals": "x", "cool_points": "x", "opening": "x", "dimensions": "x"}'
    )
    adapter = _FakeAdapter(long_json)

    result = build_craft_hints(idea="某设想", llm_adapter=adapter)

    assert result.source == "template_fallback"


def test_build_craft_hints_without_adapter_goes_straight_to_template():
    """没传 LLM adapter(如离线模式)→ 直接走模板,不调 LLM。"""
    result = build_craft_hints(idea="某设想", llm_adapter=None)

    assert result.source == "template"
    assert "节奏" in result.markdown
