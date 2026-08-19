"""Opus 盲测 — V4-Pro 评审人格盲选."""
from __future__ import annotations

import json
import random
from pathlib import Path

from ..adapter import generate_sync, _extract_json_object
from ..prompts import BLIND_REVIEW_PROMPT
from ..writer import load_fingerprint, write_with_fingerprint

BLIND_TEST_TOPICS = [
    "现代都市职场失业",
    "独居青年的深夜厨房",
    "地铁上偶遇旧识",
]

WRITE_PROMPT_TEMPLATE = "写一段 1500 字的开篇。题材：{topic}\n要求：像真实小说开篇，不要太刻意展示风格。"


def run_blind_test(
    fingerprint_path: str,
    source_path: str,
    rounds: int = 3,
    output_dir: str | None = None,
) -> list[dict]:
    """跑盲测。

    Args:
        fingerprint_path: 声纹 JSON 路径
        source_path: 原文路径（用于取真段落）
        rounds: 轮数
        output_dir: 输出目录（可选）

    Returns:
        list of round results，每个包含 {round, topic, opus_choice, correct_segment, is_correct, confidence, usage}
    """
    from ..sampler import load_source, merge_small_paragraphs

    fingerprint = load_fingerprint(fingerprint_path)
    raw_text = load_source(source_path)

    # 合并小段落以获取足够长的段落
    merged_text = merge_small_paragraphs(raw_text, min_block_chars=500)
    paragraphs = [p.strip() for p in merged_text.split("\n\n") if len(p.strip()) >= 500]

    # 如果合并后仍不够，降低阈值
    if len(paragraphs) < 3:
        paragraphs = [p.strip() for p in merged_text.split("\n\n") if len(p.strip()) >= 200]

    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

    total_cost = 0.0
    results = []

    for round_idx in range(rounds):
        topic = BLIND_TEST_TOPICS[round_idx % len(BLIND_TEST_TOPICS)]

        # 取 3 段真原文，各截 500 字
        chosen = random.sample(paragraphs, min(3, len(paragraphs)))
        real_segments = [seg[:500] for seg in chosen]

        # 用 fingerprint 写一段新内容，取 500 字
        write_prompt = WRITE_PROMPT_TEMPLATE.format(topic=topic)
        gen_text, gen_usage = write_with_fingerprint(
            fingerprint_path=fingerprint_path,
            user_prompt=write_prompt,
            max_words=1500,
        )
        total_cost += gen_usage.get("cost", 0)
        ai_segment = gen_text[:500]

        # 打乱 4 段
        segments = real_segments + [ai_segment]
        labels = ["A", "B", "C", "D"]
        combined = list(zip(labels, segments))
        random.shuffle(combined)
        shuffled = dict(combined)

        # 找到 AI 生成的标签
        correct_label = [lbl for lbl, seg in combined if seg is ai_segment][0]

        # 送评审
        review_prompt = BLIND_REVIEW_PROMPT.format(
            seg_a=shuffled["A"],
            seg_b=shuffled["B"],
            seg_c=shuffled["C"],
            seg_d=shuffled["D"],
        )

        review_messages = [{"role": "user", "content": review_prompt}]
        review_text, review_usage = generate_sync(
            messages=review_messages, max_tokens=1000
        )
        total_cost += review_usage.get("cost", 0)

        # 解析评审结果
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
                    "ai_generated_segment": "PARSE_ERROR",
                    "confidence": "low",
                    "key_evidence": [review_text[:200]],
                }

        opus_choice = review_result.get("ai_generated_segment", "?")
        confidence = review_result.get("confidence", "unknown")
        is_correct = opus_choice == correct_label

        result = {
            "round": round_idx + 1,
            "topic": topic,
            "correct_segment": correct_label,
            "opus_choice": opus_choice,
            "is_correct": is_correct,
            "confidence": confidence,
            "key_evidence": review_result.get("key_evidence", []),
            "write_usage": gen_usage,
            "review_usage": review_usage,
        }
        results.append(result)

        if output_dir:
            path = Path(output_dir) / f"blind_test_round_{round_idx + 1}.json"
            path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    # 汇总
    correct_count = sum(1 for r in results if r["is_correct"])
    error_rate = (rounds - correct_count) / rounds

    summary = {
        "rounds": rounds,
        "correct_count": correct_count,
        "error_rate": error_rate,
        "passed": error_rate >= 1 / 3,
        "total_cost": total_cost,
        "details": results,
    }

    if output_dir:
        summary_path = Path(output_dir) / "blind_test_summary.json"
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return results, summary
