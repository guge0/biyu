"""Explicit R5-3B external-text voiceprint import API.

The uploaded source exists only in a short-lived temporary directory.  The
book stores its digest, display name, counts, timestamp, and normalized lines;
it never stores the uploaded prose or exemplar passages.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from biyu.fingerprint.adapter import _estimate_cost, _get_adapter_config
from biyu.fingerprint.extractor import (
    EXTRACTION_EXPECTED_OUTPUT_TOKENS,
    EXTRACTION_OUTPUT_TOKEN_LIMIT,
    InsufficientEvidenceError,
    extract_fingerprint,
    prepare_extraction_input,
    production_prompt_ready,
)
from biyu.ui.cost_log import write_cost_log
from biyu.ui.workbench import _book_dir

router = APIRouter(prefix="/api/voiceprint", tags=["voiceprint-import"])


class ImportTextBody(BaseModel):
    source_name: str = Field(min_length=1, max_length=240)
    text: str = Field(min_length=1)


def _identity(text: str) -> tuple[str, str]:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digest, f"import:{digest}"


def _safe_source_name(value: str) -> str:
    name = Path(value.strip()).name.strip()
    return name or "导入文本.txt"


def _prepare_text(text: str, sample_size: int = 8000) -> dict[str, Any]:
    """Use the production sampler without retaining the upload."""
    with tempfile.TemporaryDirectory(prefix="biyu-fingerprint-") as temp_dir:
        source = Path(temp_dir) / "source.txt"
        source.write_text(text, encoding="utf-8")
        return prepare_extraction_input(
            str(source),
            sample_size,
            enforce_minimum=True,
        )


def _estimate(prepared: dict[str, Any]) -> dict[str, Any]:
    cfg = _get_adapter_config()
    input_units = len(str(prepared["prompt"]))
    normal = _estimate_cost(
        cfg["cost_per_1k_input"],
        cfg["cost_per_1k_output"],
        input_units,
        EXTRACTION_EXPECTED_OUTPUT_TOKENS,
    )
    single_upper_bound = _estimate_cost(
        cfg["cost_per_1k_input"],
        cfg["cost_per_1k_output"],
        input_units,
        EXTRACTION_OUTPUT_TOKEN_LIMIT,
    )
    return {
        "total_chars": prepared["total_chars"],
        "sampled_chars": prepared["sampled_chars"],
        "sampling_method": prepared["sampling_method"],
        "estimated_input_units": input_units,
        "estimated_output_tokens": EXTRACTION_EXPECTED_OUTPUT_TOKENS,
        "normal_calls": 1,
        "max_calls": 2,
        "estimated_cost": round(normal, 6),
        "max_estimated_cost": round(single_upper_bound * 2, 6),
        "prompt_ready": production_prompt_ready(),
    }


def _write_profile(book_dir: Path, digest: str, profile: dict[str, Any]) -> Path:
    target = book_dir / "声纹" / "导入作品" / f"{digest}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, staging_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(profile, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging_name, target)
    except BaseException:
        try:
            os.unlink(staging_name)
        except FileNotFoundError:
            pass
        raise
    return target


def _load_existing(book_dir: Path, digest: str) -> dict[str, Any] | None:
    path = book_dir / "声纹" / "导入作品" / f"{digest}.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=409,
            detail="已有的导入声纹无法读取；当前没有覆盖任何内容",
        ) from exc
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=409,
            detail="已有的导入声纹格式不对；当前没有覆盖任何内容",
        )
    return value


def _select_new_import(book_dir: Path, import_id: str) -> None:
    """An explicitly created profile becomes the book's sole active profile."""
    from biyu.fingerprint.profile_state import save_profile_state

    save_profile_state(book_dir, import_id)


def _record_cost(book: str, book_dir: Path, digest: str, cost: float) -> None:
    write_cost_log(
        task="voiceprint_import",
        book=book,
        session=digest[:12],
        cost=cost,
        model="v4_pro",
        data_root=book_dir.parent,
    )


@router.post("/books/{book}/imports/preflight")
def import_preflight(book: str, body: ImportTextBody) -> dict[str, Any]:
    # Resolve first so a typo cannot be mistaken for a valid, priced import.
    _book_dir(book)
    try:
        prepared = _prepare_text(body.text)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    digest, _ = _identity(body.text)
    return {
        "source_name": _safe_source_name(body.source_name),
        "source_sha256": digest,
        **_estimate(prepared),
    }


@router.post("/books/{book}/imports/extract")
def import_extract(book: str, body: ImportTextBody) -> dict[str, Any]:
    book_dir = _book_dir(book)
    source_name = _safe_source_name(body.source_name)
    digest, import_id = _identity(body.text)

    # Thin input has priority over the signature gate so the author gets the
    # useful reason and, critically, no adapter is touched.
    try:
        prepared = _prepare_text(body.text)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not production_prompt_ready():
        raise HTTPException(
            status_code=409,
            detail="外部文本提取提示词还在等老板签字；现在不会调用模型，也不会产生费用",
        )

    existing = _load_existing(book_dir, digest)
    with tempfile.TemporaryDirectory(prefix="biyu-fingerprint-") as temp_dir:
        source = Path(temp_dir) / "source.txt"
        output = Path(temp_dir) / "result.json"
        source.write_text(body.text, encoding="utf-8")
        try:
            fingerprint, usage = extract_fingerprint(
                str(source),
                str(output),
            )
        except InsufficientEvidenceError as exc:
            actual_cost = round(float(exc.usage.get("cost", 0.0)), 6)
            _record_cost(book, book_dir, digest, actual_cost)
            from biyu.ui.voiceprint import workspace_snapshot

            return {
                "status": "insufficient",
                "source_name": source_name,
                "source_sha256": digest,
                "total_chars": prepared["total_chars"],
                "sampled_chars": prepared["sampled_chars"],
                "quality_gate": exc.quality_gate,
                "usage": exc.usage,
                "actual_cost": actual_cost,
                "workspace": workspace_snapshot(book, book_dir),
            }
        except (KeyError, RuntimeError, ValueError) as exc:
            raise HTTPException(
                status_code=502,
                detail=f"提取结果无法使用；没有保存声纹：{exc}",
            ) from exc

    from biyu.fingerprint.profile_normalizer import normalize_import_result

    profile = normalize_import_result(
        fingerprint.model_dump(),
        import_id=import_id,
        source_name=source_name,
        source_sha256=digest,
        existing_profile=existing,
    )
    # Keep only non-source metadata needed for traceability and author review.
    profile["source_chars"] = prepared["total_chars"]
    profile["sampled_chars"] = prepared["sampled_chars"]
    profile["extracted_at"] = datetime.now(timezone.utc).isoformat()
    _write_profile(book_dir, digest, profile)
    _select_new_import(book_dir, import_id)

    actual_cost = round(float(usage.get("cost", 0.0)), 6)
    _record_cost(book, book_dir, digest, actual_cost)
    from biyu.ui.voiceprint import workspace_snapshot

    return {
        "status": "ready",
        "import_id": import_id,
        "source_name": source_name,
        "source_sha256": digest,
        "profile": profile,
        "usage": usage,
        "actual_cost": actual_cost,
        "workspace": workspace_snapshot(book, book_dir),
    }
