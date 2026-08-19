"""声纹写作 — 用声纹写新内容，exemplar 作为 system prompt 参考资料注入."""
from __future__ import annotations

import json
from pathlib import Path

from .adapter import _run_async, generate
from .prompts import (
    WRITING_SYSTEM_PROMPT_TEMPLATE,
    format_exemplars,
    format_pitfalls,
)
from .schema import Fingerprint


def load_fingerprint(path: str) -> Fingerprint:
    """加载声纹 JSON 文件."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Fingerprint.model_validate(data)


def write_with_fingerprint(
    fingerprint_path: str,
    user_prompt: str,
    output_path: str | None = None,
    max_words: int = 1500,
) -> tuple[str, dict]:
    """用声纹写新内容。

    Args:
        fingerprint_path: 声纹 JSON 路径
        user_prompt: 用户的写作请求
        output_path: 输出文件路径（可选）
        max_words: 最大字数

    Returns:
        (generated_text, usage_info)
    """
    fingerprint = load_fingerprint(fingerprint_path)

    system = WRITING_SYSTEM_PROMPT_TEMPLATE.format(
        style_description=fingerprint.style_description,
        exemplar_passages_formatted=format_exemplars(
            [p.model_dump() for p in fingerprint.exemplar_passages]
        ),
        ai_pitfalls_formatted=format_pitfalls(
            [p.model_dump() for p in fingerprint.ai_pitfalls]
        ),
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]

    text, usage = _run_async(generate(messages=messages, max_tokens=max_words * 2))

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")

    return text, usage
