"""F-4 核对引擎第四版:不可观察信息问法 + 代词消歧 + 非视角加严。

相对 F-3 的改动(F-4 工单 3.x):
1. 视角类复筛改问「非视角人物的内心活动/感受/视角人物无法观察到的信息」,
   抽片段,答「无」剔除;带关键区分示例表
2. 代词消歧:抽取片段含代词必须给 referent;referent=视角人物或不明 → 剔除+ambiguous 计数
3. 非视角类加严:抽取片段必须满足核心动作(解释性陈述/结构性说明);core_action 复述落盘
4. md 页眉固定说明:「本表是提示,不是判决」
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from biyu.checklist.engine import normalize
MAX_QUOTES = 5

CAT_LABEL = {
    "must_happen": "必须发生",
    "must_not_happen": "必须不发生",
    "ending_state": "结尾状态",
    "info_layers": "信息层级",
}


@dataclass
class F2Component:
    question: str
    verdict: str
    quotes: list[str] = field(default_factory=list)


@dataclass
class F2Item:
    category: str
    index: int
    text: str
    verdict: str  # met / unmet / unclear / invalid
    model_verdict: str  # invalid 时保留模型原判
    quotes: list[str] = field(default_factory=list)
    components: list[F2Component] = field(default_factory=list)
    reason: str = ""


@dataclass
class F2Result:
    planning_hash: str
    chapter: int
    version: str
    engine_version: str = "f4"
    model: str = ""
    cost_cny: float = 0.0
    items: list[F2Item] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    missing_category: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "planning_hash": self.planning_hash,
            "chapter": self.chapter,
            "version": self.version,
            "engine_version": self.engine_version,
            "model": self.model,
            "cost_cny": self.cost_cny,
            "items": [
                {
                    "category": i.category,
                    "index": i.index,
                    "text": i.text,
                    "components": [
                        {"question": c.question, "verdict": c.verdict, "quotes": c.quotes}
                        for c in i.components
                    ],
                    "verdict": i.verdict,
                    "model_verdict": i.model_verdict,
                    "quotes": i.quotes,
                    "reason": i.reason,
                }
                for i in self.items
            ],
            "summary": self.summary,
        }


def quote_in_text(quote: str, chapter_text: str) -> bool:
    """单条 quote 必须正文连续子串(空白与标点归一化后)。"""
    if not quote or not quote.strip():
        return False
    return normalize(quote) in normalize(chapter_text)


from biyu.checklist.parser import ChecklistSpec

ENGINE_VERSION = "f4"
BATCH_SIZE = 6
OVERLOAD_LIMIT = 12

# 复筛抽取题(名词题,非判否题)
VIEWPOINT_QUESTION = (
    "这一句里,有没有写到非视角人物的内心活动、感受、"
    "或视角人物无法观察到的信息?有的话把那几个字原样抽出来;没有就答「无」。"
)
OTHER_QUESTION_TEMPLATE = (
    "这一句里,满足「{core_action}」的具体文字是哪几个字?"
    "光提到相关名词不算,必须是满足核心动作的内容;没有就答「无」。"
)

_VIEWPOINT_RE = re.compile(r"不出现(.+?)以外")


def parse_viewpoint_person(text: str) -> str | None:
    """从禁项原文取视角人物:「不出现江奇以外的视角」→ 江奇。取不到返回 None。"""
    m = _VIEWPOINT_RE.search(text)
    if not m:
        return None
    person = m.group(1).strip()
    # 去掉常见修饰
    person = person.replace("的", "").strip()
    return person or None


@dataclass
class ScreenEntry:
    quote: str
    extracted: str
    referent: str = ""  # 抽取片段含代词时,代词指代的人名
    kept: bool = False


@dataclass
class NegativeScreening:
    raw_candidates: int
    overload: bool
    core_action: str = ""
    ambiguous: int = 0
    screened: list[ScreenEntry] = field(default_factory=list)


@dataclass
class F4Item(F2Item):
    negative_screening: NegativeScreening | None = None


@dataclass
class F4Result(F2Result):
    engine_version: str = ENGINE_VERSION

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["engine_version"] = self.engine_version
        for item, raw in zip(self.items, d["items"]):
            if isinstance(item, F2Item) and item.negative_screening is not None:
                ns = item.negative_screening
                raw["negative_screening"] = {
                    "raw_candidates": ns.raw_candidates,
                    "overload": ns.overload,
                    "core_action": ns.core_action,
                    "ambiguous": ns.ambiguous,
                    "screened": [
                        {"quote": s.quote, "extracted": s.extracted, "referent": s.referent, "kept": s.kept}
                        for s in ns.screened
                    ],
                }
        return d


# ---------- 提示词 ----------

def _decompose_prompt(spec: ChecklistSpec) -> str:
    lines = []
    for cat, text in spec.all_items():
        lines.append(f"- [{CAT_LABEL.get(cat, cat)}] {text}")
    return f"""你是戏核必检项拆解员。把下面每条必检项拆成可独立判定的成分,
