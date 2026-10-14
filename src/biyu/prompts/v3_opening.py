"""兼容垫片——内容已拆分（2026-10）：
- 导演提示词        → biyu.prompts.director_prompt.build_planning_prompt
- v3 写手提示（遗留）→ biyu.prompts.writer_v3_legacy
- 句式黑名单        → biyu.prompts.style_blacklist
本文件仅转发，勿新增内容。
"""
from __future__ import annotations

from biyu.prompts.style_blacklist import STYLE_BLACKLIST, WORD_BLACKLIST
from biyu.prompts.writer_v3_legacy import (
    SETTING_LOCK,
    V3_FEW_SHOT,
    V3_OPENING_SYSTEM,
    build_polish_prompt,
    build_writer_user_prompt,
)
from biyu.prompts.director_prompt import build_planning_prompt

__all__ = [
    "STYLE_BLACKLIST", "WORD_BLACKLIST", "SETTING_LOCK", "V3_FEW_SHOT",
    "V3_OPENING_SYSTEM", "build_writer_user_prompt", "build_planning_prompt",
    "build_polish_prompt",
]
