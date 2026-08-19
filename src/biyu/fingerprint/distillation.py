"""Deterministic candidate grouping and explicit human review state."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from biyu.fingerprint.ledger import read_feedback_entries
from biyu.fingerprint.library import replace_machine_lines

DISTILLATION_OUTPUT_TOKEN_LIMIT = 1024


def build_candidate_pool(entries: list[dict]) -> dict[str, list[dict]]:
    sentence_entries = [item for item in entries if item.get("scope") == "sentence"]
    return {
        "problems": [
            item for item in sentence_entries
            if item.get("action") in {"revise", "note_problem"}
        ],
        "goods": [item for item in sentence_entries if item.get("action") == "good"],
    }


def _group_id(kind: str, key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"{kind}-{digest}"


def _state_path(book_dir: Path) -> Path:
    return Path(book_dir) / "声纹" / "复核状态.json"


def _load_state(book_dir: Path) -> dict:
    path = _state_path(book_dir)
    if not path.exists():
        return {"version": 2, "groups": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    groups = value.get("groups", {})
    if not isinstance(groups, dict):
        groups = {}
    return {
        "version": 2,
        "groups": groups,
        "legacy_decisions": {
            str(key): str(decision)
            for key, decision in value.get("decisions", {}).items()
        },
        "last_distilled_at": value.get("last_distilled_at"),
        "last_feedback_ids": [
            str(item_id) for item_id in value.get("last_feedback_ids", [])
        ],
    }


def _write_state(book_dir: Path, state: dict) -> None:
    path = _state_path(book_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    persisted = {
        "version": 2,
        "groups": state.get("groups", {}),
        "last_distilled_at": state.get("last_distilled_at"),
        "last_feedback_ids": state.get("last_feedback_ids", []),
    }
    if state.get("legacy_decisions"):
        persisted["decisions"] = state["legacy_decisions"]
    path.write_text(
        json.dumps(persisted, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _legacy_items(book_dir: Path) -> list[dict]:
    path = Path(book_dir) / "样本库" / "负例候选.md"
    if not path.exists():
        return []
    result = []
    for index, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = raw.strip()
        if not text.startswith("- "):
            continue
        value = text[2:].strip()
        if value:
            result.append({"id": f"legacy-{index}", "text": value, "action": "legacy"})
    return result


def _cluster_key(item: dict) -> str:
    """Use the author's own diagnosis as the stable, non-judgmental grouping key."""
    comment = re.sub(r"\s+", "", str(item.get("author_comment", ""))).lower()
    if comment:
        return f"comment:{comment}"
    return f"item:{item.get('id', '')}"


def review_snapshot(book_dir: Path) -> dict:
    entries = read_feedback_entries(book_dir)
    pool = build_candidate_pool(entries)
    state = _load_state(book_dir)
    records = state["groups"]
    legacy_decisions = state.get("legacy_decisions", {})
    state_migrated = False
    grouped: dict[str, list[dict]] = {}
    for item in pool["problems"]:
        grouped.setdefault(_cluster_key(item), []).append(item)
    all_groups = []
    for cluster_key, items in grouped.items():
        gid = _group_id("problem", cluster_key)
        member_ids = [str(item["id"]) for item in items]
        record = records.get(gid, {})
        if not record:
            old_gid = "problem-" + hashlib.sha256(
                "\0".join(sorted(member_ids)).encode("utf-8")
            ).hexdigest()[:12]
            old_decision = legacy_decisions.get(old_gid, "")
            if old_decision:
                record = {
                    "decision": old_decision,
                    "member_ids": member_ids,
                    "decided_at": None,
                }
                records[gid] = record
                legacy_decisions.pop(old_gid, None)
                state_migrated = True
        previous_ids = {str(item_id) for item_id in record.get("member_ids", [])}
        new_ids = [item_id for item_id in member_ids if item_id not in previous_ids]
        previous_decision = str(record.get("decision", ""))
        needs_reconfirmation = bool(previous_decision and new_ids)
        all_groups.append({
            "id": gid,
            "kind": "problem",
            "count": len(items),
            "items": items,
            "decision": "" if needs_reconfirmation else previous_decision,
            "previous_decision": previous_decision,
            "new_count": len(new_ids) if needs_reconfirmation else 0,
            "needs_reconfirmation": needs_reconfirmation,
            "_confirmed_ids": (
                sorted(previous_ids & set(member_ids))
                if needs_reconfirmation and previous_decision == "common"
                else member_ids if previous_decision == "common" else []
            ),
        })
    legacy = _legacy_items(book_dir)
    if legacy:
        gid = _group_id("legacy", "以前记下的")
        member_ids = [str(item["id"]) for item in legacy]
        record = records.get(gid, {})
        if not record:
            old_gid = "legacy-" + hashlib.sha256(
                "\0".join(sorted(member_ids)).encode("utf-8")
            ).hexdigest()[:12]
            old_decision = legacy_decisions.get(old_gid, "")
            if old_decision:
                record = {
                    "decision": old_decision,
                    "member_ids": member_ids,
                    "decided_at": None,
                }
                records[gid] = record
                legacy_decisions.pop(old_gid, None)
                state_migrated = True
        previous_ids = {str(item_id) for item_id in record.get("member_ids", [])}
        new_ids = [item_id for item_id in member_ids if item_id not in previous_ids]
        previous_decision = str(record.get("decision", ""))
        needs_reconfirmation = bool(previous_decision and new_ids)
        all_groups.append({
            "id": gid,
            "kind": "legacy",
            "count": len(legacy),
            "items": legacy,
            "decision": "" if needs_reconfirmation else previous_decision,
            "previous_decision": previous_decision,
            "new_count": len(new_ids) if needs_reconfirmation else 0,
            "needs_reconfirmation": needs_reconfirmation,
            "_confirmed_ids": (
                sorted(previous_ids & set(member_ids))
                if needs_reconfirmation and previous_decision == "common"
                else member_ids if previous_decision == "common" else []
            ),
        })
    groups = [
        group for group in all_groups
        if not group["decision"] or group["needs_reconfirmation"]
    ]
    confirmed = [
        item_id
        for group in all_groups
        for item_id in group.pop("_confirmed_ids")
    ]
    feedback_ids = [str(item["id"]) for item in entries if item.get("id")]
    last_feedback_ids = set(state.get("last_feedback_ids", []))
    if state_migrated:
        _write_state(book_dir, state)
    return {
        "groups": groups,
        "all_groups": all_groups,
        "goods": pool["goods"],
        "confirmed_negative_ids": confirmed,
        "last_distilled_at": state.get("last_distilled_at"),
        "new_feedback_count": len([
            item_id for item_id in feedback_ids if item_id not in last_feedback_ids
        ]),
        "all_feedback_ids": feedback_ids,
    }


