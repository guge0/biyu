"""改写生成 — 提示词逐字取自已验证原型。

- back_translate: 直译式回译(r12_models.py,glm-5.2 实测)
- zhzh:   中文改中文 few-shot(r14_fewshot.py 的 SYS,示范块由调用方传入)
- polish: 第三层小手术(改写规则提炼自 Humanizer-zh,MIT,作者 歸藏 / op7418)
- deai:   独立去 AI 味(r13_humanizer.py 的 SKILL+WRAP,SKILL 正文随包分发)

模型输出为空或带思考内容时按现有适配器约定处理:
适配器把思维链放在 reasoning_content、正文放在 text,这里只取 text;
空正文/传输异常按原型约定返 ""(交给守卫判「空」,不重试不抛出)。
"""
from __future__ import annotations

import re
from pathlib import Path

# ---- zhzh:system 头尾逐字取自 r14_fewshot.py 的 SYS,中间示范块换成传入的 pairs ----
SYS_ZHZH_HEAD = (
    "你是网络小说的改稿编辑。下面是同一位编辑改稿的若干示范，每对是『原文→改写』。仔细体会他的改法："
    "用词更直白普通，句子写得松一点、笨一点，该补的『的』『了』『之后』『的时候』照补，"
    "精雕细琢的动词换成常用词，但意思一点不变，也不加内容。\n\n【示范】\n"
)
SYS_ZHZH_TAIL = (
    "\n【示范结束】\n\n请完全照这种改法改写用户给的这一段。规则：⟦D1⟧ ⟦K1⟧ 这类占位符代表对白和专名，"
    "原样原位保留；分段不变；不用破折号；不用『不是……而是……』；只输出改写后的正文。"
)

# ---- polish:第三层小手术(S-8-1 定稿提示词,规则提炼自 Humanizer-zh,MIT) ----
SYS_POLISH = (
    "你是中文小说的校对。下面这段已经改好，只许做小手术，其它句子一个字都别动：\n"
    "1. 破折号一律去掉，改成逗号、句号或拆句。\n"
    "2. 「不是……而是……」「与其说……不如说……」这类否定对照拆成直说。\n"
    "3. 删掉多余的「他的」「她的」「它」；「并」连接两个动作的，改成「，」或「就」「又」；「使……」句式改成直说。\n"
    "4. 英式语序、病句、重复字顺过来。\n"
    "5. 三项并列、排比，能删一项就删一项。\n"
    "⟦D1⟧ ⟦K1⟧ 这类占位符原样原位保留；分段不变；不加内容、不加修辞、不改情节。只输出正文。"
)

# ---- deai:r13 的 WRAP 去掉开头「以上是……指南」那句,拼在 SKILL 正文后面 ----
DEAI_WRAP = (
    "\n\n=====\n现在你要处理的是一章中文网络小说的一小截。额外的硬性规则:\n"
    "1. 形如 ⟦D1⟧ ⟦K1⟧ 的占位符代表对白和专有名词,必须原样、原位置保留,一个不少,不许改动。\n"
    "2. 不增删情节和信息,不改变事件顺序;分段与原文一致(每段对应一段)。\n"
    "3. 这是小说叙述,不是文章:保留人物视角和画面,不要改成说明文,不要加感想和点评。\n"
    "4. 破折号一律去掉,改用逗号、句号或改写句子;「不是……而是……」这类否定排比一律拆掉。\n"
    "5. 只输出改写后的正文,不要解释、不要列清单、不要输出初稿和点评。\n"
)

_SKILL_PATH = Path(__file__).with_name("data") / "humanizer_zh_SKILL.md"
_skill_body_cache: "str | None" = None


def _deai_system() -> str:
    """SKILL.md 正文(去 frontmatter)+ WRAP;读不到 SKILL 就只剩 WRAP(守卫兜底)。"""
    global _skill_body_cache
    if _skill_body_cache is None:
        try:
            raw = _SKILL_PATH.read_text(encoding="utf-8-sig")
        except OSError:
            raw = ""
        _skill_body_cache = re.sub(r"^---.*?---\s*", "", raw, flags=re.S)
    return _skill_body_cache + DEAI_WRAP


def _pair_texts(pair) -> "tuple[str, str]":
    """示范对取 (src, dst):兼容 dict 与 (src, dst) 元组两种形态。"""
    if isinstance(pair, dict):
        return str(pair.get("src") or ""), str(pair.get("dst") or "")
    src, dst = pair
    return str(src), str(dst)


async def _generate(adapter, system: str, user: str, *,
                    temperature: float = 1.0, max_tokens: int = 2000) -> str:
    """一次生成:正文为空/异常返 ""。输出后清洁(空白/半角标点/占位符句号)交给引擎的 clean。"""
    try:
        resp = await adapter.generate(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            thinking={"type": "disabled"},   # GLM/DeepSeek 适配器认这个参数,其它适配器忽略
        )
    except Exception:
        return ""
    return (getattr(resp, "text", "") or "").strip()


async def back_translate(adapter, masked: str, keep: list[str]) -> str:
    """直译式回译:中→英→中(按英文语序硬译)。keep 里的词要求原样保留。"""
    en = await _generate(adapter, to_en_prompt(keep), masked)
    if not en:
        return ""
    return await _generate(adapter, TO_ZH, en)


async def zhzh(adapter, masked: str, pairs: list) -> str:
    """中文改中文 few-shot(r14 的 SYS + 传入示范对)。temperature 0.9 关思考,同 r14。"""
    exemplars = "\n\n".join("原文：%s\n改写：%s" % _pair_texts(p) for p in pairs)
    system = SYS_ZHZH_HEAD + exemplars + SYS_ZHZH_TAIL
    return await _generate(adapter, system, masked, temperature=0.9)


async def polish(adapter, masked: str) -> str:
    """第三层小手术(temperature 0.7,同 r13 小手术实验)。"""
    return await _generate(adapter, SYS_POLISH, masked, temperature=0.7)


async def deai(adapter, masked: str) -> str:
    """独立去 AI 味(不进降分流程)。temperature 0.7、max_tokens 4000,同 r13。"""
    return await _generate(adapter, _deai_system(), masked, temperature=0.7, max_tokens=4000)


def to_en_prompt(terms: list[str]) -> str:
    return (
        "Translate this Chinese web-novel passage into plain English. "
        "Keep every token like ⟦D1⟧ or ⟦K1⟧ exactly as it is and keep the line breaks."
        + (
            " Do NOT translate these Chinese terms; leave them in Chinese characters exactly: "
            + ", ".join(terms) + "."
            if terms else ""
        )
        + " Output only the translation. Do not use any tools."
    )


TO_ZH = (
    "把下面的英文直译成中文,按英文的语序和措辞来译,不要润色。"
    "⟦D1⟧ ⟦K1⟧ 这类占位符原样保留;夹在英文里的中文词原样保留;换行不变。"
    "必须全部译成中文,不许留下英文单词;标点用中文全角。"
    "只输出译文,不要使用任何工具。"
)
