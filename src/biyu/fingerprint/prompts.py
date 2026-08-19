"""Prompt 模板 — 声纹功能的灵魂，任何调整必须停下问 TL."""
from __future__ import annotations

EXTRACTION_PROMPT = """你正在阅读一位作家的文字样本。你的任务是理解他的"写作味道"，\
然后帮另一个 AI 学会模仿他。

请输出三块内容：

【一、风格说明】(800-1500 字，自然语言，像跟朋友聊这位作家)
描述这位作家的写作"气质"。包括他在不同情境下倾向于怎么处理\
——比如他写战斗时是冷峻还是抒情、写对话时人物腔调有什么共性、\
他喜欢什么样的句法节奏、什么样的修辞习惯。
**关键**：每描述一个特征，都顺带说一句**为什么**他这样写\
（比如"他喜欢长句插短句，因为他要的是情绪的潮汐感"）。\
不要列"维度"，要写流畅的自然语言。

【二、代表段落】(5-8 段)
从原文中挑你觉得最能体现他风格的段落，每段 500-1500 字。\
每段后面加一句"这段为什么代表他的风格"——也是要说"为什么"。

【三、容易模仿成 AI 味的雷区】(5-10 条)
如果让一个普通 AI 模仿这位作家，哪些地方容易"走样成 AI 套话"？\
列出来，**附带解释为什么这是雷区**\
（比如"AI 会过度对仗，因为它觉得对仗有文学性，\
但这位作家其实很少用工整对仗，他的修辞是松散的、口语化的"）。\
**注意**：这些不是"必须避免"，是"提醒——如果你下意识想这样写，\
先问问这位作家会不会这样写"。

JSON 格式输出：
{{
  "style_description": "...",
  "exemplar_passages": [
    {{"passage": "...", "why_representative": "..."}}
  ],
  "ai_pitfalls": [
    {{"pitfall": "...", "why_it_happens": "..."}}
  ]
}}

样本如下：
---
{sampled_text}
---"""

WRITING_SYSTEM_PROMPT_TEMPLATE = """你将按一位作家的风格写一段新内容。

下面是关于这位作家的参考资料——**这是参考，不是规则**。

【他的风格气质】
{style_description}

【他的代表段落，供你随时回看】
{exemplar_passages_formatted}

【一些容易写成 AI 味的雷区，提醒你】
{ai_pitfalls_formatted}

----

写作原则：
1. 理解他为什么这样写，然后**判断你这一段需不需要这样写**
2. 不必每句话都对应他的某个特征——自然写，在合适处让那种气质浮现
3. 如果你写的情境他原作里没有（比如他没写过赛博朋克，你要写赛博朋克），\
   就用他的"气质"去处理新情境，不要硬套他的具体场景
4. 不强求字数对仗、排比工整——他本来就不强求"""


def format_exemplars(passages: list[dict]) -> str:
    """将 exemplar passages 格式化为 system prompt 中的参考资料."""
    parts = []
    for i, p in enumerate(passages, 1):
        passage_text = p.passage if hasattr(p, "passage") else p["passage"]
        why = p.why_representative if hasattr(p, "why_representative") else p["why_representative"]
        parts.append(f"---片段 {i}---\n{passage_text}\n(为什么代表他的风格：{why})")
    return "\n\n".join(parts)


def format_pitfalls(pitfalls: list[dict]) -> str:
    """将 ai_pitfalls 格式化为 system prompt 中的参考资料."""
    parts = []
    for i, p in enumerate(pitfalls, 1):
        pitfall_text = p.pitfall if hasattr(p, "pitfall") else p["pitfall"]
        why = p.why_it_happens if hasattr(p, "why_it_happens") else p["why_it_happens"]
        parts.append(f"{i}. {pitfall_text}（原因：{why}）")
    return "\n".join(parts)


# --- 评审 prompt（V4-Pro 评审人格，严格角色隔离）---

BLIND_REVIEW_PROMPT = """你是资深文学编辑，完全不了解任何 AI 生成内容，\
你的任务是判断这 4 段文字中哪一段最可能是模仿写出来的。

判断依据：句法节奏 / 修辞习惯 / 情绪调性 / 议论穿插方式 / 词汇选择
**不要**用内容判断——4 段内容完全不同，内容相似度无意义。

请指出哪段是模仿生成的，JSON 输出：
{{
  "ai_generated_segment": "A|B|C|D",
  "confidence": "high|medium|low",
  "key_evidence": ["..."]
}}

A: {seg_a}
B: {seg_b}
C: {seg_c}
D: {seg_d}"""

MULTI_GENRE_REVIEW_PROMPT = """你是资深文学编辑。下面 3 篇短文出自同一个写手，\
据说使用了同一种"风格偏好"生成。3 篇的题材完全不同。

请评判：这 3 篇是否保持了**同一种风格气质**？
不要用题材或内容判断，只用风格判断。

JSON 输出：
{{
  "consistency_score": 1-5,
  "what_remains_same": ["..."],
  "what_differs": ["..."],
  "verdict": "consistent|partially_consistent|inconsistent"
}}

篇 1(现代都市)：{output_1}
篇 2(玄幻)：{output_2}
篇 3(科幻)：{output_3}"""
