"""直译式回译与顺稿 — 提示词逐字取自 _s6_ref/r12_models.py(已验证原型,glm-5.2 实测)。

模型输出为空或带思考内容时按现有适配器约定处理:
适配器把思维链放在 reasoning_content、正文放在 text,这里只取 text;
空正文/传输异常按原型约定返 ""(交给守卫判「空」,不重试不抛出)。
"""
from __future__ import annotations


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

SMOOTH = (
    "下面是一小段小说,带明显的翻译腔。请只做最小改动,把它顺成通顺的中文:"
    "删掉多余的『他的』『那个』『了』,把英制单位和外文式语序改回中文习惯,"
    "修正病句和重复字。不要润色,不要加修辞,不要改写本来就通顺的句子,改动越少越好。"
    "⟦D1⟧ 这类占位符原样保留,分段不变,人名地名器物名和数字不变。只输出正文。"
)


async def _generate(adapter, system: str, user: str) -> str:
    """一次生成:正文为空/异常返 ""。输出后清洁(空白/半角标点/占位符句号)交给引擎的 clean。"""
    try:
        resp = await adapter.generate(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=1.0,
            max_tokens=2000,
            thinking={"type": "disabled"},   # 只有 GLM 适配器认这个参数,其它适配器忽略
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


async def smooth(adapter, masked: str) -> str:
    """顺稿:最小改动去翻译腔。"""
    return await _generate(adapter, SMOOTH, masked)
