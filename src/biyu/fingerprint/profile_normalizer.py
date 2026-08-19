"""Normalize a signed R5-3B extraction result into line-style voiceprint data."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from biyu.fingerprint.merge_policy import canonical_dimension

_STYLE_LINE = re.compile(
    r"^\s*维度[：:]\s*(?P<dimension>.+?)\s*[｜|]\s*"
    r"规则是什么[：:]\s*(?P<text>.+?)\s*[｜|]\s*"
    r"为什么[：:]\s*(?P<why>.+?)\s*$"
)


def _line_id(import_id: str, dimension: str, text: str) -> str:
    digest = hashlib.sha256(
        f"{import_id}\0{dimension}\0{text}".encode("utf-8")
    ).hexdigest()[:12]
    return f"voice-{digest}"


def _source_ref(
    import_id: str,
    source_name: str,
    source_sha256: str,
) -> dict[str, str]:
    return {
        "import_id": import_id,
        "source_name": source_name,
        "source_sha256": source_sha256,
    }


def _parse_style_description(description: str) -> list[tuple[str, str, str]]:
    parsed: list[tuple[str, str, str]] = []
    for raw_line in str(description).splitlines():
        clean = raw_line.strip()
        if not clean:
            continue
        match = _STYLE_LINE.match(clean)
        if match is None:
            raise ValueError(
                "风格说明不是可拆分的“维度｜规则是什么｜为什么”逐行格式"
            )
        dimension = match.group("dimension").strip()
        text = match.group("text").strip()
        why = match.group("why").strip()
        if not dimension or not text or not why:
            raise ValueError("风格说明的维度、规则和原因都不能为空")
        parsed.append((dimension, text, why))
    if not parsed:
        raise ValueError("风格说明没有可用规则")
    return parsed


def normalize_import_result(
    result: dict[str, Any],
    *,
    import_id: str,
    source_name: str,
    source_sha256: str,
    existing_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert one extraction result, discarding R5-3B exemplar passages.

    Author-owned rows from the same imported profile are carried forward and
    remain authoritative for their dimension on a re-extraction.
    """
    import_id = str(import_id).strip()
    source_name = str(source_name).strip()
    source_sha256 = str(source_sha256).strip().lower()
    if not import_id or not source_name or not source_sha256:
        raise ValueError("导入来源标识不完整")

    source_ref = _source_ref(import_id, source_name, source_sha256)
    author_lines: list[dict[str, Any]] = []
    if isinstance(existing_profile, dict):
        for item in existing_profile.get("lines", []):
            if isinstance(item, dict) and item.get("source") == "author":
                author_lines.append(dict(item))
    protected_dimensions = {
        canonical_dimension(str(line.get("dimension", "")))
        for line in author_lines
    }

    machine_lines: list[dict[str, Any]] = []
    for dimension, text, why in _parse_style_description(
        str(result.get("style_description", ""))
    ):
        if canonical_dimension(dimension) in protected_dimensions:
            continue
        machine_lines.append({
            "id": _line_id(import_id, dimension, text),
            "dimension": dimension,
            "text": text,
            "why": why,
            "source": "machine",
            "source_ref": dict(source_ref),
        })

    for item in result.get("ai_pitfalls", []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("pitfall", "")).strip()
        why = str(item.get("why_it_happens", "")).strip()
        dimension = "明确避坑"
        if not text or canonical_dimension(dimension) in protected_dimensions:
            continue
        line = {
            "id": _line_id(import_id, dimension, text),
            "dimension": dimension,
            "text": text,
            "source": "machine",
            "source_ref": dict(source_ref),
        }
        if why:
            line["why"] = why
        machine_lines.append(line)

    created_at = (
        existing_profile.get("created_at")
        if isinstance(existing_profile, dict)
        else None
    ) or datetime.now(timezone.utc).isoformat()
    profile: dict[str, Any] = {
        "schema_version": 1,
        "id": import_id,
        "name": source_name,
        "kind": "imported",
        "created_at": created_at,
        "source_ref": source_ref,
        "lines": author_lines + machine_lines,
    }
    source_info = result.get("source_info")
    if isinstance(source_info, dict):
        # Never persist a browser upload's temporary filesystem path.
        profile["source_info"] = {
            key: value for key, value in source_info.items()
            if key != "source_path"
        }
    return profile
