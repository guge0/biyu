"""创作规律对照模块(P7-1 T4-T5)。

五大骨架(节奏/目标/爽点/开篇/七维)读取自
prompts/assets/网文Craft蒸馏_v0.md；资产是唯一文本家。

针对作者 idea 给"参考提示"。

实现策略:
- LLM 主路径:1 次 LLM 调用,JSON schema `{rhythm, goals, cool_points, opening, dimensions}`。
- 模板降级:LLM 异常 / JSON 失败 / 输出过短(<200)/ 过长(>2000) → 退化为纯模板。

红线:中性语气,"参考提示"不是"规则清单",不含"必须/应当/要求/不得/禁止"。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from biyu.config import get_project_root
from biyu.propose.prompts import build_craft_prompt
from biyu.fingerprint.adapter import _extract_json_object


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class CraftHints:
    """创作规律提示产物。

    source: 'llm' / 'template' / 'template_fallback'
    markdown: 给作者读的提示文本(已渲染成 Markdown)
    """

    markdown: str
    source: str  # 'llm' | 'template' | 'template_fallback'
    cost_cny: float = 0.0  # LLM 调用实际成本(模板路径为 0)
    latency_s: float = 0.0  # 耗时


# ---------------------------------------------------------------------------
# 模板降级路径
# ---------------------------------------------------------------------------


def read_craft_file(project_root: Path | None = None) -> str:
    """读 prompts/assets/网文Craft蒸馏_v0.md 全文。

    Args:
        project_root: 项目根目录;None → get_project_root()

    Returns:
        文件内容字符串。
    """
    root = project_root or get_project_root()
    path = root / "prompts" / "assets" / "网文Craft蒸馏_v0.md"
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"Required prompt asset could not be read: {path}") from exc


def render_craft_template(idea: str) -> str:
    """纯模板渲染:把蒸馏五节骨架针对 idea 中性叙述一遍。

    中性语气:不用"必须/应当/要求/不得/禁止"——这些是规则清单的口吻;
    我们用"可参考/常见做法/经验提示"等参考口吻。

    现在读取 prompts/assets/网文Craft蒸馏_v0.md 作为正文来源。
    """
    craft_content = read_craft_file()
    return f"""## 创作规律参考提示

> 来源:《网文 Craft 蒸馏》(千幻冰云《别说你懂写网文》蒸馏)
> 适用设想:**{idea}**
> 以下为结构化骨架的参考提示,具体取舍由作者判断。

{craft_content}
"""


# ---------------------------------------------------------------------------
# LLM 调用 + 降级编排
# ---------------------------------------------------------------------------


class _LLMAdapterProto(Protocol):
    """LLM adapter 的最小接口,与 LLMAdapter.generate 兼容。"""

    async def generate(self, messages: list, **kwargs: Any) -> Any: ...


def _render_llm_hints_as_markdown(parsed: dict, idea: str) -> str:
    """把 LLM 返回的结构化 JSON 渲染成 Markdown。"""
    return f"""## 创作规律参考提示(LLM)

> 来源:基于《网文 Craft 蒸馏》针对设想 **{idea}** 的针对性提示。
> 以下为参考提示,具体取舍由作者判断。

### 节奏曲线
{parsed.get("rhythm", "")}

### 目标体系
{parsed.get("goals", "")}

### 爽点
{parsed.get("cool_points", "")}

### 开篇结构
{parsed.get("opening", "")}

### 评书维度
{parsed.get("dimensions", "")}
"""


# 降级触发阈值(spec 已定)
_MIN_LEN = 200
_MAX_LEN = 2000


def build_craft_hints(
    idea: str,
    llm_adapter: _LLMAdapterProto | None = None,
) -> CraftHints:
    """合成创作规律提示。

    Args:
        idea: 作者设想文本
        llm_adapter: 可选 LLM adapter(注:同步入口,内部用 asyncio.run 跑 async generate);
                     None → 直接走模板,不调 LLM

    Returns:
        CraftHints: source='llm'(主路径)| 'template'(无 adapter)| 'template_fallback'(LLM 失败)
    """
    # 无 adapter → 直接走模板(不开 LLM)
    if llm_adapter is None:
        return CraftHints(markdown=render_craft_template(idea), source="template")

    # LLM 主路径
    started = time.time()
    try:
        messages = build_craft_prompt(idea)
        resp = asyncio.run(llm_adapter.generate(messages))
        elapsed = time.time() - started
        cost = float(getattr(resp, "cost", 0.0) or 0.0)
        text = getattr(resp, "text", "") or ""
        parsed = _parse_and_validate_llm_craft(text)
        if parsed is None:
            return _fallback(idea, "llm returned invalid JSON or schema", cost_cny=cost, latency_s=elapsed)
        md = _render_llm_hints_as_markdown(parsed, idea)
        if not (_MIN_LEN <= len(md) <= _MAX_LEN):
            return _fallback(
                idea, f"llm output length out of range ({len(md)} not in [{_MIN_LEN},{_MAX_LEN}])",
                cost_cny=cost, latency_s=elapsed,
            )
        return CraftHints(markdown=md, source="llm", cost_cny=cost, latency_s=elapsed)
    except Exception as e:
        elapsed = time.time() - started
        return _fallback(idea, f"llm error: {e}", latency_s=elapsed)


def _fallback(
    idea: str, reason: str,
    cost_cny: float = 0.0, latency_s: float = 0.0,
) -> CraftHints:
    """降级到模板,记录原因到 markdown 末尾(供调试/报告用)。"""
    md = render_craft_template(idea)
    # 在末尾加一行隐性标注(不在作者可见正文抢眼处,但 trace 留痕)
    md = md + f"\n<!-- fallback reason: {reason} -->\n"
    return CraftHints(
        markdown=md, source="template_fallback",
        cost_cny=cost_cny, latency_s=latency_s,
    )


def _parse_and_validate_llm_craft(text: str) -> dict | None:
    """解析 LLM 返回的 JSON 并做 schema 校验。

    schema: {rhythm, goals, cool_points, opening, dimensions} 全为字符串。
    """
    try:
        obj = _extract_json_object(text)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    required = ["rhythm", "goals", "cool_points", "opening", "dimensions"]
    if not all(k in obj and isinstance(obj[k], str) and obj[k].strip() for k in required):
        return None
    return obj
