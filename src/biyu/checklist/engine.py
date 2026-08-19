"""F-1 必检项核对引擎:一次 LLM 调用逐条判定,强制引证。

契约(F-1 工单 5.2-5.4 + 中枢修订 A/B/C):
- 一次调用判完整章全部条目,输出 JSON 数组;解析失败重试一次,仍失败整份作废报错
- 修订 A:多成分(谁/做什么/凭什么/在什么条件下)全成立才 met;任一成分不成立或被替换 → unmet,
  reason 指明是哪一个成分
- 修订 B:met 一律=符合要求;must_not_happen 的 met=确实没出现,unmet=出现了(违规)
- 修订 C:quote=支持判定的正文原句;正向条目 unmet 时 quote 空、禁项 met 时 quote 空;
  quote 机械子串匹配(空白与标点归一化),匹配不上强制改判 unclear + reason「引证无效」
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from biyu.checklist.parser import ChecklistSpec

# 归一化:去空白(含全角)与常见标点
_NORMALIZE_RE = re.compile(r"[\s\u3000,，。.!！?？;；:：·、\"“”‘’()（）\[\]【】\-—…]+")


def normalize(text: str) -> str:
    return _NORMALIZE_RE.sub("", text)


def quote_in_text(quote: str, chapter_text: str) -> bool:
    """quote 是否真在正文中(空白与标点归一化后子串匹配)。"""
    if not quote or not quote.strip():
        return False
    return normalize(quote) in normalize(chapter_text)


@dataclass
class ChecklistItem:
    category: str
    index: int
    text: str
    verdict: str  # met / unmet / unclear
    quote: str
    reason: str


@dataclass
class ChecklistResult:
    planning_hash: str
    chapter: int
    version: str
    model: str
    cost_cny: float
    items: list[ChecklistItem] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    missing_category: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "planning_hash": self.planning_hash,
            "chapter": self.chapter,
            "version": self.version,
            "model": self.model,
            "cost_cny": self.cost_cny,
            "items": [
                {
                    "category": i.category,
                    "index": i.index,
                    "text": i.text,
                    "verdict": i.verdict,
                    "quote": i.quote,
                    "reason": i.reason,
                }
                for i in self.items
            ],
            "summary": self.summary,
        }


def build_prompt(spec: ChecklistSpec, chapter_text: str) -> str:
    """构建逐条判定提示词(封闭式一问一答,非开放式找问题)。"""
    cat_label = {
        "must_happen": "必须发生",
        "must_not_happen": "必须不发生",
        "ending_state": "结尾状态",
        "info_layers": "信息层级",
    }
    item_lines: list[str] = []
    for cat, text in spec.all_items():
        item_lines.append(f'- [{"必须不发生" if cat == "must_not_happen" else cat_label[cat]}] {text}')
    items_text = "\n".join(item_lines) if item_lines else "(无条目)"

    return f"""你是章节戏核履约核对员。给你一章正文和一份戏核必检项清单，逐条判定正文是否满足。

## 判定规则(必须严格遵守)

1. **三态判定**:
   - met = 符合要求
   - unmet = 不符合要求
   - unclear = 正文信息不足以判断,或该条本身不可核对(如内心状态)——宁可 unclear,不许硬判

2. **多成分规则**:一条必检项若含多个成分(谁 / 做什么 / 凭什么 / 在什么条件下),
   必须**全部成分**成立才判 met;任一成分不成立、被替换或缺失 → 判 unmet,
   并在 reason 里明确指出是哪一个成分不成立/被替换。

3. **各类别语义**:
   - 必须发生 / 结尾状态 / 信息层级:met = 正文里该事件/状态/信息成立
   - 必须不发生:met = 确实没出现;unmet = 出现了(即违规)

4. **引证要求(强制)**:每条 met 或 unmet 都必须给出正文原句作为证据,逐字引用,不得改写、不得拼凑、不得编造。
   - 正向条目(必须发生/结尾状态/信息层级):met 引落实的句子;unmet 时 quote 为空字符串
   - 禁项(必须不发生):met 时 quote 为空字符串;unmet 时必须给出违规原句
   - unclear:引最接近的句子,或空字符串

5. **reason 要求**:一句话,不超过 40 字,说明判定依据;unmet 时指明不成立的成分。

## 输出格式

只输出一个 JSON 数组,不要输出任何其他内容:

[
  {{"category": "must_happen", "index": 0, "text": "<必检项原文,逐字>", "verdict": "met|unmet|unclear", "quote": "<正文原句,逐字>", "reason": "<不超过40字>"}}
]

