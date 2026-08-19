"""Voiceprint review, editing, selection, and explicit distillation API."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from biyu.fingerprint.distillation import (
    DISTILLATION_OUTPUT_TOKEN_LIMIT,
    build_candidate_pool,
    build_distillation_payload,
    distill_voiceprint,
    review_snapshot,
    save_group_decision,
)
from biyu.fingerprint.ledger import read_feedback_entries
from biyu.fingerprint.library import (
    create_manual_profile,
    edit_voice_line,
    load_catalog_with_status,
    load_merged_voiceprint,
    load_self_profile,
    mechanically_combine_profiles,
    save_selection,
)
from biyu.ui.workbench import _book_dir
from biyu.config import get_registry
from biyu.ui.cost_log import write_cost_log

router = APIRouter(prefix="/api/voiceprint", tags=["voiceprint"])


class DecisionBody(BaseModel):
    decision: str


class EditLineBody(BaseModel):
    text: str
    why: str | None = None
    profile_id: str | None = None


class SelectionBody(BaseModel):
    active: str | None = None


class ManualProfileBody(BaseModel):
    name: str = "手写声纹"
    lines: list[dict]


class CombineProfilesBody(BaseModel):
    name: str = "合并声纹"
    source_ids: list[str]


def _source_breakdown(book_dir: Path) -> dict:
    entries = read_feedback_entries(book_dir)
    sentence_entries = [item for item in entries if item.get("scope") == "sentence"]
    chapters = sorted({
        int(item["chapter"])
        for item in sentence_entries
        if str(item.get("chapter", "")).isdigit()
    })
    if not chapters:
        chapter_range = "暂无句级反馈"
    elif len(chapters) == 1:
        chapter_range = f"第 {chapters[0]} 章"
    else:
        chapter_range = f"第 {chapters[0]}–{chapters[-1]} 章"
    return {
        "revise": sum(item.get("action") == "revise" for item in sentence_entries),
        "note_problem": sum(
            item.get("action") == "note_problem" for item in sentence_entries
        ),
        "good": sum(item.get("action") == "good" for item in sentence_entries),
        "chapter_excluded": sum(item.get("scope") == "chapter" for item in entries),
        "chapter_range": chapter_range,
    }


def _estimate(book_dir: Path) -> dict:
    pool = build_candidate_pool(read_feedback_entries(book_dir))
    count = len(pool["problems"]) + len(pool["goods"])
    calls = 0 if count == 0 else 1
    estimated_cost = 0.0
    estimated_input_units = 0
    if calls:
        prompt_path = (
            Path(__file__).resolve().parents[3]
            / "prompts"
            / "fingerprint"
            / "distillation.md"
        )
        prompt_text = prompt_path.read_text(encoding="utf-8")
        payload_text = json.dumps(
            build_distillation_payload(review_snapshot(book_dir)),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        # Chinese character count is a conservative engineering proxy for
        # input tokens; the output allowance equals the real request limit.
        estimated_input_units = len(prompt_text) + len(payload_text)
        adapter = get_registry().get_adapter_for_stage("writer")
        estimated_cost = adapter.estimate_cost(
            estimated_input_units,
            DISTILLATION_OUTPUT_TOKEN_LIMIT,
        )
    return {
        "feedback_count": count,
        "estimated_calls": calls,
        "estimated_cost_yuan": round(estimated_cost, 6),
        "estimated_input_units": estimated_input_units,
        "estimated_output_tokens": DISTILLATION_OUTPUT_TOKEN_LIMIT if calls else 0,
        "estimate_kind": "upper_bound",
    }


def workspace_snapshot(book: str, book_dir: Path) -> dict:
    """Build the read-only workspace for an already-resolved book directory."""
    merged = load_merged_voiceprint(book_dir)
    review = review_snapshot(book_dir)
    catalog = load_catalog_with_status(book_dir)
    from biyu.fingerprint.profile_state import load_profile_state
    profile_state = load_profile_state(book_dir)
    return {
        "book": book,
        "estimate": _estimate(book_dir),
        "sources": _source_breakdown(book_dir),
        "review": review,
        "profile": load_self_profile(book_dir),
        "catalog": catalog,
        "imports": [
            profile for profile in catalog
            if profile.get("kind") == "imported"
        ],
        "profile_state": profile_state,
        "active": merged["active_profile_id"],
        "active_profile": merged["active_profile"],
        "merged": merged,
    }


@router.get("/books/{book}")
def get_workspace(book: str) -> dict:
    return workspace_snapshot(book, _book_dir(book))


@router.post("/books/{book}/review/{group_id}")
def decide_group(book: str, group_id: str, body: DecisionBody) -> dict:
    book_dir = _book_dir(book)
    snapshot = review_snapshot(book_dir)
    if group_id not in {group["id"] for group in snapshot["groups"]}:
        raise HTTPException(status_code=404, detail="待复核组不存在或已经判过")
    try:
        result = save_group_decision(book_dir, group_id, body.decision)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result["review"] = review_snapshot(book_dir)
    return result


@router.put("/books/{book}/lines/{line_id}")
def update_line(book: str, line_id: str, body: EditLineBody) -> dict:
    try:
        line = edit_voice_line(_book_dir(book), line_id, body.text, body.why, body.profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"line": line}


@router.put("/books/{book}/selection")
def update_selection(book: str, body: SelectionBody) -> dict:
    book_dir = _book_dir(book)
    catalog_ids = {profile["id"] for profile in load_catalog_with_status(book_dir)}
    active = body.active
    if active is not None and active not in catalog_ids:
        raise HTTPException(status_code=422, detail=f"声纹不存在: {active}")
    save_selection(book_dir, active)
    return load_merged_voiceprint(book_dir)


@router.post("/books/{book}/profiles/manual")
def create_manual(book: str, body: ManualProfileBody) -> dict:
    book_dir = _book_dir(book)
    try:
        profile = create_manual_profile(book_dir, body.name, body.lines)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"profile": profile, "workspace": workspace_snapshot(book, book_dir)}


@router.post("/books/{book}/profiles/combine")
def combine_profiles(book: str, body: CombineProfilesBody) -> dict:
    book_dir = _book_dir(book)
    try:
        profile = mechanically_combine_profiles(book_dir, body.source_ids, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"profile": profile, "workspace": workspace_snapshot(book, book_dir)}


@router.post("/books/{book}/distill")
async def start_distillation(book: str) -> dict:
    # The production prompt is deliberately absent until the boss signs it.
    prompt_path = Path(__file__).resolve().parents[3] / "prompts" / "fingerprint" / "distillation.md"
    if not prompt_path.exists():
        raise HTTPException(status_code=409, detail="蒸馏提示词尚未签字，当前不会调用模型")
    book_dir = _book_dir(book)
    adapter = get_registry().get_adapter_for_stage("writer")
    try:
        result = await distill_voiceprint(
            book_dir,
            adapter,
            prompt_path.read_text(encoding="utf-8"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    write_cost_log(
        task="voiceprint_distillation",
        book=book,
        session="explicit",
        cost=result["cost"],
        data_root=book_dir.parent,
    )
    save_selection(book_dir, "book:self")
    result["workspace"] = get_workspace(book)
    return result
