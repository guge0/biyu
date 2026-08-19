"""多题材鲁棒性测试 — 验证声纹是"风格"不是"内容记忆"."""
from __future__ import annotations

import json
from pathlib import Path

from ..adapter import generate_sync, _extract_json_object
from ..prompts import MULTI_GENRE_REVIEW_PROMPT
from ..writer import write_with_fingerprint

GENRE_PROMPTS = {
    "modern": "写一段 1500 字的现代都市小说开篇。题材：一个在大城市打拼的年轻人，面临职场选择和感情抉择。",
    "xuanhuan": "写一段 1500 字的玄幻修仙小说开篇。题材：一个废材少年意外获得远古传承，踏上修仙之路。注意：不要出现诸天无限元素。",
    "scifi": "写一段 1500 字的科幻短篇开篇。题材：人类在火星上建立了第一个永久殖民地，主人公是殖民地的维护工程师。",
}


def run_multi_genre_test(
    fingerprint_path: str,
    output_dir: str | None = None,
) -> dict:
    """跑多题材鲁棒性测试。

    Args:
        fingerprint_path: 声纹 JSON 路径
        output_dir: 输出目录

    Returns:
        测试结果 dict
    """
    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

    total_cost = 0.0
    outputs = {}

    # 写 3 个题材
    for genre_key, prompt in GENRE_PROMPTS.items():
        text, usage = write_with_fingerprint(
            fingerprint_path=fingerprint_path,
            user_prompt=prompt,
            max_words=1500,
        )
        outputs[genre_key] = text
        total_cost += usage.get("cost", 0)

        if output_dir:
            path = Path(output_dir) / f"output_{genre_key}.txt"
            path.write_text(text, encoding="utf-8")

    # 评审
    review_prompt = MULTI_GENRE_REVIEW_PROMPT.format(
        output_1=outputs["modern"],
        output_2=outputs["xuanhuan"],
        output_3=outputs["scifi"],
    )

    review_messages = [{"role": "user", "content": review_prompt}]
    review_text, review_usage = generate_sync(
        messages=review_messages, max_tokens=2000
    )
    total_cost += review_usage.get("cost", 0)

    try:
        clean = review_text.strip()
        if clean.startswith("```"):
            first_nl = clean.index("\n") + 1
            clean = clean[first_nl:]
            if clean.endswith("```"):
                clean = clean[:-3].strip()
        review_result = json.loads(clean)
    except json.JSONDecodeError:
        try:
            review_result = _extract_json_object(review_text)
        except json.JSONDecodeError:
            review_result = {
                "consistency_score": 0,
                "what_remains_same": [],
                "what_differs": ["PARSE_ERROR"],
                "verdict": "inconsistent",
                "raw_review": review_text[:500],
        }

    result = {
        "consistency_score": review_result.get("consistency_score", 0),
        "verdict": review_result.get("verdict", "unknown"),
        "what_remains_same": review_result.get("what_remains_same", []),
        "what_differs": review_result.get("what_differs", []),
        "passed": (
            review_result.get("consistency_score", 0) >= 3
            and review_result.get("verdict") != "inconsistent"
        ),
        "total_cost": total_cost,
        "char_counts": {k: len(v) for k, v in outputs.items()},
    }

    if output_dir:
        result_path = Path(output_dir) / "multi_genre_result.json"
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return result