category 取值:must_happen / must_not_happen / ending_state / info_layers(与清单顺序一一对应)

## 必检项清单

{items_text}

## 正文

{chapter_text}
"""


def _category_allows_empty_quote(category: str, verdict: str) -> bool:
    """修订 C:哪些 (category, verdict) 组合允许 quote 为空。"""
    if verdict == "unclear":
        return True
    if category == "must_not_happen":
        return verdict == "met"
    return verdict == "unmet"


async def judge_checklist(
    spec: ChecklistSpec,
    chapter_text: str,
    adapter,
    version: str,
    chapter: int = 0,
    max_retries: int = 1,
) -> ChecklistResult:
    """一次调用判完整章;返回 ChecklistResult。解析失败重试一次,仍失败抛 RuntimeError。"""
    prompt = build_prompt(spec, chapter_text)
    messages = [{"role": "user", "content": prompt}]

    resp = None
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = await adapter.generate(messages)
            raw_items = json.loads(resp.text)
            if not isinstance(raw_items, list):
                raise ValueError("LLM 输出不是 JSON 数组")
            break
        except Exception as e:
            last_err = e
            resp = None
    if resp is None or raw_items is None:
        raise RuntimeError(f"必检项判定输出解析失败(重试 {max_retries} 次): {last_err}")

    items: list[ChecklistItem] = []
    for i, raw in enumerate(raw_items):
        try:
            category = str(raw.get("category", ""))
            text = str(raw.get("text", ""))
            verdict = str(raw.get("verdict", "unclear"))
            quote = str(raw.get("quote", ""))
            reason = str(raw.get("reason", ""))
        except Exception:
            continue
        if verdict not in ("met", "unmet", "unclear"):
            verdict = "unclear"
        # 引证机械校验(修订 C):quote 必须真在正文中;不匹配 → 强制改判 unclear
        if quote:
            if not quote_in_text(quote, chapter_text):
                verdict = "unclear"
                reason = f"引证无效: quote 不在正文中" + (f"; {reason}" if reason else "")
                quote = ""
        elif not _category_allows_empty_quote(category, verdict):
            # 该组合必须有 quote 却缺失 → 证据不足,强制 unclear
            verdict = "unclear"
            reason = "引证无效: 缺少正文原句" + (f"; {reason}" if reason else "")
        items.append(ChecklistItem(category=category, index=i, text=text, verdict=verdict, quote=quote, reason=reason))

    result = ChecklistResult(
        planning_hash=spec.planning_hash,
        chapter=chapter,
        version=version,
        model=resp.model if resp else "",
        cost_cny=resp.cost if resp else 0.0,
        items=items,
        missing_category=spec.missing_category,
    )
    result.summary = _summarize(result)
    return result


def _summarize(result: ChecklistResult) -> dict:
    total = len(result.items)
    met = sum(1 for i in result.items if i.verdict == "met")
    unmet = sum(1 for i in result.items if i.verdict == "unmet")
    unclear = sum(1 for i in result.items if i.verdict == "unclear")
    return {
        "total": total,
        "met": met,
        "unmet": unmet,
        "unclear": unclear,
        "missing_category": result.missing_category,
    }


def render_markdown(result: ChecklistResult) -> str:
    """人可读版:由 JSON 渲染,不另判。"""
    cat_label = {
        "must_happen": "必须发生",
        "must_not_happen": "必须不发生",
        "ending_state": "结尾状态",
        "info_layers": "信息层级",
    }
    verdict_label = {"met": "✅ met", "unmet": "❌ unmet", "unclear": "❓ unclear"}
    lines = [
        f"# 必检项核对 · {result.version}",
        "",
        f"- planning_hash: `{result.planning_hash}`",
        f"- chapter: {result.chapter} · version: {result.version} · model: {result.model}",
        f"- cost: ¥{result.cost_cny:.4f}",
        "",
        f"## 汇总: met {result.summary['met']} / unmet {result.summary['unmet']} / unclear {result.summary['unclear']} (共 {result.summary['total']})",
    ]
    if result.summary.get("missing_category"):
        lines.append(f"- ⚠️ 缺失类别: {', '.join(result.summary['missing_category'])}")
    lines.append("")
    for i, item in enumerate(result.items):
        lines.append(f"### {i + 1}. [{cat_label.get(item.category, item.category)}] {item.text}")
        lines.append(f"- 判定: {verdict_label.get(item.verdict, item.verdict)}")
        if item.quote:
            lines.append(f"- 引证: 「{item.quote}」")
        if item.reason:
            lines.append(f"- 理由: {item.reason}")
        lines.append("")
    return "\n".join(lines)