每个成分是一个完整问句,必须能回答 是/否/不清楚。只许拆,不许改写原文措辞。
例:「姜聆以协会公示的验尸通报为证,当众确认江奇的伤口细节属实」
→ ① 姜聆当众确认了吗 ② 她凭的是协会公示的验尸通报吗 ③ 确认的是伤口细节属实吗
对不需要拆的条目,给一个完整问句即可。

只输出 JSON 数组,不输出其他内容:
[{{"index": 0, "question": "<完整问句>"}}, ...]

## 必检项清单
{chr(10).join(lines)}
"""


def _positive_prompt(
    spec: ChecklistSpec, category: str, indexes: list[int],
    components: dict[int, list[str]], chapter_text: str,
) -> str:
    lines = []
    for idx in indexes:
        text = getattr(spec, category)[idx - _cat_start(spec, category)]
        comps = components.get(idx, [text])
        lines.append(f"- [{idx}] {text} | 成分: " + " / ".join(f"({q})" for q in comps))
    return f"""你是戏核履约核对员。给一章正文,逐条判定必检项是否满足。

判定规则:
1. 三态:met=符合要求 / unmet=不符合 / unclear=正文信息不足或该条不可核对(宁可 unclear,不许硬判)
2. 多成分:每条含多个成分(括号中列出),必须全部成分成立才判 met;
   任一成分不成立 → 该条 unmet,reason 指明是哪个成分不成立
3. 引证:每个成分的 met/unmet 判定必须带正文原句;quotes 为正文中的**连续原句**数组,
   每条逐字引用,不得改写、合并;跨句落实给多条,不许合并成一句;允许 0~5 条;
   met 最多 5 条,unmet 可为空数组,unclear 可为空数组
4. **找不到能逐字引用的原句时,判 unclear,不要编一个。**
5. reason 一句话,不超过 40 字

只输出 JSON 数组:
[{{"index": <编号>, "text": "<必检项原文,逐字>", "components": [{{"question": "<问句>", "verdict": "met|unmet|unclear", "quotes": ["<连续原句>", ...]}}],
  "verdict": "met|unmet|unclear", "quotes": ["<连续原句>", ...], "reason": "<40字>"}}]

## 必检项
{chr(10).join(lines)}

## 正文
{chapter_text}
"""


def _reask_prompt(item_text: str, chapter_text: str) -> str:
    return f"""你之前对下面这条必检项判了 met,但引用的句子在正文中找不到(引用无效)。

请重新判定。**严禁编造引证**——正文里没有逐字原句,就不许给 quote。

判定规则:
- met:必须给出正文中逐字存在的连续原句,否则不许判 met
- unmet:正文明确不符合,quotes 可为空
- unclear:找不到可逐字引用的原句,或该条不可核对(如内心状态、想法、感受)——判 unclear

必检项:{item_text}

只输出 JSON:
{{"index": 0, "text": "<必检项原文,逐字>", "verdict": "met|unmet|unclear", "quotes": ["<连续原句>", ...], "reason": "<40字>"}}

