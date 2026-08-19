"""P8-M3 T7 prompt 文本: 起名 system prompt (设计稿 2026-07-04 定稿).

用法:
    is_naming_placeholder() -> bool   # False = 真 LLM 模式(2026-07-06 B 核已过)
    set_naming_placeholder(val)       # B 核过后翻转为 False

设计:
- NAMING_SYSTEM_PROMPT 取自设计稿,末句含派发单附加句(命名范式参考注入)
- build_naming_messages() 注入 prompts/assets/命名范式_v0.md 为参考语料
- 占位开关 False(B 核已过),启用真 LLM
"""
from __future__ import annotations

from biyu.config import get_project_root

# ---------------------------------------------------------------------------
# 起名 system prompt — 设计稿 2026-07-04 定稿 verbatim
# 末句即派发单附加句(D-86 §3 原文),已嵌入设计稿第三节末尾。
# ---------------------------------------------------------------------------

NAMING_SYSTEM_PROMPT = """给一本中文网文起书名。你会拿到:作品设想或简介、题材、当前在榜书名列表(参照语料)。
产出 8-10 个候选,按风格分组(如:直给爽点型 / 悬念钩子型 / 长句流水型 / 反差幽默型),每个候选附一句"为什么可能有效"——它勾住哪类读者、给出什么预期。
评判一个书名看三条:**信息量**(题材+爽点+差异点至少占二)、**口语可读**(读得顺、记得住)、**搜索友好**(不与在榜书重名或近似,自带可检索的独特词)。
对照榜单要明说:借了哪个在榜名的**结构**(如"从X开始Y"),但候选不得与任何在榜书名重复或高度近似。
不解释创作理论,不输出候选之外的建议。
你可能还会拿到一份『命名范式』参考(从在榜书名蒸馏的结构模板与避坑清单):优先借它的结构起名,并在分组时标注所用范式;拿不到该参考时,按上述规则独立起名。"""


# ---------------------------------------------------------------------------
# 占位开关
# ---------------------------------------------------------------------------

_naming_placeholder: bool = False  # B 核已过(2026-07-06),启用真 LLM


def is_naming_placeholder() -> bool:
    return _naming_placeholder


def set_naming_placeholder(val: bool) -> None:
    global _naming_placeholder
    _naming_placeholder = val


# ---------------------------------------------------------------------------
# 命名范式参考读取
# ---------------------------------------------------------------------------


def read_paradigm_ref() -> str:
    """读 prompts/assets/命名范式_v0.md 全文,作为命名参考注入。"""
    root = get_project_root()
    path = root / "prompts" / "assets" / "命名范式_v0.md"
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"Required prompt asset could not be read: {path}") from exc


# ---------------------------------------------------------------------------
# 消息构造器
# ---------------------------------------------------------------------------


def build_naming_messages(
    idea: str,
    genre: str,
    scan_data: str,
    paradigm_ref: str,
) -> list[dict]:
    """构造起名 LLM 消息列表。

    Args:
        idea: 作品设想文本
        genre: 题材代号
        scan_data: 扫榜缓存文本(在榜书名参照语料)
        paradigm_ref: 命名范式参考文本

    Returns:
        messages: [system, user]
    """
    user_content = f"""作品设想:{idea or '(空)'}
题材:{genre}

当前在榜书名列表(参照语料):
{scan_data if scan_data else '(暂无扫榜数据)'}

命名范式参考:
{paradigm_ref if paradigm_ref else '(无)'}

请按规则产出候选,并标注所用范式。

请以 JSON 格式输出(不要 markdown 代码块),结构为:
{{"candidates": [{{"name": "书名", "paradigm": "范式", "reason": "为什么有效"}}]}}"""
    return [
        {"role": "system", "content": NAMING_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
