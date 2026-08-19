"""P8-M3 T3/T4 prompt 文本: 责编/导演 system prompt (设计稿 2026-07-04 定稿)。

用法:
    PLACEHOLDER_FLAGS["editor"] = False   # B 核已过,启用真 LLM(2026-07-06)
    PLACEHOLDER_FLAGS["director"] = False # B 核已过,启用真 LLM(2026-07-06)
    # B 核过后翻转为 False 即启用真 LLM

占位开关 B 核后 False(真 LLM),每角色独立。
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 责编 system prompt — 设计稿 2026-07-04 定稿 verbatim
# ---------------------------------------------------------------------------

EDITOR_SYSTEM_PROMPT = """你是这本书的责任编辑,作者的同行,不是客服。规矩:
一,**先查后说**。凡涉及本书事实(人物、设定、前文情节),必须先调用工具核对再下判断;没查到的就说"我需要先查"或"记忆里没有",不许脑补。每个判断给出处(第几章、原文短引)。
二,**像编辑,不像检查器**。问题分轻重:先说最伤读者的(弃书点、逻辑硬伤),再说锦上添花的;别把七类问题平铺成清单。没有问题就说没有,不硬凑。
三,**不空夸,不空贬**。夸要夸到具体的字上,批要批到具体的字上,并说清"伤到谁"(哪类读者、什么预期)。
四,**决定权在作者**。你给判断、理由和可选改法(最多三个,各带代价),不替作者选;作者否掉的方案不再纠缠。
五,**不代写正文**。除非作者点名要示例,示例不超过两句。
语气:直接、省字、同行之间不客套。"""

# ---------------------------------------------------------------------------
# 导演会诊 system prompt — 设计稿 2026-07-04 定稿 verbatim
# ---------------------------------------------------------------------------

DIRECTOR_SYSTEM_PROMPT = """你是这本书的导演,作者动笔前找你会诊剧情。作者会给你一段剧情想法,可能附特殊要求。你做三件事,按序:
一,**冲突预警**:对照本书记忆(truth_files)与既有伏笔,指出这段剧情与已有设定、人物逻辑、时间线的冲突处,逐条引证(哪一章、什么设定);没冲突就明说"记忆层面无冲突"。
二,**节奏与市场判断**:这段在本卷里承担什么功能(铺垫/爆发/过渡)、爽点密度够不够、读者此刻的预期是什么、有没有更狠的写法——判断要引创作规律(craft)或榜单参照,不引经据典就标"个人判断"。
三,**给方案不做主**:可选方案最多三个,各带一句代价;作者的特殊要求高于你的偏好——你可以说"这个要求会带来 X 代价",但作者坚持就按作者的收进纪要。
红线:不写正文、不出细纲(那是开写后 architect 的活);会诊只到"方向与要求定下来"为止。作者说"收束"时,如实归纳:拍板的要求清单、被否的方案、遗留待办——不夹带你被否掉的私货。"""

# ---------------------------------------------------------------------------
# 占位开关(每角色独立)
# ---------------------------------------------------------------------------
# True = 占位模式(固定文案 + 工具结果,无 LLM 调用)
# False = 启用真 LLM(使用上方 system prompt)
PLACEHOLDER_FLAGS: dict[str, bool] = {
    "editor": False,
    "director": False,
}

# ---------------------------------------------------------------------------
# 工具说明段(P8-M3R R2,D-96 分层读书)— 人格段 verbatim 不动,此段独立追加
# ---------------------------------------------------------------------------

TOOLS_DESCRIPTION = """可用工具与 D-96 分层读书规则:

工具列表:
- read_truth_files:查真相文件(当前状态/粒子账/钩子)
- look_up_character:查角色档案
- look_up_setting:查设定/worldbook
- read_review:读最新审读结果
- read_craft:读创作规律蒸馏
- read_scan_cache:读扫榜缓存
- read_chapter:读章节正文

D-96 分层读书(L2 点读规则):
- L0 细纲/书档案:必带(无则建议作者先倒灌 `biyu refresh` 建档)
- L1 truth_files / worldbook:定点查(用 read_truth_files / look_up_setting)
- L2 read_chapter 点读:**每轮 ≤3 章上限**;超限自动采样前 3 章 + 采样声明;单章 ≤4000 字截断
- L3 区间读:未开通
- **任何路径禁整本入上下文**;需要章节正文时用 read_chapter 点读,不自行拼接

调用规则:涉及前文情节核对时,先用 read_chapter 读指定章(消息含"第 X 章"时自动解析);不指定章号时按需查 truth_files 或 look_up_character/setting。"""


# ---------------------------------------------------------------------------
# 消息构造器
# ---------------------------------------------------------------------------


def build_editor_messages(
    conversation_history: list[dict],
    tool_results: list[dict],
    user_message: str,
) -> list[dict]:
    """构造责编 LLM 消息列表。

    Args:
        conversation_history: 历史消息列表 [{role, content}]
        tool_results: 本轮工具查询结果列表 [{name, args, result, cost}]
        user_message: 用户本轮输入

    Returns:
        messages: 完整消息列表,含 system + history + tool_context + user
    """
    messages: list[dict] = [
        {"role": "system", "content": EDITOR_SYSTEM_PROMPT},
        # R2:工具说明段(人格段 verbatim 不动,此段独立追加)
        {"role": "system", "content": TOOLS_DESCRIPTION},
    ]
    # 对话历史
    for msg in conversation_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    # 本轮工具结果作为上下文
    if tool_results:
        tool_context = "工具查询结果:\n" + "\n".join(
            f"- {tr['name']}({tr['args']}):\n{tr['result'][:1000]}"
            for tr in tool_results
        )
        messages.append({"role": "system", "content": tool_context})
    # 当前用户消息
    messages.append({"role": "user", "content": user_message})
    return messages


def build_director_messages(
    conversation_history: list[dict],
    tool_results: list[dict],
    user_message: str,
) -> list[dict]:
    """构造导演 LLM 消息列表。

    Args:
        conversation_history: 历史消息列表 [{role, content}]
        tool_results: 本轮工具查询结果列表 [{name, args, result, cost}]
        user_message: 用户本轮输入

    Returns:
        messages: 完整消息列表,含 system + history + tool_context + user
    """
    messages: list[dict] = [
        {"role": "system", "content": DIRECTOR_SYSTEM_PROMPT},
        # R2:工具说明段(人格段 verbatim 不动,此段独立追加)
        {"role": "system", "content": TOOLS_DESCRIPTION},
    ]
    for msg in conversation_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    if tool_results:
        tool_context = "会诊资料:\n" + "\n".join(
            f"- {tr['name']}({tr['args']}):\n{tr['result'][:1000]}"
            for tr in tool_results
        )
        messages.append({"role": "system", "content": tool_context})
    messages.append({"role": "user", "content": user_message})
    return messages
