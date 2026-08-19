"""声纹提取 — 单 LLM 调用提取声纹."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .adapter import _run_async, generate_json
from .prompts import EXTRACTION_PROMPT
from .sampler import load_source, merge_small_paragraphs, uniform_paragraph_sample
from .schema import Fingerprint

logger = logging.getLogger(__name__)

MAX_RETRIES = 1

PASSAGE_MIN_CHARS = 500
MIN_SOURCE_CHARS = 3000
EXTRACTION_EXPECTED_OUTPUT_TOKENS = 5000
EXTRACTION_OUTPUT_TOKEN_LIMIT = 16384


class InsufficientEvidenceError(RuntimeError):
    """The model completed the paid call but honestly found no stable style."""

    def __init__(self, quality_gate: dict[str, Any], usage: dict[str, Any]):
        self.quality_gate = {
            "stable_enough": False,
            "reason": str(quality_gate.get("reason", "")).strip()
            or "这份文本里还看不出足够稳定的写法。",
            "missing_evidence": [
                str(item).strip()
                for item in quality_gate.get("missing_evidence", [])
                if str(item).strip()
            ],
        }
        self.usage = dict(usage)
        super().__init__(self.quality_gate["reason"])


def prepare_extraction_input(
    source_path: str,
    sample_size: int = 8000,
    *,
    enforce_minimum: bool = False,
) -> dict[str, Any]:
    """Load and sample once, before any adapter call.

    This shared seam lets the browser preflight price the exact formatted
    request without triggering the model.  The returned raw/merged text stays
    in process memory and is never persisted by this helper.
    """
    raw_text = load_source(source_path)
    source_chars = len(raw_text.strip())
    if enforce_minimum and source_chars < MIN_SOURCE_CHARS:
        raise ValueError(
            f"可用文本只有 {source_chars} 字，至少需要 {MIN_SOURCE_CHARS} 字才能提取稳定声纹"
        )
    merged_text = merge_small_paragraphs(raw_text, min_block_chars=500)
    sampled, method = uniform_paragraph_sample(merged_text, sample_size)
    prompt = EXTRACTION_PROMPT.format(sampled_text=sampled)
    return {
        "raw_text": raw_text,
        "merged_text": merged_text,
        "sampled_text": sampled,
        "sampling_method": method,
        "prompt": prompt,
        "total_chars": source_chars,
        "sampled_chars": len(sampled),
    }


def production_prompt_ready() -> bool:
    """True only after the signed prompt exposes the R5-3B soft gate."""
    required_markers = (
        "quality_gate",
        "stable_enough",
        "missing_evidence",
    )
    return all(marker in EXTRACTION_PROMPT for marker in required_markers)


def _extend_short_passages(passages: list[dict], source_text: str, min_chars: int = PASSAGE_MIN_CHARS) -> list[dict]:
    """对短于 min_chars 的 passage，在源文中定位并扩展到足够长度."""
    result = []
    for p in passages:
        passage = p.get("passage", "")
        why = p.get("why_representative", "")

        if len(passage) >= min_chars:
            result.append(p)
            continue

        # 在源文中定位这段文字
        # 取 passage 的前 50 个字符作为搜索片段
        search_snippet = passage[:50].strip()
        if not search_snippet:
            result.append(p)
            continue

        pos = source_text.find(search_snippet)
        if pos == -1:
            # 尝试取更短的片段
            search_snippet = passage[:30].strip()
            pos = source_text.find(search_snippet)

        if pos == -1:
            # 找不到，保持原样
            result.append(p)
            continue

        # 从定位点向前后扩展
        start = pos
        end = pos + len(passage)

        # 向前扩展到上一个段落边界（双换行）
        while start > 0 and (end - start) < min_chars:
            prev_nl = source_text.rfind("\n\n", 0, start - 1)
            if prev_nl == -1:
                start = 0
                break
            start = prev_nl + 2 if prev_nl + 2 < start else 0
            if start == 0:
                break

        # 向后扩展到下一个段落边界
        while end < len(source_text) and (end - start) < min_chars:
            next_nl = source_text.find("\n\n", end + 1)
            if next_nl == -1:
                end = len(source_text)
                break
            end = next_nl

        extended = source_text[start:end].strip()

        if len(extended) >= min_chars:
            result.append({"passage": extended, "why_representative": why})
        else:
            result.append(p)  # 无法扩展到足够长度，保持原样

    return result


def extract_fingerprint(
    source_path: str,
    output_path: str,
    sample_size: int = 8000,
) -> tuple[Fingerprint, dict]:
    """从源文本提取声纹。

    Args:
        source_path: 源文本路径（文件或目录）
        output_path: 输出 JSON 路径
        sample_size: 采样目标字数

    Returns:
        (fingerprint, usage_info)
    """
    prepared = prepare_extraction_input(source_path, sample_size)
    raw_text = prepared["raw_text"]
    merged_text = prepared["merged_text"]
    sampled = prepared["sampled_text"]
    method = prepared["sampling_method"]
    prompt = prepared["prompt"]

    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0.0}
    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        response_data, usage = _run_async(
            generate_json(prompt, max_tokens=EXTRACTION_OUTPUT_TOKEN_LIMIT)
        )

        # 累加 usage
        for k in total_usage:
            if k in usage:
                total_usage[k] += usage[k]

        quality_gate = response_data.get("quality_gate")
        if (
            isinstance(quality_gate, dict)
            and quality_gate.get("stable_enough") is False
        ):
            # This is a valid business result, not malformed JSON.  Retrying
            # would spend money to pressure the model into inventing evidence.
            raise InsufficientEvidenceError(quality_gate, total_usage)

        # 后处理：扩展短段落
        if "exemplar_passages" in response_data:
            response_data["exemplar_passages"] = _extend_short_passages(
                response_data["exemplar_passages"], merged_text, PASSAGE_MIN_CHARS
            )

        try:
            fingerprint = Fingerprint(
                schema_version=1,
                extracted_at=datetime.now(timezone.utc).isoformat(),
                source_info={
                    "source_path": source_path,
                    "total_chars": len(raw_text),
                    "sampled_chars": len(sampled),
                    "sampling_method": method,
                },
                style_description=response_data["style_description"],
                exemplar_passages=response_data["exemplar_passages"],
                ai_pitfalls=response_data["ai_pitfalls"],
            )

            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(fingerprint.model_dump(), f, ensure_ascii=False, indent=2)

            return fingerprint, total_usage

        except ValidationError as e:
            last_error = e
            logger.warning(f"提取尝试 {attempt + 1} 校验失败: {e}")
            if attempt < MAX_RETRIES:
                retry_note = (
                    "\n\n【重要修正要求】\n"
                    "上次的输出有校验问题，请务必满足以下要求：\n"
                    "- 每段 passage 必须 >= 500 字符（合并连续段落也可以）\n"
                    "- 代表段落数量 5-8 段\n"
                    "- AI 雷区数量 5-10 条\n"
                    "- 所有 why_* 字段不能为空\n"
                    "- 必须输出完整的 JSON，包含 style_description、exemplar_passages、ai_pitfalls 三个字段"
                )
                prompt = EXTRACTION_PROMPT.format(sampled_text=sampled) + retry_note

    raise RuntimeError(
        f"声纹提取 {MAX_RETRIES + 1} 次尝试后仍校验失败。最后错误:\n{last_error}"
    )
