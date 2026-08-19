"""破折号修复器。

评审反馈:破折号是 AI 文最大的标记,平均每 700 字一个。
模型在战斗章节(ch1=4.9/k, ch3=6.0/k)无法靠 prompt 自我抑制。

策略:正则识别 5 类破折号用法,4 类替换为更自然的表达,1 类保留。

5 类用法:
1. 戛然停顿(对话被打断):"这——"  → 保留(评审认可)
2. 句中补充说明:"是物理上的——空气变得滞重" → 替换为句号
3. 句末延长/感叹:"洒了江面一片——" → 替换为句号
4. 转折(等等——):"等等——北岸?" → 替换为感叹号
5. 拟声/情绪:"卧槽——" → 替换为感叹号

阈值控制:
- 修复后破折号密度 ≤ 1.5/千字(评审建议)
- 优先修复"补充说明"类(对剧情影响最小)
- 保护"对话戛然停顿"类(影响节奏感)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class DashFixResult:
    original_text: str
    fixed_text: str
    original_count: int
    fixed_count: int
    replacements: list[dict] = field(default_factory=list)


# —— 规则 1:对话内戛然停顿(保留) ——
# 引号内 ≤15 字 + 破折号 + 引号闭合 = 戛然停顿,不替换
# 这条由处理顺序保护:其他规则先执行,剩下在引号内短句末尾的破折号自然保留

# —— 规则 2:句末延长/感叹 → 句号 ——
# 模式:非引号字符 + 破折号 + (换行/文件尾/句号)
SENTENCE_END_DASH_PATTERN = re.compile(r'([^"」])——(\n|$|。)')


def fix_sentence_end_dash(text: str) -> str:
    """句末破折号(非对话)替换为句号。"""
    return SENTENCE_END_DASH_PATTERN.sub(r'\1。\2', text)


# —— 规则 3:句中补充说明 → 句号 ——
# 模式:中文字符 + 破折号 + 中文字符
SENTENCE_MIDDLE_DASH_PATTERN = re.compile(r'([\u4e00-\u9fff])——([\u4e00-\u9fff])')


def fix_sentence_middle_dash(text: str) -> str:
    """句中破折号(中文-中文)替换为句号。"""
    return SENTENCE_MIDDLE_DASH_PATTERN.sub(r'\1。\2', text)


# —— 规则 4:转折/反问 → 感叹号 ——
TRANSITION_DASH_PATTERN = re.compile(r'(等等|啊|哎|嗯|哦)——')


def fix_transition_dash(text: str) -> str:
    """单字反应词后的破折号替换为感叹号。"""
    return TRANSITION_DASH_PATTERN.sub(r'\1!', text)


# —— 规则 5:对话内拟声/情绪 → 感叹号 ——
# 模式:引号内2-6字+破折号+引号闭合(不在引号最末尾紧跟其他文字)
DIALOGUE_EMOTION_PATTERN = re.compile(r'(["\u201c\u201d])([\u4e00-\u9fff]{2,6})——(["\u201c\u201d])')


def fix_dialogue_emotion_dash(text: str) -> str:
    """对话内短拟声/情绪词后的破折号替换为感叹号。"""
    return DIALOGUE_EMOTION_PATTERN.sub(r'\1\2!\3', text)


# —— 主入口 ——
def fix_dashes(text: str) -> DashFixResult:
    """主入口:对正文做破折号修复。

    应用顺序:
    1. 对话内拟声/情绪 → 感叹号(规则 5)
    2. 转折/反问 → 感叹号(规则 4)
    3. 句末延长 → 句号(规则 2)
    4. 句中补充 → 句号(规则 3)

    剩下的"——"属于规则 1(对话内戛然停顿),保留不动。
    """
    original_count = text.count('——')
    fixed_text = text

    replacements = []

    # 规则 5: 对话内拟声/情绪 → 感叹号
    new_text = fix_dialogue_emotion_dash(fixed_text)
    if new_text != fixed_text:
        replacements.append({
            "rule": "dialogue_emotion",
            "before_count": fixed_text.count('——'),
            "after_count": new_text.count('——'),
        })
        fixed_text = new_text

    # 规则 4: 转折/反问 → 感叹号
    new_text = fix_transition_dash(fixed_text)
    if new_text != fixed_text:
        replacements.append({
            "rule": "transition",
            "before_count": fixed_text.count('——'),
            "after_count": new_text.count('——'),
        })
        fixed_text = new_text

    # 规则 2: 句末延长 → 句号
    new_text = fix_sentence_end_dash(fixed_text)
    if new_text != fixed_text:
        replacements.append({
            "rule": "sentence_end",
            "before_count": fixed_text.count('——'),
            "after_count": new_text.count('——'),
        })
        fixed_text = new_text

    # 规则 3: 句中中文-中文 → 句号
    new_text = fix_sentence_middle_dash(fixed_text)
    if new_text != fixed_text:
        replacements.append({
            "rule": "sentence_middle",
            "before_count": fixed_text.count('——'),
            "after_count": new_text.count('——'),
        })
        fixed_text = new_text

    fixed_count = fixed_text.count('——')

    return DashFixResult(
        original_text=text,
        fixed_text=fixed_text,
        original_count=original_count,
        fixed_count=fixed_count,
        replacements=replacements,
    )