def save_group_decision(book_dir: Path, group_id: str, decision: str) -> dict:
    if decision not in {"common", "specific"}:
        raise ValueError("复核结论必须是 common 或 specific")
    snapshot = review_snapshot(book_dir)
    group = next(
        (item for item in snapshot["all_groups"] if item["id"] == group_id),
        None,
    )
    if group is None:
        raise ValueError("待复核组不存在")
    state = _load_state(book_dir)
    state["groups"][group_id] = {
        "decision": decision,
        "member_ids": [str(item["id"]) for item in group["items"]],
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_state(book_dir, state)
    return {"group_id": group_id, "decision": decision}


def record_distillation(book_dir: Path, snapshot: dict | None = None) -> dict:
    snapshot = snapshot or review_snapshot(book_dir)
    state = _load_state(book_dir)
    state["last_distilled_at"] = datetime.now(timezone.utc).isoformat()
    state["last_feedback_ids"] = sorted(set(snapshot["all_feedback_ids"]))
    _write_state(book_dir, state)
    return {
        "last_distilled_at": state["last_distilled_at"],
        "last_feedback_ids": state["last_feedback_ids"],
    }


def _parse_json_response(text: str) -> dict:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    try:
        result = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("蒸馏模型没有返回有效 JSON") from exc
    if not isinstance(result, dict) or not isinstance(result.get("lines"), list):
        raise ValueError("蒸馏结果缺少 lines 数组")
    return result


def build_distillation_payload(snapshot: dict) -> dict:
    confirmed_ids = set(snapshot["confirmed_negative_ids"])
    confirmed_groups = [
        {
            **group,
            "items": [
                item for item in group["items"]
                if str(item["id"]) in confirmed_ids
            ],
        }
        for group in snapshot["all_groups"]
        if any(str(item["id"]) in confirmed_ids for item in group["items"])
    ]
    return {
        "confirmed_problem_groups": confirmed_groups,
        "positive_examples": snapshot["goods"],
        "required_dimensions": [
            "句子长短与节奏偏好",
            "该用与不该用的句式",
            "标点习惯",
            "比喻/形容的密度",
            "明确禁用的表达",
        ],
        "output_rule": "每条必须同时说明偏好是什么，以及为什么这样处理。",
    }


async def distill_voiceprint(book_dir: Path, adapter, prompt_text: str) -> dict:
    """Run the only model-backed action in this module, after explicit UI click."""
    snapshot = review_snapshot(book_dir)
    payload = build_distillation_payload(snapshot)
    response = await adapter.generate(
        messages=[
            {"role": "system", "content": prompt_text},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0.2,
        max_tokens=DISTILLATION_OUTPUT_TOKEN_LIMIT,
    )
    parsed = _parse_json_response(response.text)
    profile = replace_machine_lines(book_dir, parsed["lines"])
    record_distillation(book_dir, snapshot)
    return {
        "profile": profile,
        "cost": float(getattr(response, "cost", 0.0)),
        "usage": getattr(response, "usage", None),
    }
