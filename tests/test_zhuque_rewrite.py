"""S-8-1 · 改写函数契约:三类提示词的组装与参数传法、空/异常返 ""。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from biyu.zhuque import rewrite
from biyu.zhuque.rewrite import _deai_system, back_translate, deai, polish, zhzh

PAIRS = [
    {"src": "他猫着腰钻进柴房。", "dst": "他弯腰进了柴房。", "note": ""},
    ("她收了针线。", "她把针线收起来。"),   # 元组形态也要兼容
]


class CapturingAdapter:
    """记下每次 generate 的消息与参数,按序回吐文本。"""

    def __init__(self, outputs: list[str] | None = None):
        self.outputs = list(outputs or [])
        self.calls: list[dict] = []

    async def generate(self, messages: list, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        text = self.outputs.pop(0) if self.outputs else ""
        if text == "RAISE":
            raise RuntimeError("炸了")
        return SimpleNamespace(text=text, cost=0.0)


def _run(coro):
    return asyncio.run(coro)


def test_zhzh_builds_fewshot_system_verbatim() -> None:
    adapter = CapturingAdapter(["改写稿"])
    out = _run(zhzh(adapter, "⟦K1⟧数账。", PAIRS))
    assert out == "改写稿"
    system = adapter.calls[0]["messages"][0]["content"]
    assert system.startswith(rewrite.SYS_ZHZH_HEAD)
    assert system.endswith(rewrite.SYS_ZHZH_TAIL)
    middle = system[len(rewrite.SYS_ZHZH_HEAD):-len(rewrite.SYS_ZHZH_TAIL)]
    assert middle == ("原文：他猫着腰钻进柴房。\n改写：他弯腰进了柴房。\n\n"
                      "原文：她收了针线。\n改写：她把针线收起来。")
    assert adapter.calls[0]["messages"][1]["content"] == "⟦K1⟧数账。"
    assert adapter.calls[0]["kwargs"]["temperature"] == 0.9          # r14 实测档
    assert adapter.calls[0]["kwargs"]["thinking"] == {"type": "disabled"}


def test_polish_prompt_and_temperature() -> None:
    adapter = CapturingAdapter(["小手术稿"])
    out = _run(polish(adapter, "他数账。"))
    assert out == "小手术稿"
    assert adapter.calls[0]["messages"][0]["content"] == rewrite.SYS_POLISH
    assert adapter.calls[0]["kwargs"]["temperature"] == 0.7          # r13 实验档


def test_deai_system_is_skill_body_plus_wrap() -> None:
    system = _deai_system()
    assert not system.startswith("---")            # frontmatter 已去
    assert system.lstrip().startswith("# Humanizer-zh")
    assert "=====" in system and system.endswith(rewrite.DEAI_WRAP)
    assert "以上是去除 AI 写作痕迹的完整指南" not in system   # 开头那句已去掉


def test_deai_call_params() -> None:
    adapter = CapturingAdapter(["去味稿"])
    assert _run(deai(adapter, "他数账。")) == "去味稿"
    assert adapter.calls[0]["messages"][0]["content"] == _deai_system()
    assert adapter.calls[0]["kwargs"]["temperature"] == 0.7
    assert adapter.calls[0]["kwargs"]["max_tokens"] == 4000         # r13 分块上限配套


def test_generate_returns_empty_on_exception_or_blank() -> None:
    adapter = CapturingAdapter(["RAISE"])
    assert _run(zhzh(adapter, "x", PAIRS)) == ""
    adapter2 = CapturingAdapter(["   "])
    assert _run(polish(adapter2, "x")) == ""
    adapter3 = CapturingAdapter(["en", ""])
    assert _run(back_translate(adapter3, "x", [])) == ""            # 英文有了中文空 → 整稿空
