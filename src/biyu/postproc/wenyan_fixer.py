"""文白夹杂修复器。

评审反馈:ch5 出现"亦/便/此/吾"等文言词,与 ch1-4 口语化叙述风格不一致。
评审建议:全部替换成口语形式。

策略:词级替换,保留特殊语境(如确实的古风对话、引用古文等)。
"""
from __future__ import annotations

from dataclasses import dataclass, field


# 替换规则(关键字 -> 替换词)
# None 表示保留不替换
WENYAN_REPLACEMENTS: dict[str, str | None] = {
    "亦": "也",
    "便": "就",
    "吾": "我",
    # "此": "这",     # ← 删除(此刻/如此/彼此都会被误伤)
    "彼": "那",
    "尔": "你",
    "汝": "你",
    # "其": "他/她",  # ← 删除(占位字符不该当替换值)
    "乃": "是",
    # "已": "已经",   # ← 删除("已经"会被替换为"已经经")
}


@dataclass
class WenyanFixResult:
    original_text: str
    fixed_text: str
    replacements: list[dict] = field(default_factory=list)


def fix_wenyan(text: str, in_secret_realm: bool = False) -> WenyanFixResult:
    """主入口。

    in_secret_realm: 如果是秘境内章节,不修复引号内历史人物对话中的文言
                     秘境外章节,全部替换
    """
    fixed = text
    replacements: list[dict] = []

    for wenyan, modern in WENYAN_REPLACEMENTS.items():
        if modern is None:
            continue

        if in_secret_realm:
            # 秘境内:只替换不在引号内的
            new_fixed, n = _replace_outside_quotes(fixed, wenyan, modern)
            if n > 0:
                replacements.append({"from": wenyan, "to": modern, "count": n})
                fixed = new_fixed
        else:
            # 秘境外:全替换
            n = fixed.count(wenyan)
            if n > 0:
                fixed = fixed.replace(wenyan, modern)
                replacements.append({"from": wenyan, "to": modern, "count": n})

    return WenyanFixResult(
        original_text=text,
        fixed_text=fixed,
        replacements=replacements,
    )


def _replace_outside_quotes(text: str, old: str, new: str) -> tuple[str, int]:
    """替换不在引号内的字符。引号字符:"「」"""
    result: list[str] = []
    i = 0
    in_quote = False
    quote_chars = '""「」'
    count = 0
    while i < len(text):
        ch = text[i]
        if ch in quote_chars:
            in_quote = not in_quote
            result.append(ch)
            i += 1
        elif not in_quote and ch == old:
            result.append(new)
            count += 1
            i += 1
        else:
            result.append(ch)
            i += 1
    return "".join(result), count