## 正文
{chapter_text}
"""


def _negative_prompt(text: str, chapter_text: str) -> str:
    return f"""你是戏核禁项枚举员。下面是一条「必须不发生」的禁项。

把正文里所有**可能**属于这条禁项的句子逐字列出来。宁可多列,不确定的也列。
一条都没有就返回空数组。只做枚举,不要判断这些句子算不算违规。

判断时注意:
- 禁项若是「不出现某角色的视角」,要特别留意**他人的看见/听见/感知/心理活动**句,
  以及任何脱离主角感知的旁观描写(例如「她看见…」「他心想…」「人群注意到…」);
- 主角自己的所见所闻**不属于**越界,不要列;
- 宁可错列,不可漏列。

只输出 JSON:
{{"quotes": ["<正文中的连续原句,逐字>", ...]}}

## 禁项
{text}

## 正文
{chapter_text}
"""


def _screen_prompt(text: str, candidates: list[str], chapter_text: str) -> str:
    """抽取式复筛(F-4):问「不可观察信息」,非视角类先复述核心动作。"""
    viewpoint = parse_viewpoint_person(text)
    cand_lines = "\n".join(f"- {q}" for q in candidates)
    if viewpoint is not None:
        return f"""你是禁项候选句复筛员。下面是一条禁项和一批候选句。
对**每一个候选句**回答一个抽取题(名词题,不是判断题):

抽取题:{VIEWPOINT_QUESTION}

判定规则:
- 抽出的片段过「在正文中逐字存在」校验后 → keep=true(保留为违规候选)
- 答「无」→ keep=false(剔除)

关键区分(视角人物 = {viewpoint}):
| 句子 | 判 | 为什么 |
|---|---|---|
| 秦岳回头看了江奇一眼 | 剔除 | 动作,视角人物看得见 |
| 她**看见**江奇的嘴动了动 | 保留 | 「看见」是他人的感知内容 |
| 她**听见**"断刀卡鳞"四个字 | 保留 | 同上 |
| 那个一声不吭的**收尸人** | 保留 | 他人对视角人物的称谓 |
| 传进**在场每一个人**的脚底板 | 保留 | 超出个人感知范围 |
| 姜聆把半块饼递过去 | 剔除 | 动作,看得见 |

**代词消歧**:抽取片段里出现代词(他/她/它/他们)时,必须同时给出 `referent`(该代词指代的具体人名)。
- referent = 视角人物「{viewpoint}」→ 剔除
- referent 给不出(指代不明)→ 剔除
- referent = 其他人 → 保留

只输出 JSON:
{{"screened": [{{"quote": "<候选句,逐字>", "extracted": "<抽出的原文片段,没有答'无'>", "referent": "<代词指代的人名,无代词填空>", "keep": true|false}}]}}

## 禁项
{text}

## 候选句
{cand_lines}

## 正文
{chapter_text}
"""
    # 非视角类:先复述核心动作,再据此抽取(加严)
    return f"""你是禁项候选句复筛员。下面是一条禁项和一批候选句。

第一步,先复述这条禁项的**核心动作**(一句话,如「解答回溯的原因/代价/目的」「写出完整解剖解释」):

第二步,对**每一个候选句**回答抽取题:
{OTHER_QUESTION_TEMPLATE.format(core_action="<核心动作>")}

判定规则:
- 抽出的片段必须**满足该禁项的核心动作**,光提到相关名词不算;
- 例:「不解答回溯的原因」→ 要抽的是**解释性陈述**(因为…/由于…/是…造成的/所以他才…),单纯提及「我死过一次」「回到三天前」这类现象陈述**不算**;
- 例:「不写出完整解剖解释」→ 要抽的是**结构性说明**(器官位置、构造、机理的成体系描述),单纯的现场感官呈现(声音、裂开、鼓胀)不算;
- 片段过「在正文中逐字存在」校验 → keep=true;答「无」→ keep=false

