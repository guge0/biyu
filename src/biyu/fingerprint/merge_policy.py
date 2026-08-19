"""Small shared contracts retained after D-160 removed runtime merging."""
from __future__ import annotations

from typing import Any


SYSTEM_USAGE_POLICY = [
    "这是参考，不是硬规则。",
    "不必每句话都对应某条规则，只在合适的场景与情绪节点让它自然生效。",
    "学的是处理方式，不照搬具体人物、意象、场景。",
    "与本书自蒸馏冲突时，以本书为准。",
]

# Canonical names remain solely for protecting author-edited lines when a
# machine-backed profile is refreshed.  They no longer arbitrate profiles.
DIMENSION_ALIASES: dict[str, str] = {
    "句子长短与节奏偏好": "句子长短与节奏",
    "比喻/形容的密度": "比喻与通感",
    "明确禁用的表达": "明确避坑",
    "写作雷区": "明确避坑",
}

_INSUFFICIENT_PREFIX = "现有反馈不足，暂不设规则"


def canonical_dimension(dimension: str) -> str:
    """Return the comparison key used by author-edit overwrite protection."""
    clean = str(dimension).strip()
    return DIMENSION_ALIASES.get(clean, clean)


def is_effective_line(line: dict[str, Any]) -> bool:
    text = str(line.get("text", "")).strip()
    return bool(text) and not text.startswith(_INSUFFICIENT_PREFIX)