只输出 JSON:
{{"core_action": "<第一步复述的核心动作>", "screened": [{{"quote": "<候选句,逐字>", "extracted": "<抽出的原文片段,没有答'无'>", "referent": "", "keep": true|false}}]}}

## 禁项
{text}

## 候选句
{cand_lines}

## 正文
{chapter_text}
"""


def _cat_start(spec: ChecklistSpec, category: str) -> int:
    start = 0
    for cat in ("must_happen", "must_not_happen", "ending_state", "info_layers"):
        if cat == category:
            return start
        start += len(getattr(spec, cat))
    return start


def _parse_json_list(text: str) -> list:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip("` \n")
        data = json.loads(cleaned)
    if isinstance(data, dict):
        return [data]
    assert isinstance(data, list), "不是数组"
    return data


def _locate_by_text(spec: ChecklistSpec, cat: str, idx: int, text_out: str, q_to_idx: dict[str, int] | None = None) -> int:
    """定位:先按必检项原文匹配,再按成分问句反查,最后回退 idx。"""
    cat_items = list(getattr(spec, cat))
    if text_out.strip():
        n_out = normalize(text_out)
        for ci, ctext in enumerate(cat_items):
            n_ct = normalize(ctext)
            if n_out == n_ct or (n_out and n_ct and n_ct in n_out):
                return _cat_start(spec, cat) + ci
    # 成分问句反查(模型输出成分问句而非原文时)
    if q_to_idx and text_out.strip():
        for q, qi in q_to_idx.items():
            if normalize(q) == normalize(text_out) or normalize(q) in normalize(text_out):
                return qi
    return idx


async def judge_checklist_f4(
    spec: ChecklistSpec,
    chapter_text: str,
    adapter,
    version: str,
    chapter: int = 0,
    max_retries: int = 1,
) -> F4Result:
    """F-3 核对:拆解1 + 正向分批(+引证失败重问) + 禁项枚举(+熔断+复筛)。"""
    cost_cny = 0.0
    model = ""

    # ---- 1. 成分拆解 ----
    components: dict[int, list[str]] = {}
    q_to_idx: dict[str, int] = {}  # 成分问句 → 全局条目 idx(修整批错位)
    for attempt in range(max_retries + 1):
        try:
            resp = await adapter.generate([{"role": "user", "content": _decompose_prompt(spec)}])
            cost_cny += resp.cost
            model = resp.model
            for d in _parse_json_list(resp.text):
                if isinstance(d, dict) and "index" in d:
                    components[int(d["index"])] = [d.get("question", "")]
                    for q in components[int(d["index"])]:
                        if q.strip():
                            q_to_idx[q.strip()] = int(d["index"])
            break
        except Exception:
            if attempt == max_retries:
                raise RuntimeError(f"成分拆解输出解析失败(重试 {max_retries} 次)")
            continue

    # ---- 2. 正向批判定(分批 + 引证失败重问) ----
    items: dict[int, F4Item] = {}
    for cat in ("must_happen", "ending_state", "info_layers"):
        start = _cat_start(spec, cat)
        texts = list(getattr(spec, cat))
        for batch_start in range(0, len(texts), BATCH_SIZE):
            batch = texts[batch_start:batch_start + BATCH_SIZE]
            indexes = [start + batch_start + i for i in range(len(batch))]
            if not indexes:
                continue
            for attempt in range(max_retries + 1):
                try:
                    resp = await adapter.generate(
                        [{"role": "user", "content": _positive_prompt(spec, cat, indexes, components, chapter_text)}]
                    )
                    cost_cny += resp.cost
                    model = resp.model
                    raw = _parse_json_list(resp.text)
                    break
                except Exception:
                    if attempt == max_retries:
                        raise RuntimeError(f"正向批判定输出解析失败(重试 {max_retries} 次)")
                    continue
            for r in raw:
                idx = int(r.get("index", -1))
                if idx < 0:
                    continue
                target = _locate_by_text(spec, cat, idx, str(r.get("text", "")), q_to_idx)
                item, needs_reask = _finalize_positive(spec, cat, target, r, chapter_text)
                if needs_reask:
                    # 单独重问一次(只问该条)
                    item_text = getattr(spec, cat)[target - _cat_start(spec, cat)]
                    for attempt2 in range(max_retries + 1):
                        try:
                            resp2 = await adapter.generate(
                                [{"role": "user", "content": _reask_prompt(item_text, chapter_text)}]
                            )
                            cost_cny += resp2.cost
                            model = resp2.model
                            raw2 = _parse_json_list(resp2.text)[0]
                            break
                        except Exception:
                            if attempt2 == max_retries:
                                raise RuntimeError(f"重问输出解析失败(重试 {max_retries} 次)")
                            continue
                    item2, needs_reask2 = _finalize_positive(spec, cat, target, raw2, chapter_text)
                    if needs_reask2:
                        # 第二次仍引证失败 → invalid
                        item2.verdict = "invalid"
                        item2.reason = "引证无效: 重问后 quote 仍不在正文中"
                    item = item2
                items[target] = item

    # ---- 3. 禁项逐条枚举(+熔断+复筛) ----
    for idx, text in enumerate(spec.must_not_happen):
        cat = "must_not_happen"
        abs_idx = _cat_start(spec, cat) + idx
        for attempt in range(max_retries + 1):
            try:
                resp = await adapter.generate([{"role": "user", "content": _negative_prompt(text, chapter_text)}])
                cost_cny += resp.cost
                model = resp.model
                raw = json.loads(resp.text)
                if not isinstance(raw, dict) or "quotes" not in raw:
                    raise ValueError("枚举输出缺 quotes")
                break
            except Exception:
                if attempt == max_retries:
                    raise RuntimeError(f"禁项枚举输出解析失败(重试 {max_retries} 次)")
                continue
        candidates = [q for q in raw.get("quotes", []) if quote_in_text(q, chapter_text)]
        raw_count = len(raw.get("quotes", []))
        overload = len(candidates) > OVERLOAD_LIMIT  # 结构修复:熔断后移,先复筛再说

        if not candidates:
            items[abs_idx] = F4Item(
                category=cat, index=abs_idx, text=text,
                verdict="met", model_verdict="met",
                quotes=[], reason="未枚举到相关句子",
                negative_screening=NegativeScreening(raw_candidates=raw_count, overload=False),
            )
            continue

        # 抽取式复筛(1 次调用,候选一批)
        for attempt in range(max_retries + 1):
            try:
                resp = await adapter.generate(
                    [{"role": "user", "content": _screen_prompt(text, candidates, chapter_text)}]
                )
                cost_cny += resp.cost
                model = resp.model
                raw_s = json.loads(resp.text)
                if not isinstance(raw_s, dict) or "screened" not in raw_s:
                    raise ValueError("复筛输出缺 screened")
                core_action = str(raw_s.get("core_action", "")).strip()
                break
            except Exception:
                if attempt == max_retries:
                    raise RuntimeError(f"复筛输出解析失败(重试 {max_retries} 次)")
                continue

        screened: list[ScreenEntry] = []
        kept_quotes: list[str] = []
        ambiguous = 0
        viewpoint = parse_viewpoint_person(text)
        for s in raw_s.get("screened", []):
            q = str(s.get("quote", ""))
            extracted = str(s.get("extracted", "")).strip()
            referent = str(s.get("referent", "")).strip()
            keep = bool(s.get("keep", False))
            if not quote_in_text(q, chapter_text):
                continue  # 候选句本身校验不过 → 丢弃
            if viewpoint is not None:
                # 视角类(F-4):答「无」→ 剔除;抽出的片段必须过连续子串校验;
                # 含代词 → referent 判定(视角人物或不明 → 剔除 + ambiguous)
                extracted_clean = "" if extracted in ("无", "没有", "none", "None", "没") else extracted
                if extracted_clean == "" or not quote_in_text(extracted_clean, chapter_text):
                    keep = False
                elif re.search(r"[他她它]们?|自己", extracted_clean):
                    if referent in ("", viewpoint, "不明", "无"):
                        keep = False
                        if referent == "":
                            ambiguous += 1
                    elif referent == viewpoint:
                        keep = False
                    else:
                        keep = True
                else:
                    keep = True
            else:
                # 非视角类:抽取片段满足核心动作(由模型判定 keep)+ 片段过校验
                keep = bool(keep) and bool(extracted) and quote_in_text(extracted, chapter_text)
            screened.append(ScreenEntry(quote=q, extracted=extracted, referent=referent, kept=keep))
            if keep:
                kept_quotes.append(q)

        if kept_quotes and (not overload or len(kept_quotes) <= OVERLOAD_LIMIT):
            items[abs_idx] = F4Item(
                category=cat, index=abs_idx, text=text,
                verdict="unmet", model_verdict="unmet",
                quotes=kept_quotes, reason="禁项出现",
                negative_screening=NegativeScreening(raw_candidates=raw_count, overload=overload, core_action=core_action, ambiguous=ambiguous, screened=screened),
            )
        elif overload and kept_quotes:
            # 熔断:原始候选超限且复筛后仍无法收敛到 ≤12 → 需人工核
            items[abs_idx] = F4Item(
                category=cat, index=abs_idx, text=text,
                verdict="unclear", model_verdict="unclear",
                quotes=[], reason=f"枚举过载({len(candidates)} 条候选, 复筛后仍 {len(kept_quotes)} 条), 需人工核",
                negative_screening=NegativeScreening(raw_candidates=raw_count, overload=True, core_action=core_action, ambiguous=ambiguous, screened=screened),
            )
        else:
            items[abs_idx] = F4Item(
                category=cat, index=abs_idx, text=text,
                verdict="met", model_verdict="met",
                quotes=[], reason="复筛后无违规句",
                negative_screening=NegativeScreening(raw_candidates=raw_count, overload=overload, core_action=core_action, ambiguous=ambiguous, screened=screened),
            )

    # ---- 汇总 ----
    ordered = [items[i] for i in sorted(items)]
    result = F4Result(
        planning_hash=spec.planning_hash,
        chapter=chapter,
        version=version,
        model=model,
        cost_cny=cost_cny,
        items=ordered,
        missing_category=spec.missing_category,
    )
    result.summary = _summarize(result)
    return result


def _finalize_positive(
    spec: ChecklistSpec, cat: str, idx: int, raw: dict, chapter_text: str,
) -> tuple[F4Item, bool]:
    """正向条:成分聚合 + quotes 校验。返回 (item, needs_reask)。"""
    text = getattr(spec, cat)[idx - _cat_start(spec, cat)]
    model_verdict = str(raw.get("verdict", "unclear"))
    if model_verdict not in ("met", "unmet", "unclear"):
        model_verdict = "unclear"

    components: list[F2Component] = []
    for c in raw.get("components", []):
        cq = [q for q in (c.get("quotes") or []) if isinstance(q, str)]
        components.append(F2Component(
            question=str(c.get("question", "")),
            verdict=str(c.get("verdict", "unclear")),
            quotes=cq,
        ))

    quotes = [q for q in (raw.get("quotes") or []) if isinstance(q, str)]
    reason = str(raw.get("reason", ""))

    if components:
        if any(c.verdict == "unmet" for c in components):
            model_verdict = "unmet"
            bad = next(c for c in components if c.verdict == "unmet")
            reason = f"成分不成立: {bad.question[:20]}" + (f"; {reason}" if reason else "")
        elif all(c.verdict == "met" for c in components):
            model_verdict = "met"
        elif any(c.verdict == "unclear" for c in components):
            model_verdict = "unclear"

    # 引证校验:顶层与成分级任一不在正文 → 该条需重问(模型判 met 时)
    all_quotes = list(quotes) + [q for c in components for q in c.quotes]
    invalid_quote = any(not quote_in_text(q, chapter_text) for q in all_quotes)
    need_quote = (model_verdict == "met" and cat != "must_not_happen") or (
        cat == "must_not_happen" and model_verdict == "unmet"
    )
    missing_quote = need_quote and not quotes

    if invalid_quote or missing_quote:
        # 重问一次;若重问后仍失败,由调用方判 invalid
        return F4Item(
            category=cat, index=idx, text=text,
            verdict="invalid", model_verdict=model_verdict,
            quotes=quotes, components=components,
            reason="引证无效: quote 不在正文中" + (f"; {reason}" if reason else ""),
        ), True

    return F4Item(
        category=cat, index=idx, text=text,
        verdict=model_verdict, model_verdict=model_verdict,
        quotes=quotes, components=components, reason=reason,
    ), False


def _summarize(result: F4Result) -> dict:
    total = len(result.items)
    counts = {"met": 0, "unmet": 0, "unclear": 0, "invalid": 0}
    for i in result.items:
        counts[i.verdict] = counts.get(i.verdict, 0) + 1
    invalid_rate = counts["invalid"] / total if total else 0.0
    return {
        "total": total,
        "met": counts["met"],
        "unmet": counts["unmet"],
        "unclear": counts["unclear"],
        "invalid": counts["invalid"],
        "invalid_rate": round(invalid_rate, 3),
        "missing_category": result.missing_category,
    }


def render_markdown_f4(result: F4Result) -> str:
    """人可读清单:没做到排最前,作者最关心。"""
    verdict_label = {"met": "✅ met", "unmet": "❌ unmet", "unclear": "❓ unclear", "invalid": "⚠️ 引证无效"}
    s = result.summary

    unmet_items = [i for i in result.items if i.verdict == "unmet"]
    unclear_items = [i for i in result.items if i.verdict == "unclear"]
    invalid_items = [i for i in result.items if i.verdict == "invalid"]
    met_items = [i for i in result.items if i.verdict == "met"]

    lines = [
        f"# 第 {result.chapter} 章 · {result.version} 偏离清单",
        "",
        f"戏核 `{result.planning_hash}` · 引擎 {result.engine_version} · "
        f"{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "> **本表是提示，不是判决。请以你自己的判断为准。**",
        "",
    ]

    def _cat(item) -> str:
        return CAT_LABEL.get(item.category, item.category)

    lines.append(f"## 没做到（{len(unmet_items)} 条）")
    for it in unmet_items:
        lines.append(f"- **[{_cat(it)}] {it.text}**")
        if it.quotes:
            lines.append(f"  - 正文里：{''.join(f'「{q}」' for q in it.quotes[:5])}")
        else:
            lines.append("  - 正文里：全文未找到")
        if it.reason:
            lines.append(f"  - 原因：{it.reason}")
    if not unmet_items:
        lines.append("（无）")
    lines.append("")

    lines.append(f"## 说不清（{len(unclear_items)} 条）")
    for it in unclear_items:
        lines.append(f"- **[{_cat(it)}] {it.text}**")
        if it.negative_screening and it.negative_screening.overload:
            lines.append(f"  - 枚举过载：原始候选 {it.negative_screening.raw_candidates} 条，需人工核")
        if it.reason:
            lines.append(f"  - 原因：{it.reason}")
    if not unclear_items:
        lines.append("（无）")
    lines.append("")

    lines.append(f"## 引证无效（{len(invalid_items)} 条）")
    for it in invalid_items:
        lines.append(f"- **[{_cat(it)}] {it.text}**（模型原判 {it.model_verdict}）")
        if it.reason:
            lines.append(f"  - 原因：{it.reason}")
    if not invalid_items:
        lines.append("（无）")
    lines.append("")

    lines.append(f"## 做到了（{len(met_items)} 条）")
    for it in met_items:
        lines.append(f"- [{_cat(it)}] {it.text}")
    if not met_items:
        lines.append("（无）")

    return "\n".join(lines)
