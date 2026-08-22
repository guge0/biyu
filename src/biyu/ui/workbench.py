"""R3-1 workbench file adapters; all displayed state is re-scanned from disk."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from biyu.config import (
    BookConfig,
    find_book_dir,
    get_data_root,
    get_data_root_2,
    get_project_root,
    get_registry,
    load_characters_yaml,
)
from biyu.cli.talk_cmd import _bookroom_bat, open_talk
from biyu.ui.cli_executor import execute, running_action
from biyu.ui.sse import sse_generator
from biyu.ui.workbench_state import (
    STEP_STAGE,
    asset_state,
    persisted_run_state,
    read_workbench_step,
    write_workbench_step,
)
from biyu.ui.workbench_versions import (
    candidate_plan_is_stale,
    current_outline_version,
    current_plan_version,
    discard_current_candidate,
    list_candidate_versions,
    list_outline_versions,
    list_plan_versions,
    list_trash,
    mark_current_candidate_archived,
    purge_trash,
    restore_trash,
    save_outline_version,
    save_plan_version,
    sync_outline_version,
    select_candidate_version,
    select_outline_version,
    select_plan_version,
)
from biyu.ui.diagnosis import diagnosis_is_fresh, read_diagnosis, revision_round_count
from biyu.feedback_ledger import append_feedback
from biyu.ui.author_notice_state import (
    acknowledge_replica_warning,
    load_author_notice_state,
)
from biyu.setup_asset_versions import (
    acknowledge_setup_restore_notice,
    list_setup_asset_versions,
    load_setup_restore_notice,
    restore_setup_asset_version,
)
from biyu.importer.workbench import (
    ImportConflict,
    import_manuscripts,
    items_from_explicit_text,
    preview_import,
    preview_memory,
)

router = APIRouter(prefix="/api/workbench", tags=["workbench"])
OUTLINE_TEMPLATE = get_project_root() / "prompts" / "assets" / "章节细纲模板.md"
_WEB_ARCHITECT_RUNS: dict[tuple[str, int], dict[str, Any]] = {}


@dataclass(frozen=True)
class WebArchitectResult:
    text: str
    cost: float
    status: str


class _CostTrackingAdapter:
    """Delegate an adapter while retaining every billed response in an E-1 ladder."""

    def __init__(self, adapter, costs: list[float]):
        self._adapter = adapter
        self._costs = costs
        self.max_tokens = adapter.max_tokens

    async def generate(self, messages, **kwargs):
        response = await self._adapter.generate(messages, **kwargs)
        self._costs.append(response.cost)
        return response

    @staticmethod
    def detect_failure(response) -> str | None:
        if not response.text or not response.text.strip():
            return "empty"
        if response.finish_reason == "length":
            return "truncated"
        return None


_PLANNING_CHARACTER_FIELDS = {"人物"}
_PLANNING_WORLDBOOK_FIELDS = {"设定", "世界观", "道具", "地点"}


def _structured_planning_items(text: str, fields: set[str]) -> tuple[bool, list[str]]:
    """Read only explicit planning fields; narrative prose is deliberately ignored."""
    found = False
    items: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("- ").strip()
        match = re.match(r"(?:\*\*)?([^*：:]+?)(?:\*\*)?\s*[：:]\s*(.+)$", line)
        if not match or match.group(1).strip() not in fields:
            continue
        found = True
        for item in re.split(r"[、，,；;]", match.group(2)):
            value = item.strip()
            if value and value not in items:
                items.append(value)
    return found, items


def _planning_asset_notice(book_dir: Path, planning_text: str) -> dict[str, Any]:
    from biyu.injection_tools import query_worldbook
    from biyu.prompts.chapter_writer import resolve_present_characters

    has_characters, character_names = _structured_planning_items(
        planning_text, _PLANNING_CHARACTER_FIELDS,
    )
    has_worldbook, worldbook_names = _structured_planning_items(
        planning_text, _PLANNING_WORLDBOOK_FIELDS,
    )
    missing_characters = (
        resolve_present_characters(character_names, load_characters_yaml(book_dir)).unmatched_names
        if has_characters else []
    )
    missing_worldbook = (
        [name for name in worldbook_names if not query_worldbook(book_dir, name).hit]
        if has_worldbook else []
    )
    messages: list[str] = []
    if missing_characters:
        messages.append(
            f"这一章点到 {len(missing_characters)} 个名字没有人物卡："
            + "、".join(missing_characters)
            + "。写手查不到他们的设定，可以去设定集补，也可以就这么写。"
        )
    if missing_worldbook:
        messages.append(
            f"这一章点到 {len(missing_worldbook)} 个设定在世界观里查不到："
            + "、".join(missing_worldbook)
            + "。可以去设定集补，也可以就这么写。"
        )
    unchecked: list[str] = []
    if not has_characters:
        unchecked.append("人物")
    if not has_worldbook:
        unchecked.append("设定")
    if unchecked:
        messages.append(f"方案没有结构化{'/'.join(unchecked)}清单，本次未核，不从正文猜名字。")
    return {
        "character_names": missing_characters,
        "worldbook_names": missing_worldbook,
        "character_check": "checked" if has_characters else "unchecked",
        "worldbook_check": "checked" if has_worldbook else "unchecked",
        "message": " ".join(messages),
        "blocking": False,
    }


def _web_architect_enabled() -> bool:
    return get_registry().get_feature("web_architect")


def _architect_estimate(book_dir: Path) -> float:
    """Use this book's successful Architect history; fall back to the N-1 mean."""
    import csv

    path = book_dir / "logs" / "cost_log.csv"
    costs: list[float] = []
    if path.exists():
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                costs = [
                    float(row["cost_cny"])
                    for row in csv.DictReader(handle)
                    if row.get("stage") == "architect" and row.get("status", "ok") == "ok"
                ]
        except (OSError, ValueError, KeyError):
            costs = []
    return round(sum(costs) / len(costs), 4) if costs else 0.1132


async def _call_web_architect(book_dir: Path, chapter: int) -> WebArchitectResult:
    """Run only the existing pipeline Architect contract; never enter Writer."""
    from biyu.llm.base import LLMAdapter
    from biyu.pipeline import (
        _capture_generation_setup_versions,
        _catalog_without_lines,
        _load_prev_chapter_tail,
        _log_cost,
        _q1_worldbook_prompt,
        _read_north_star,
        _run_q1_tool_loop,
    )
    from biyu.prompts.v3_opening import build_planning_prompt
    from biyu.truth_files import read_all_truth_files
    from biyu.worldbook import build_worldbook_prompt, load_worldbook

    book = BookConfig(book_dir)
    outline_path = book.outline_path(chapter)
    if not outline_path.exists():
        raise FileNotFoundError(f"Outline not found: {outline_path}")
    outline = outline_path.read_text(encoding="utf-8")
    characters = load_characters_yaml(book_dir)
    truth_files_block = "".join(
        f"=== {name} ===\n{content}\n\n"
        for name, content in read_all_truth_files(book_dir).items()
        if content.strip()
    )
    worldbook_prompt = build_worldbook_prompt(load_worldbook(book_dir))
    injection_v2 = get_registry().get_feature("injection_v2") is True
    if injection_v2:
        _capture_generation_setup_versions(book_dir)
    north_star, _source = _read_north_star(book_dir)
    if north_star.strip() and not injection_v2:
        worldbook_prompt = "\n\n".join(
            part for part in (worldbook_prompt, north_star) if part.strip()
        )
    character_catalog = ""
    worldbook_catalog = ""
    prev_tail = _load_prev_chapter_tail(book_dir, chapter)
    from biyu.pipeline import _parse_present_characters
    from biyu.prompts.chapter_writer import resolve_present_characters

    present_characters = resolve_present_characters(
        _parse_present_characters(outline, book_dir), characters,
    ).matched_names
    previous_present_characters: list[str] = []
    if chapter > 1:
        previous_outline = book.outline_path(chapter - 1)
        if previous_outline.exists():
            previous_present_characters = resolve_present_characters(
                _parse_present_characters(
                    previous_outline.read_text(encoding="utf-8"),
                    book_dir,
                    allow_truth_fallback=False,
                ),
                characters,
            ).matched_names
    if injection_v2:
        from biyu.injection_tools import build_character_catalog, build_worldbook_catalog

        character_catalog = build_character_catalog(book_dir)
        worldbook_catalog = _catalog_without_lines(
            build_worldbook_catalog(book_dir),
            {"创作锚点", "不可变硬设定", "绝对禁止", "力量·修炼体系"},
        )
        worldbook_prompt = _q1_worldbook_prompt(load_worldbook(book_dir))
    prompt = build_planning_prompt(
        outline=outline,
        characters=[] if injection_v2 else characters,
        truth_files_block=truth_files_block,
        worldbook_prompt=worldbook_prompt,
        chapter_num=chapter,
        prev_tail=prev_tail,
        present_characters=present_characters,
        previous_present_characters=previous_present_characters,
        character_catalog=character_catalog,
        worldbook_catalog=worldbook_catalog,
        injection_v2=injection_v2,
    )
    registry = get_registry()
    primary = registry.get_adapter_for_stage("planner")
    fallback = registry.get_adapter("v3")
    billed: list[float] = []
    q1_cost = 0.0
    q1_cost_logged = False
    started = time.time()
    status = "ok"
    try:
        if injection_v2:
            response = await _run_q1_tool_loop(
                adapter=primary,
                fallback_adapter=fallback,
                messages=[{"role": "user", "content": prompt}],
                book_dir=book_dir,
                chapter_num=chapter,
                role="architect",
                guarded=True,
                generate_kwargs={},
            )
            q1_cost = response.cost
            status = "degraded" if response.degraded else "ok"
            return WebArchitectResult(response.text, response.cost, status)
        response = await LLMAdapter.generate_guarded(
            _CostTrackingAdapter(primary, billed),
            [{"role": "user", "content": prompt}],
            fallback_adapter=_CostTrackingAdapter(fallback, billed),
        )
        status = "degraded" if response.degraded else "ok"
        return WebArchitectResult(response.text, sum(billed), status)
    except Exception as exc:
        status = str(getattr(exc, "failure_type", "error"))
        q1_cost = float(getattr(exc, "q1_cost", q1_cost) or 0.0)
        q1_cost_logged = bool(getattr(exc, "q1_cost_logged", False))
        raise
    finally:
        if not q1_cost_logged:
            _log_cost(
                book, chapter, "architect", q1_cost or sum(billed),
                time.time() - started, status=status,
            )


def _checklist_missing_labels(text: str) -> list[str]:
    from biyu.checklist.parser import ChecklistMissingError, parse_checklist

    labels = {
        "must_happen": "必须发生",
        "must_not_happen": "必须不发生",
        "ending_state": "结尾停在哪",
        "info_layers": "信息层级",
    }
    try:
        checklist = parse_checklist(text)
    except ChecklistMissingError:
        return list(labels.values())
    return [
        label for name, label in labels.items()
        if name in checklist.missing_category or not getattr(checklist, name)
    ]


def _architect_state_path(book_dir: Path, chapter: int) -> Path:
    return book_dir / "logs" / f"ch{chapter}" / "architect_state.json"


def _planning_draft_path(book_dir: Path, chapter: int) -> Path:
    """Unconfirmed work never replaces the plan currently consumed by Writer."""
    return book_dir / "logs" / f"ch{chapter}" / "planning_draft.md"


def _write_architect_state(book_dir: Path, chapter: int, payload: dict[str, Any]) -> None:
    path = _architect_state_path(book_dir, chapter)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_architect_state(book_dir: Path, chapter: int) -> dict[str, Any]:
    running = _WEB_ARCHITECT_RUNS.get((book_dir.name, chapter))
    if running:
        return {"state": "running", **running}
    path = _architect_state_path(book_dir, chapter)
    if not path.exists():
        return {"state": "idle", "missing_labels": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"state": "idle", "missing_labels": []}


async def generate_planning_with_architect(book: str, chapter: int) -> dict[str, Any]:
    """Validate fully in memory, then atomically replace planning.md once."""
    if not _web_architect_enabled():
        raise HTTPException(status_code=404, detail="网页导演功能尚未开启")
    book_dir = _book_dir(book)
    from biyu.pipeline import _read_north_star

    north_star, _source = _read_north_star(book_dir)
    injection_v2 = get_registry().get_feature("injection_v2") is True
    notices = (
        [] if north_star.strip() else ["本书方向说明暂未找到；本次方案仍按其余资料生成。"]
    ) if injection_v2 else []
    path = book_dir / "logs" / f"ch{chapter}" / "planning.md"
    target = _planning_draft_path(book_dir, chapter) if _planning_status(_read(path)) == "已批" else path
    result = await _call_web_architect(book_dir, chapter)
    if result.status != "ok" or not result.text.strip():
        rejected = {"state": "rejected", "missing_labels": [], "reason": "本次产出不完整，盘上方案未改变"}
        rejected["notices"] = notices
        _write_architect_state(book_dir, chapter, rejected)
        return rejected
    missing = _checklist_missing_labels(result.text)
    if missing:
        rejected = {"state": "rejected", "missing_labels": missing, "reason": "必检项不完整，盘上方案未改变"}
        rejected["notices"] = notices
        _write_architect_state(book_dir, chapter, rejected)
        return rejected
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.n2.tmp")
    temp.write_text(f"status: 待批\nsource: 导演产出\n{result.text}", encoding="utf-8")
    temp.replace(target)
    _write_architect_state(
        book_dir, chapter,
        {"state": "draft", "missing_labels": [], "notices": notices},
    )
    if target == path:
        write_workbench_step(book_dir, chapter, "planning")
    return {
        "state": "draft", "missing_labels": [], "cost": result.cost,
        "notices": notices,
    }


def _replica_status() -> dict[str, Any]:
    root = Path(os.environ.get("BIYU_REPLICA_ROOT", r"D:\biyu-data-replica"))
    path = root / "status.json"
    if not path.exists():
        return {"configured": False, "last_success": "", "snapshot_count": 0, "earliest_recovery": "", "failed": False, "last_error": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {"configured": True, "last_success": "", "snapshot_count": 0, "earliest_recovery": "", "failed": True, "last_error": "副本状态无法读取"}
    return {
        "configured": True,
        "last_success": str(data.get("last_success") or ""),
        "snapshot_count": int(data.get("snapshot_count") or 0),
        "earliest_recovery": str(data.get("earliest_recovery") or ""),
        "failed": bool(data.get("failed")),
        "last_error": str(data.get("last_error") or ""),
    }


@router.get("/replica-notice")
def replica_notice() -> dict[str, Any]:
    return load_author_notice_state()


@router.post("/replica-notice/acknowledge")
def acknowledge_replica_notice() -> dict[str, Any]:
    try:
        return acknowledge_replica_warning()
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="没有保存成功，请稍后再试；顶部提醒仍会保留。",
        ) from exc


def _data_roots() -> list[Path]:
    """All visible data roots: primary first, secondary second (I-1).

    用模块内 get_data_root(r3/o2 测试 patch workbench.get_data_root 亦生效)。
    """
    roots = [get_data_root()]
    second = get_data_root_2()
    if second is not None:
        roots.append(second)
    return roots


def _book_dir(book: str) -> Path:
    """Resolve a book across all visible data roots (I-1 dual-root)."""
    try:
        return find_book_dir(book, roots=_data_roots())
    except FileNotFoundError as exc:
        # Legacy workbench fixtures predate book.json; directory-name access
        # remains read-compatible, while real books still use shared lookup.
        for root in _data_roots():
            candidate = (root.resolve() / book).resolve()
            if candidate.parent == root.resolve() and candidate.is_dir():
                return candidate
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _book_root(book: str) -> Path:
    """Return the data root that owns the book (for read/write gating, I-1)."""
    book_dir = _book_dir(book)
    for root in _data_roots():
        if book_dir.parent == root.resolve():
            return root.resolve()
    raise HTTPException(status_code=404, detail=f"书的数据根无法识别: {book}")


@router.get("/books/{book}/setup-assets")
def setup_asset_versions(book: str) -> dict[str, Any]:
    book_dir = _book_dir(book)
    return {"assets": list_setup_asset_versions(book_dir)}


@router.post("/books/{book}/setup-assets/{asset_id}/versions/{version}/restore")
def restore_setup_asset(book: str, asset_id: str, version: int) -> dict[str, Any]:
    book_dir = _book_dir(book)
    try:
        restore_setup_asset_version(book_dir, asset_id, version)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "assets": list_setup_asset_versions(book_dir)}


@router.post("/books/{book}/setup-assets/notice/acknowledge")
def acknowledge_setup_asset_notice(book: str) -> dict[str, Any]:
    return acknowledge_setup_restore_notice(_book_dir(book))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _entry_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.lstrip().startswith("- "))


def _legacy_entry_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.startswith("- ") and not line.startswith("- {"))


def _sample_entries(*texts: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    archived: set[str] = set()
    for text in texts:
        for line in text.splitlines():
            if not line.startswith("- {"):
                continue
            try:
                item = json.loads(line[2:])
            except json.JSONDecodeError:
                continue
            if item.get("tombstone_for"):
                archived.add(str(item["tombstone_for"]))
            elif item.get("id"):
                entries.append(item)
    return [item for item in entries if str(item.get("id")) not in archived]


def _excerpt_trash(*texts: str) -> list[dict[str, Any]]:
    originals: dict[str, dict[str, Any]] = {}
    tombstones: list[dict[str, Any]] = []
    for text in texts:
        for line in text.splitlines():
            if not line.startswith("- {"):
                continue
            try:
                item = json.loads(line[2:])
            except json.JSONDecodeError:
                continue
            if item.get("tombstone_for"):
                tombstones.append(item)
            elif item.get("id"):
                originals[str(item["id"])] = item
    result = []
    for tombstone in tombstones:
        original_id = str(tombstone.get("tombstone_for", ""))
        original = tombstone.get("snapshot") or originals.get(original_id, {})
        if not original:
            continue
        result.append({
            "id": str(tombstone.get("id", "")),
            "kind": "excerpt",
            "original_id": original_id,
            "deleted_at": str(tombstone.get("created_at", "")),
            "text": str(original.get("text", "")),
            "excerpt_type": str(original.get("type", "problem")),
            "snapshot": original,
        })
    return result


def _append_sample_entry(book_dir: Path, item: dict[str, Any]) -> None:
    if item.get("type") != "good":
        raise ValueError("声纹负例只能由 R5-2 蒸馏复核产生")
    path = book_dir / "样本库" / "正例候选.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("- " + json.dumps(item, ensure_ascii=False) + "\n")


def _restore_excerpt(book_dir: Path, trash_id: str) -> None:
    entries = _excerpt_trash(_read(book_dir / "样本库" / "正例候选.md"), _read(book_dir / "样本库" / "负例候选.md"))
    entry = next((item for item in entries if item["id"] == trash_id), None)
    if entry is None:
        raise FileNotFoundError("回收站项目不存在")
    for name in ("正例候选.md", "负例候选.md"):
        path = book_dir / "样本库" / name
        if path.exists():
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if f'"id": "{trash_id}"' not in line]
            path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _purge_excerpt(book_dir: Path, trash_id: str) -> None:
    entries = _excerpt_trash(_read(book_dir / "样本库" / "正例候选.md"), _read(book_dir / "样本库" / "负例候选.md"))
    entry = next((item for item in entries if item["id"] == trash_id), None)
    if entry is None:
        raise FileNotFoundError("回收站项目不存在")
    original_marker = f'"id": "{entry["original_id"]}"'
    for name in ("正例候选.md", "负例候选.md"):
        path = book_dir / "样本库" / name
        if not path.exists():
            continue
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if f'"id": "{trash_id}"' not in line and original_marker not in line]
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _excerpt_trash_with_expiry(book_dir: Path) -> list[dict[str, Any]]:
    entries = _excerpt_trash(_read(book_dir / "样本库" / "正例候选.md"), _read(book_dir / "样本库" / "负例候选.md"))
    cutoff = datetime.now().astimezone() - timedelta(days=30)
    active = []
    for entry in entries:
        try:
            deleted = datetime.fromisoformat(entry["deleted_at"])
            if deleted.tzinfo is None:
                deleted = deleted.astimezone()
        except ValueError:
            active.append(entry)
            continue
        if deleted < cutoff:
            _purge_excerpt(book_dir, entry["id"])
        else:
            active.append(entry)
    return active


def _planning_status(text: str) -> str:
    first = text.splitlines()[0] if text.splitlines() else ""
    if first.startswith("status:"):
        return first.split(":", 1)[1].strip()
    return "\u65e0"


def _planning_source(text: str) -> str:
    """Author-facing provenance stored in planning.md, with legacy inference."""
    for line in text.splitlines()[:3]:
        if line.startswith("source:"):
            value = line.split(":", 1)[1].strip()
            if value in {"导演产出", "作者手写", "作者改过"}:
                return value
    return "导演产出" if text.strip() else "尚未保存"


def _planning_body(text: str) -> str:
    lines = text.splitlines()
    while lines and (lines[0].startswith("status:") or lines[0].startswith("source:")):
        lines.pop(0)
    return "\n".join(lines).lstrip("\r\n")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _memory_dirty(book_dir: Path, chapter: int) -> bool:
    path = book_dir / "logs" / f"ch{chapter}" / "memory_state.json"
    if not path.exists():
        return False
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("memory_dirty"))
    except (json.JSONDecodeError, OSError):
        # An unreadable durable state must be loud, never silently treated clean.
        return True


def _action(enabled: bool, reason: str = "") -> dict[str, Any]:
    return {"enabled": enabled, "reason": "" if enabled else reason}


def _state_actions(
    step: str, run: str, *, stale: bool, has_official: bool = False, has_pending: bool = False,
    has_outline: bool = False, has_planning: bool = False, planning_status: str = "无",
    has_planning_draft: bool = False,
    memory_dirty: bool = False, revision_rounds: int = 0,
) -> dict[str, dict[str, Any]]:
    in_reading = step in {"reading", "revision", "adoption"}
    actions = {
        "prefill_outline": _action(not has_outline, "本章已有细纲，不会用模板覆盖"),
        "save_outline": _action(run != "busy", "这一章正在处理中，请完成后再改细纲"),
        "architect": _action(
            _web_architect_enabled() and has_outline,
            "先保存细纲，再让导演写方案" if not has_outline else "网页导演功能尚未开启",
        ),
        "save_planning": _action(has_outline, "先保存细纲，再写方案"),
        "approve_planning": _action(
            has_outline and (planning_status != "已批" or has_planning_draft),
            "当前方案已经确认；修改文字或让导演重写后可再次确认" if planning_status == "已批" else "先保存细纲，再写方案",
        ),
        "revoke_planning": _action(has_planning and planning_status == "已批", "方案尚未确认，不需要退回"),
        "write": _action(step == "generation" and planning_status == "已批", "先确认方案，再生成正文"),
        "adopt": _action(
            in_reading and has_pending,
            "" if (in_reading and has_pending) else ("这一章已定稿" if has_official else "还没有正文，先去生成正文"),
        ),
        "edit_chapter": _action((in_reading and has_pending) or (step == "review" and has_official), "正文生成后才能自己修改"),
        "rewrite": _action(in_reading and has_pending, "先生成候选稿，再提交本轮修改"),
        "save_annotations": _action(in_reading and has_pending, "候选稿生成后才能批注"),
        "regenerate": _action(in_reading and has_pending and planning_status == "已批", "先确认方案，再重新生成"),
        "excerpt": _action((in_reading and has_pending) or (step == "review" and has_official), "正文生成后才能摘句"),
        "chapter_review": _action(step == "review" and has_official, "采用为正式正文后才能保存章评"),
        "archive_excerpt": _action(step == "review" and has_official, "采用为正式正文后才能整理摘句"),
        "retag_excerpt": _action(step == "review" and has_official, "采用为正式正文后才能整理摘句"),
        "refresh_memory": _action(memory_dirty, "本章记忆已经是最新状态"),
        "diagnose": _action(revision_rounds >= 3, "同一章完成第 3 轮修订后才会开放诊断"),
    }
    if run == "busy":
        return {key: _action(False, "这一章正在处理中，请稍候") for key in actions}
    return actions


_AUDITOR_AUTHOR_LABELS = {
    "dedup": "跨章重复",
    "worldbook_check": "设定一致性",
    "character_presence": "在场角色",
    "transition": "章节衔接",
    "style_repeat": "句式重复",
    "punctuation_density": "标点密度",
    "meta_vocab": "认知边界用词",
    "chapter_ending": "章末完整性",
    "dialogue_ratio": "对话密度",
    "character_naming": "角色称谓",
    "anchor_check": "硬信息锚点",
    "PLAN_UNAUTHORIZED_MAJOR_EVENT": "方案外重大事件",
}

_EDITOR_AUTHOR_LABELS = {
    "rhythm": "叙事节奏",
    "hook": "开篇与章末钩子",
    "ai_smell": "文风自然度",
    "meta_vocab": "说明式用词",
    "dialogue_ratio": "对话密度",
    "persona": "人物言行",
    "symbol_overuse": "人物标志重复",
    "dialogue_id": "对话辨识度",
    "personality_anchor": "人物性格锚点",
    "tier_rigor": "战力等级",
    "facts": "设定事实",
    "forbidden": "禁忌设定",
    "naming": "命名一致性",
    "hooks_audit": "伏笔与回收",
    "appearance_audit": "外貌一致性",
    "visual_clash": "视觉符号冲突",
    "cross_chapter": "跨章衔接",
}

_SEVERITY_AUTHOR_LABELS = {
    "BLOCK": "必须处理",
    "WARN": "建议修改",
    "PASS": "已通过",
    "SKIP": "本章不适用",
}

_STYLE_PATTERN_LABELS = {
    "不是[^。，]*[，。](?:而)?是": "『不是 X 而是 Y』",
    "不是[^。，]*[，。]不是": "『不是 X，不是 Y』",
    "与其说.*不如说": "『与其说 X，不如说 Y』",
    "在这一刻": "『在这一刻』",
    "仿佛.*一般": "『仿佛 X 一般』",
    "仿佛.*一样": "『仿佛 X 一样』",
    "心中(暗想|暗叹|不由得|不禁)": "『心中暗想／暗叹』",
    "一股.*涌上心头": "『一股 X 涌上心头』",
    "不由得.*起来": "『不由得 X 起来』",
    "眼眸中闪过一丝": "『眼眸中闪过一丝』",
    "嘴角勾起一抹": "『嘴角勾起一抹』",
    "刹那间": "『刹那间』",
}


def _author_type_label(internal_name: Any, *, editor: bool = False) -> str:
    name = str(internal_name or "")
    labels = _EDITOR_AUTHOR_LABELS if editor else _AUDITOR_AUTHOR_LABELS
    if name in labels:
        return labels[name]
    if name and not re.search(r"[A-Za-z_]", name):
        return name
    return "编辑意见" if editor else "规则检查"


def _match_locations(text: str, pattern: str) -> tuple[list[int], str]:
    try:
        matches = list(re.finditer(pattern, text))
    except re.error:
        return [], ""
    lines = sorted({text.count("\n", 0, match.start()) + 1 for match in matches})
    quote = matches[0].group(0) if matches else ""
    return lines, quote


def _line_label(lines: list[int]) -> str:
    return "、".join(f"第 {line} 行" for line in lines) if lines else "整章"


def _auditor_author_projection(result: dict[str, Any], chapter_text: str) -> dict[str, Any]:
    checker = str(result.get("checker") or "")
    details = result.get("details") if isinstance(result.get("details"), dict) else {}
    judgment = "规则检查发现一处需要核对的问题。"
    lines: list[int] = []
    quote = ""

    if checker == "style_repeat":
        current = details.get("current_counts") if isinstance(details.get("current_counts"), dict) else {}
        recent = details.get("recent_3ch_counts") if isinstance(details.get("recent_3ch_counts"), dict) else {}
        violations = "\n".join(str(value) for value in details.get("violations", []) if isinstance(value, str))
        summaries: list[str] = []
        all_lines: list[int] = []
        for pattern, label in _STYLE_PATTERN_LABELS.items():
            if pattern not in violations:
                continue
            count = int(current.get(pattern, 0) or 0)
            recent_count = int(recent.get(pattern, 0) or 0)
            pattern_lines, pattern_quote = _match_locations(chapter_text, pattern)
            if count:
                summaries.append(f"{label}这个句式出现 {count} 次 · {_line_label(pattern_lines)}")
                all_lines.extend(pattern_lines)
                quote = quote or pattern_quote
            elif recent_count:
                summaries.append(f"{label}这个句式近四章累计出现 {recent_count} 次 · 近四章")
        if summaries:
            judgment = "\n".join(summaries)
            lines = sorted(set(all_lines))
    elif checker == "dedup":
        chapter = details.get("similar_with_chapter")
        judgment = f"本章与第 {chapter} 章有较多重复内容，请检查是否需要改写。" if chapter else "本章与前文有较多重复内容，请检查是否需要改写。"
    elif checker == "worldbook_check":
        judgment = "正文可能与已确认设定不一致，请核对人物或设定事实。"
    elif checker == "character_presence":
        missing = [str(value) for value in details.get("missing", []) if str(value).strip()]
        unexpected = [str(value) for value in details.get("unexpected", []) if str(value).strip()]
        parts = []
        if missing:
            parts.append(f"本章应在场但没有出现：{'、'.join(missing)}")
        if unexpected:
            parts.append(f"本章出现了不在本章清单中的角色：{'、'.join(unexpected)}")
        judgment = "；".join(parts) or "本章的在场角色需要核对。"
    elif checker == "transition":
        judgment = "本章开头与上一章结尾承接较弱，请核对场景、人物或动作是否接得上。"
        head = str(details.get("curr_head") or "").strip()
        if head and head in chapter_text:
            quote = head
            lines, _ = _match_locations(chapter_text, re.escape(head))
    elif checker == "punctuation_density":
        values = []
        for key, label in (("em_dash_per_k", "破折号"), ("ellipsis_per_k", "省略号"), ("exclamation_per_k", "感叹号")):
            if key in details:
                values.append(f"{label}每千字约 {details[key]} 个")
        judgment = f"本章标点使用偏密：{'，'.join(values)}。" if values else "本章标点使用偏密，请检查是否影响阅读节奏。"
    elif checker == "meta_vocab":
        raw = "\n".join(str(value) for value in details.get("violations", []) if isinstance(value, str))
        found = re.search(r"'([^']+)'\s*出现\s*(\d+)\s*次", raw)
        if found:
            word, count = found.groups()
            lines, quote = _match_locations(chapter_text, re.escape(word))
            judgment = f"『{word}』这类跨时空表述出现 {count} 次 · {_line_label(lines)}"
        else:
            judgment = "正文出现了可能越过人物认知边界的说法，请结合故事时空核对。"
    elif checker == "chapter_ending":
        judgment = "章末与前文内容重复度偏高，可能在收束后又重新起了一段。"
    elif checker == "dialogue_ratio":
        ratio = details.get("ratio")
        judgment = f"本章对话约占 {float(ratio):.0%}，可能过密，请检查叙述与动作是否足够。" if isinstance(ratio, (int, float)) else "本章对话可能过密，请检查叙述与动作是否足够。"
    elif checker == "character_naming":
        raw = "\n".join(str(value) for value in details.get("violations", []) if isinstance(value, str))
        found = re.search(r"禁用称谓'([^']+)'出现(\d+)次", raw)
        if found:
            word, count = found.groups()
            lines, quote = _match_locations(chapter_text, re.escape(word))
            judgment = f"正文中的临时代称『{word}』出现 {count} 次 · {_line_label(lines)}"
        else:
            judgment = "正文出现了不应直接写给读者看的角色代称。"
    elif checker == "anchor_check":
        mismatch = int(details.get("value_mismatch", 0) or 0)
        missing = int(details.get("missing", 0) or 0)
        judgment = f"有 {mismatch} 处硬信息与已确认值不一致，请逐项核对。" if mismatch else f"有 {missing} 处本章应出现的硬信息没有找到。"
    elif checker == "PLAN_UNAUTHORIZED_MAJOR_EVENT":
        evidence = str(details.get("chapter_evidence") or "").strip()
        judgment = f"正文写了方案中没有确认的重大事件：{evidence}" if evidence else "正文出现了方案中没有确认的重大事件。"
        if evidence and evidence in chapter_text:
            quote = evidence
            lines, _ = _match_locations(chapter_text, re.escape(evidence))

    return {
        "type": _author_type_label(checker),
        "severity_label": _SEVERITY_AUTHOR_LABELS.get(str(result.get("severity", "")).upper(), "需要核对"),
        "judgment": judgment,
        "line": lines[0] if lines else 0,
        "position_label": _line_label(lines),
        "quote": quote,
    }


def _load_issue_cards(path: Path, chapter_text: str = "") -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    annotations = data.get("workbench_annotations", {})
    cards: list[dict[str, Any]] = []
    for issue in data.get("issues", []):
        if issue.get("status") == "dismissed":
            continue
        issue_id = str(issue.get("id") or "")
        note = annotations.get(issue_id, {})
        editor_severity = str(issue.get("severity", "medium")).lower()
        cards.append({
            "id": issue_id,
            "source": "editor",
            "severity": "BLOCK" if editor_severity == "high" else "WARN",
            "editor_severity": editor_severity,
            "severity_label": _SEVERITY_AUTHOR_LABELS["BLOCK" if editor_severity == "high" else "WARN"],
            "type": _author_type_label(issue.get("type", "编辑意见"), editor=True),
            "line": issue.get("paragraph", issue.get("line", 0)),
            "position_label": f"第 {issue.get('paragraph', issue.get('line', 0))} 段" if issue.get("paragraph", issue.get("line", 0)) else "整章",
            "quote": issue.get("quoted_text", issue.get("quote", "")),
            "judgment": issue.get("description", issue.get("explanation", "")),
            "explanation": issue.get("explanation", ""),
            "suggestion": issue.get("suggestion", issue.get("fix_suggestion", "")),
            "selected": bool(note.get("selected", False)),
            "ignored": bool(note.get("ignored", False)),
            "author_comment": str(note.get("author_comment", "")),
        })
    for index, result in enumerate(data.get("results", []), 1):
        severity = str(result.get("severity", "")).upper()
        if severity not in {"WARN", "BLOCK"}:
            continue
        issue_id = f"auditor-{result.get('checker', 'check')}-{index}"
        note = annotations.get(issue_id, {})
        author = _auditor_author_projection(result, chapter_text)
        cards.append({
            "id": issue_id,
            "source": "auditor",
            "severity": severity,
            "severity_label": author["severity_label"],
            "type": author["type"],
            "line": author["line"],
            "position_label": author["position_label"],
            "quote": author["quote"],
            "judgment": author["judgment"],
            "explanation": "",
            "suggestion": "请结合正文核对并给出本轮修改意见",
            "selected": bool(note.get("selected", False)),
            "ignored": bool(note.get("ignored", False)),
            "author_comment": str(note.get("author_comment", "")),
        })
    return cards


def _review_state_path(book_dir: Path, chapter: int) -> Path:
    return book_dir / "logs" / f"ch{chapter}" / "workbench_review_state.json"


def _read_review_state(book_dir: Path, chapter: int) -> tuple[dict[str, Any], str]:
    path = _review_state_path(book_dir, chapter)
    if not path.exists():
        return {}, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}, "意见版本状态无法读取；当前不把它当作已检查"
    if not isinstance(data, dict):
        return {}, "意见版本状态格式不正确；当前不把它当作已检查"
    return data, ""


def _write_review_state(book_dir: Path, chapter: int, state: dict[str, Any]) -> None:
    path = _review_state_path(book_dir, chapter)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _checklist_feature_enabled() -> bool:
    return get_registry().get_feature("checklist")


_CHECKLIST_CATEGORY_LABELS = {
    "must_happen": "必须发生",
    "must_not_happen": "禁止发生",
    "ending_state": "结尾状态",
    "info_layers": "信息层级",
}


def _load_checklist_cards(
    book_dir: Path, chapter: int, candidate_sha: str, report_json: Path,
) -> tuple[list[dict[str, Any]], str, dict[str, int]]:
    candidates_dir = book_dir / "logs" / f"ch{chapter}" / "candidates"
    results: list[tuple[Path, dict[str, Any]]] = []
    for path in candidates_dir.glob("*_checklist.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            results.append((path, data))
    empty_meta = {"total": 0, "unresolved": 0}
    if not results:
        return [], "legacy_no_items", empty_meta

    matching = [
        entry for entry in results
        if str(entry[1].get("candidate_sha") or "") == candidate_sha
    ]
    if not matching:
        if any(str(data.get("candidate_sha") or "") for _path, data in results):
            return [], "version_mismatch", empty_meta
        return [], "unversioned", empty_meta

    path, data = max(
        matching,
        key=lambda entry: (entry[0].stat().st_mtime_ns, entry[0].name),
    )
    del path
    raw_items = data.get("items", [])
    items = raw_items if isinstance(raw_items, list) else []
    unresolved = sum(
        1 for item in items
        if isinstance(item, dict) and str(item.get("verdict", "")).lower() in {"unclear", "invalid"}
    )
    try:
        report_data = json.loads(report_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        report_data = {}
    annotations = report_data.get("workbench_annotations", {})
    if not isinstance(annotations, dict):
        annotations = {}

    cards: list[dict[str, Any]] = []
    for position, item in enumerate(items):
        if not isinstance(item, dict) or str(item.get("verdict", "")).lower() != "unmet":
            continue
        category = str(item.get("category") or "checklist")
        item_index = item.get("index", position)
        issue_id = f"checklist-{candidate_sha[:12]}-{category}-{item_index}"
        note = annotations.get(issue_id, {})
        if not isinstance(note, dict):
            note = {}
        raw_quotes = item.get("quotes", [])
        quotes = [
            value.strip() for value in raw_quotes
            if isinstance(value, str) and value.strip()
        ] if isinstance(raw_quotes, list) else []
        cards.append({
            "id": issue_id,
            "source": "checklist",
            "severity": "WARN",
            "severity_label": _SEVERITY_AUTHOR_LABELS["WARN"],
            "type": _CHECKLIST_CATEGORY_LABELS.get(category, "戏核条目"),
            "line": 0,
            "position_label": "引文位置" if quotes else "整章",
            "quote": quotes[0] if quotes else "",
            "quotes": quotes,
            "judgment": str(item.get("text") or ""),
            "explanation": str(item.get("reason") or ""),
            "suggestion": "请结合正文核对并给出本轮修改意见",
            "selected": bool(note.get("selected", False)),
            "ignored": bool(note.get("ignored", False)),
            "author_comment": str(note.get("author_comment", "")),
        })
    state = "checked_with_issues" if cards else "checked_clean"
    return cards, state, {"total": len(items), "unresolved": unresolved}


def _reading_states(
    *, pending_exists: bool, has_chapter: bool, report_json: Path,
    editor_cards: list[dict[str, Any]], review_state_error: str,
    checklist_state: str,
) -> tuple[str, str, dict[str, str]]:
    manuscript_state = "candidate" if pending_exists else ("official" if has_chapter else "missing")
    if review_state_error or not report_json.exists():
        editor_state = "unchecked"
    else:
        editor_state = "checked_with_issues" if editor_cards else "checked_clean"
    sources = {
        "editor": editor_state,
        "checklist": checklist_state,
    }
    if "checked_with_issues" in sources.values():
        check_state = "checked_with_issues"
    elif "checked_clean" in sources.values():
        check_state = "checked_clean"
    else:
        check_state = "unchecked"
    return manuscript_state, check_state, sources


def _completed_check_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    return sum(
        1 for item in data.get("results", [])
        if str(item.get("severity", "")).upper() in {"PASS", "SKIP"}
    )


def _completed_checks(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    completed = []
    for item in data.get("results", []):
        severity = str(item.get("severity", "")).upper()
        if severity not in {"PASS", "SKIP"}:
            continue
        label = _author_type_label(item.get("checker"))
        completed.append({
            "severity": severity,
            "severity_label": _SEVERITY_AUTHOR_LABELS[severity],
            "type": label,
            "message": f"{label}未发现问题。" if severity == "PASS" else f"{label}本章无需检查。",
        })
    return completed


def chapter_snapshot(book_dir: Path, chapter: int, book_key: str | None = None) -> dict[str, Any]:
    from biyu.ui.workbench_state import has_diagnosis_return
    outline = book_dir / "outlines" / f"ch{chapter}.md"
    planning = book_dir / "logs" / f"ch{chapter}" / "planning.md"
    planning_draft = _planning_draft_path(book_dir, chapter)
    pending = book_dir / "chapters" / "_pending" / f"ch{chapter}.md"
    chapter_path = book_dir / "chapters" / f"ch{chapter}.md"
    report = book_dir / "audit_reports" / f"ch{chapter}.md"
    report_json = book_dir / "audit_reports" / f"ch{chapter}.json"
    verdict = book_dir / "\u5224\u8bcd" / f"ch{chapter}.md"
    positive = book_dir / "\u6837\u672c\u5e93" / "\u6b63\u4f8b\u5019\u9009.md"
    negative = book_dir / "\u6837\u672c\u5e93" / "\u8d1f\u4f8b\u5019\u9009.md"
    sample_entries = _sample_entries(_read(positive), _read(negative))
    memory_dirty = _memory_dirty(book_dir, chapter)
    revision_rounds = revision_round_count(book_dir, chapter)
    from biyu.outline_fact_reader import check_outline_facts
    outline_text = _read(outline)
    outline_fact_check = check_outline_facts(book_dir, outline_text)
    from biyu.pipeline import _parse_present_characters
    from biyu.prompts.chapter_writer import resolve_present_characters
    character_resolution = resolve_present_characters(
        _parse_present_characters(outline_text, book_dir),
        load_characters_yaml(book_dir),
    )
    missing_character_names = character_resolution.unmatched_names
    outline_character_notice = {
        "count": len(missing_character_names),
        "names": missing_character_names,
        "message": (
            f"这一章点到 {len(missing_character_names)} 个名字没有人物卡："
            + "、".join(missing_character_names)
            + "。写手查不到他们的设定，可以去设定集补，也可以就这么写。"
        ) if missing_character_names else "",
        "blocking": False,
    }
    pending_exists = pending.exists()
    has_outline = outline.exists()
    has_chapter = chapter_path.exists()
    assets = asset_state(book_dir, chapter)
    planning_status = _planning_status(_read(planning))
    displayed_planning = _read(planning_draft) if planning_draft.exists() else _read(planning)
    architect_state = _read_architect_state(book_dir, chapter)
    visible_chapter = pending if pending_exists else chapter_path
    visible_text = _read(visible_chapter)
    visible_sha = _sha(visible_text)
    editor_cards = _load_issue_cards(report_json, visible_text)
    checklist_enabled = _checklist_feature_enabled()
    if checklist_enabled:
        checklist_cards, checklist_state, checklist_meta = _load_checklist_cards(
            book_dir, chapter, visible_sha, report_json,
        )
    else:
        checklist_cards = []
        checklist_state = "feature_off"
        checklist_meta = {"total": 0, "unresolved": 0}
    issue_cards = [*editor_cards, *checklist_cards]
    review_state, review_state_error = _read_review_state(book_dir, chapter)
    manuscript_state, check_state, check_sources = _reading_states(
        pending_exists=pending_exists,
        has_chapter=has_chapter,
        report_json=report_json,
        editor_cards=editor_cards,
        review_state_error=review_state_error,
        checklist_state=checklist_state,
    )
    editor_base_sha = str(review_state.get("editor_base_sha") or "")
    review_stale = bool(report_json.exists() and editor_base_sha and editor_base_sha != visible_sha)
    running = running_action(book_key or book_dir.name, chapter)
    persisted_run, failure_card = persisted_run_state(book_dir, chapter)
    run = "busy" if running else persisted_run
    step = read_workbench_step(book_dir, chapter)
    # A written candidate records the exact plan version it consumed. File mtimes
    # are only a compatibility fallback for candidates created before version cards.
    bound_plan_stale = candidate_plan_is_stale(book_dir, chapter) if pending_exists else None
    stale = bool(
        planning_status == "\u5df2\u6279"
        and visible_chapter.exists()
        and (
            bound_plan_stale
            if bound_plan_stale is not None
            else planning.stat().st_mtime_ns > visible_chapter.stat().st_mtime_ns
        )
    )
    candidate_versions = list_candidate_versions(book_dir, chapter)
    first_generation = not (
        candidate_versions or pending_exists or has_chapter
    )
    next_by_step = {
        "outline": ("prefill_outline", "写细纲", "先写下本章要发生什么。"),
        "planning": ("talk", "请导演出方案", "导演会读取本章细纲。"),
        "generation": ("write", "生成正文", "确认费用后开始生成。"),
        "reading": ("adopt", "读稿定夺", "读正文和审读报告，满意后再采用。"),
        "revision": ("rewrite", "提交整章修订", "带着本轮批注生成新候选稿。"),
        "adoption": ("adopt", "采用为正式正文", "采用后才更新跨章记忆。"),
        "review": ("chapter_review", "评章摘句", "可以摘句并保存章评。"),
    }
    next_id, next_label, next_hint = next_by_step[step]
    if step == "planning" and planning.exists():
        next_id, next_label, next_hint = "approve_planning", "确认方案", "改到满意后再确认。"
    if run == "busy":
        next_id, next_label, next_hint = "running", "本章处理中", "完成后页面会显示结果。"
    elif run == "fail":
        failed_action = str(failure_card.get("action", ""))
        retry_steps = {
            "diagnose": ("diagnose", "重试诊断"),
            "rewrite": ("rewrite", "重试本轮修订"),
            "adopt": ("adopt", "重试采用"),
        }
        next_id, next_label = retry_steps.get(failed_action, ("write", "重试生成"))
        next_hint = "失败没有改动正文或当前步骤。"
    elif step == "review" and stale:
        next_id, next_label, next_hint = "write", "按新方案生成候选稿", "正式正文不动，候选稿等待定夺。"
    return {
        "chapter": chapter,
        "replica_status": _replica_status(),
        "replica_notice": load_author_notice_state(),
        "setup_restore_notice": load_setup_restore_notice(book_dir),
        "badges": {
            "outline": "\u6709" if has_outline else "\u65e0",
            "planning": planning_status,
            "chapter": "\u5f85\u6536" if pending_exists else ("\u5df2\u6536" if has_chapter else "\u65e0"),
            "report": "\u6709" if report.exists() else "\u65e0",
            "verdict": "\u6709\u7ae0\u8bc4" if verdict.exists() else "\u65e0",
        },
        "outline": _read(outline),
        "outline_fact_check": outline_fact_check,
        "outline_character_notice": outline_character_notice,
        "planning": displayed_planning,
        "planning_asset_notice": (
            _planning_asset_notice(book_dir, displayed_planning)
            if planning_status == "已批"
            else {
                "character_names": [], "worldbook_names": [],
                "character_check": "not_applicable", "worldbook_check": "not_applicable",
                "message": "", "blocking": False,
            }
        ),
        "planning_source": _planning_source(displayed_planning),
        "planning_has_draft": planning_draft.exists(),
        "web_architect": {
            "enabled": _web_architect_enabled(),
            "estimate": _architect_estimate(book_dir),
            **architect_state,
        },
        "chapter_text": visible_text,
        "official_text": _read(chapter_path),
        "chapter_source": "pending" if pending_exists else "official",
        "chapter_target": "pending" if pending_exists else "official",
        "official_locked": pending_exists and has_chapter,
        "official_lock_reason": "修订轮已有候选稿；正式正文保持只读，请在候选稿上修改" if pending_exists and has_chapter else "",
        "chapter_sha": visible_sha,
        "outline_sha": _sha(_read(outline)),
        "planning_sha": _sha(displayed_planning),
        "report_sha": _sha(_read(report_json)),
        "verdict_sha": _sha(_read(verdict)),
        "positive_sha": _sha(_read(positive)),
        "negative_sha": _sha(_read(negative)),
        "report": _read(report),
        "issue_cards": issue_cards,
        "unhandled_issue_count": sum(
            1 for card in issue_cards if not card.get("selected") and not card.get("ignored")
        ),
        "manuscript_state": manuscript_state,
        "check_state": check_state,
        "check_sources": check_sources,
        "check_source_meta": {"checklist": checklist_meta},
        "review_stale": review_stale,
        "review_state_error": review_state_error,
        "check_completed": _completed_check_count(report_json),
        "completed_checks": _completed_checks(report_json),
        "verdict": _read(verdict),
        "chapter_complete": verdict.exists(),
        "axes": {"asset": assets, "step": step, "run": run},
        "stage": STEP_STAGE[step],
        "first_generation": first_generation,
        "stale": stale,
        "running_action": running,
        "failure_card": failure_card,
        "memory_dirty": memory_dirty,
        "revision_rounds": revision_rounds,
        "diagnosis_return_available": has_diagnosis_return(book_dir, chapter),
        "diagnosis": {
            **read_diagnosis(book_dir, chapter),
            "fresh": diagnosis_is_fresh(book_dir, chapter),
        } if read_diagnosis(book_dir, chapter) else {},
        "current_plan_version": current_plan_version(book_dir, chapter),
        "current_outline_version": current_outline_version(book_dir, chapter),
        "outline_versions": list_outline_versions(book_dir, chapter),
        "plan_versions": list_plan_versions(book_dir, chapter),
        "candidate_versions": candidate_versions,
        "trash": list_trash(book_dir, chapter) + _excerpt_trash_with_expiry(book_dir),
        "actions": _state_actions(
            step, run, stale=stale, has_official=has_chapter, has_pending=pending_exists,
            has_outline=has_outline, has_planning=planning.exists(), planning_status=planning_status,
            has_planning_draft=planning_draft.exists(),
            memory_dirty=memory_dirty, revision_rounds=revision_rounds,
        ),
        "next_step": {"id": next_id, "label": next_label, "hint": next_hint},
        "positive_candidates": _read(positive),
        "negative_candidates": _read(negative),
        "samples": sample_entries,
        "verdict_receipt": {
            "verdict_path": str(verdict) if verdict.exists() else "",
            "positive_count": _legacy_entry_count(_read(positive)) + sum(1 for item in sample_entries if item.get("type") == "good"),
            "negative_count": _legacy_entry_count(_read(negative)) + sum(1 for item in sample_entries if item.get("type") == "problem"),
        },
    }


def _memory_snapshot(book_dir: Path) -> dict[str, Any]:
    from biyu.memory_projection import rebuild_memory
    from biyu.projections import read_shards
    from biyu.truth_files import read_pins

    chapters_dir = book_dir / "chapters"
    chapters = {
        int(path.stem[2:]) for path in chapters_dir.glob("ch*.md")
        if path.stem[2:].isdigit()
    } if chapters_dir.exists() else set()
    try:
        shards = read_shards(book_dir, chapters)
    except (FileNotFoundError, ValueError) as exc:
        return {"entries": [], "conflicts": [], "error": str(exc)}
    pins = read_pins(book_dir)
    result = rebuild_memory(shards, chapters, pins)
    entries = []
    for filename, values in result.values.items():
        for key, value in values.items():
            if key.startswith("__"):
                continue
            compound = f"{filename}:{key}"
            entries.append({
                "file": filename,
                "key": key,
                "value": value,
                "pinned": compound in pins,
            })
    return {"entries": entries, "conflicts": result.conflicts, "error": ""}


@router.get("/books")
def books() -> dict[str, list[dict[str, str]]]:
    result = []
    for root in _data_roots():
        for path in sorted(root.iterdir()):
            if not path.is_dir() or not (path / "book.json").exists():
                continue
            try:
                meta = json.loads((path / "book.json").read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                meta = {}
            result.append({
                "name": path.name,
                "id": str(meta.get("id") or path.name),
                "display_name": str(meta.get("display_name") or meta.get("title") or path.name),
            })
    return {"books": result}


@router.get("/books/{book}/chapters/{chapter}")
def get_chapter(book: str, chapter: int) -> dict[str, Any]:
    return chapter_snapshot(_book_dir(book), chapter, book)


@router.post("/books/{book}/chapters/{chapter}/feedback")
def record_feedback(book: str, chapter: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist one mark without exposing a feedback-ledger reader."""
    book_dir = _book_dir(book)
    visible = (
        book_dir / "chapters" / "_pending" / f"ch{chapter}.md"
        if (book_dir / "chapters" / "_pending" / f"ch{chapter}.md").exists()
        else book_dir / "chapters" / f"ch{chapter}.md"
    )
    if not visible.exists():
        raise HTTPException(status_code=409, detail="当前没有可标记的正文")
    candidate_sha = str(payload.get("candidate_sha", ""))
    if candidate_sha != _sha(_read(visible)):
        raise HTTPException(status_code=409, detail="正文版本已经变化，请刷新后重新划句")
    action = str(payload.get("action", ""))
    try:
        entry = append_feedback(
            book_dir,
            book=book,
            chapter=chapter,
            round_no=revision_round_count(book_dir, chapter),
            scope="sentence",
            candidate_sha=candidate_sha,
            anchor=int(payload.get("anchor", 0) or 0),
            text=str(payload.get("text", "")),
            action=action,
            author_comment=str(payload.get("author_comment", "")),
            in_revision_package=action == "revise",
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if action == "good":
        _append_sample_entry(book_dir, {
            "id": entry["id"],
            "type": "good",
            "text": entry["text"],
            "book": book_dir.name,
            "chapter": chapter,
            "version_sha": entry["candidate_sha"],
            "anchor": entry["anchor"],
            "created_at": entry["created_at"],
            "status": "候选",
        })
    return {
        "entry": entry,
        "snapshot": chapter_snapshot(book_dir, chapter, book),
    }


def _import_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items")
    if isinstance(items, list) and items:
        return [item for item in items if isinstance(item, dict)]
    text = str(payload.get("text", ""))
    identity = str(payload.get("identity", ""))
    if bool(payload.get("split_explicit", False)):
        return items_from_explicit_text(
            text,
            identity=identity,
            source=str(payload.get("source") or "paste"),
        )
    return [{
        "chapter": int(payload.get("chapter", 0) or 0),
        "content": text,
        "identity": identity,
        "source": str(payload.get("source") or "paste"),
    }]


@router.post("/books/{book}/imports/preview")
def preview_manuscript_import(book: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return preview_import(_book_dir(book), _import_items(payload))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/books/{book}/imports")
def commit_manuscript_import(book: str, payload: dict[str, Any]) -> dict[str, Any]:
    book_dir = _book_dir(book)
    try:
        results = import_manuscripts(
            book_dir,
            _import_items(payload),
            confirmed=bool(payload.get("confirmed", False)),
        )
    except ImportConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    for result in results:
        write_workbench_step(
            book_dir,
            int(result["chapter"]),
            "reading" if result["identity"] == "candidate" else "review",
        )
    return {"imported": results, "llm_calls": 0, "estimated_cost": 0.0}


def _build_imported_projection(book_dir: Path, chapter: int, official: Path) -> dict[str, Any]:
    from biyu.cli.workbench_cmd import _run_official_observer
    from biyu.projections import read_shard

    if not _run_official_observer(book_dir, chapter, official):
        raise RuntimeError(f"第 {chapter} 章记忆没有建立成功")
    return read_shard(book_dir, chapter)


@router.post("/books/{book}/imports/memory/preview")
def preview_imported_memory(book: str, payload: dict[str, Any]) -> dict[str, Any]:
    chapters = [int(value) for value in payload.get("chapters", [])]
    try:
        return preview_memory(_book_dir(book), chapters, _build_imported_projection)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/books/{book}/imports/memory/continue")
def continue_imported_memory(book: str, payload: dict[str, Any]) -> dict[str, Any]:
    book_dir = _book_dir(book)
    chapters = sorted(set(int(value) for value in payload.get("chapters", []) if int(value) > 0))
    if not bool(payload.get("confirmed", False)):
        raise HTTPException(status_code=409, detail="请先确认首章提取结果")
    completed = []
    for chapter in chapters:
        official = book_dir / "chapters" / f"ch{chapter}.md"
        if not official.exists():
            raise HTTPException(status_code=404, detail=f"第 {chapter} 章正式稿不存在")
        try:
            _build_imported_projection(book_dir, chapter, official)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        completed.append(chapter)
    return {"completed": completed, "remaining": [], "calls": len(completed)}


@router.get("/books/{book}/memory")
def get_memory(book: str) -> dict[str, Any]:
    return _memory_snapshot(_book_dir(book))


@router.put("/books/{book}/memory/pins")
def save_memory_pin(book: str, payload: dict[str, str]) -> dict[str, Any]:
    from biyu.observer import replay_persisted_projections
    from biyu.truth_files import pin_truth_entry
    book_dir = _book_dir(book)
    try:
        pin_truth_entry(book_dir, payload.get("file", ""), payload.get("key", ""), payload.get("value", ""))
        replay_persisted_projections(book_dir)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _memory_snapshot(book_dir)


@router.delete("/books/{book}/memory/pins")
def delete_memory_pin(book: str, file: str, key: str) -> dict[str, Any]:
    from biyu.observer import replay_persisted_projections
    from biyu.truth_files import unpin_truth_entry
    book_dir = _book_dir(book)
    unpin_truth_entry(book_dir, file, key)
    replay_persisted_projections(book_dir)
    return _memory_snapshot(book_dir)


@router.post("/books/{book}/memory/conflicts/resolve")
def resolve_memory_conflict(book: str, payload: dict[str, str]) -> dict[str, Any]:
    from biyu.observer import replay_persisted_projections
    from biyu.truth_files import resolve_pin_conflict
    book_dir = _book_dir(book)
    try:
        resolve_pin_conflict(book_dir, payload.get("file", ""), payload.get("key", ""), payload.get("choice", ""))
        replay_persisted_projections(book_dir)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _memory_snapshot(book_dir)


@router.post("/books/{book}/chapters/{chapter}/undo-adopt")
def undo_adoption(book: str, chapter: int) -> dict[str, Any]:
    from biyu.cli.workbench_cmd import _commit_undo_adoption, _undo_adopt
    from biyu.observer import replay_persisted_projections
    book_dir = _book_dir(book)
    try:
        result = _undo_adopt(
            book_dir,
            chapter,
            commit_fn=_commit_undo_adoption,
            rebuild_runner=lambda current_book, _chapter: replay_persisted_projections(current_book),
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    snapshot = chapter_snapshot(book_dir, chapter, book)
    snapshot["undo_notice"] = (
        "这一章退回候选状态，世界观和角色卡已跟着退回。之后各章已经写好的正文不会被改动。"
        if result.memory_updated else
        "正文已退回候选状态；记忆重放未完成，可稍后重试。"
    )
    return snapshot


def _history_action(message: str) -> str:
    if "采用为正式正文" in message or "adopt" in message.lower():
        return "采用"
    if "修订" in message or "revise" in message.lower():
        return "修订"
    if message.lower().startswith("manual:") or "手动" in message:
        return "手改"
    if "初次生成" in message or message.lower().startswith("auto:"):
        return "初稿"
    return "保存"


def _git_chapter_history(book_dir: Path, chapter: int) -> list[dict[str, Any]]:
    try:
        from biyu.git_helper import repo_root_for_book

        root = repo_root_for_book(book_dir)
        rel_book = book_dir.resolve().relative_to(root)
    except (RuntimeError, ValueError):
        return []
    paths = [rel_book / "chapters" / f"ch{chapter}.md", rel_book / "chapters" / "_pending" / f"ch{chapter}.md"]
    path_strings = [path.as_posix() for path in paths]
    command = ["git", "log", "--format=%H%x1f%aI%x1f%s", "--", *path_strings]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        return []
    entries: list[dict[str, Any]] = []
    previous_count: int | None = None
    for line in result.stdout.splitlines():
        parts = line.split("\x1f", 2)
        if len(parts) != 3:
            continue
        commit, timestamp, message = parts
        changed = subprocess.run(
            ["git", "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", commit, "--", *path_strings],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        changed_paths = [path for path in changed.stdout.splitlines() if path in path_strings]
        content = ""
        selected_path = ""
        blob = ""
        for rel_path in changed_paths:
            shown = subprocess.run(["git", "show", f"{commit}:{rel_path}"], cwd=root, capture_output=True, text=True, encoding="utf-8")
            resolved_blob = subprocess.run(["git", "rev-parse", f"{commit}:{rel_path}"], cwd=root, capture_output=True, text=True, encoding="utf-8")
            if shown.returncode == 0 and resolved_blob.returncode == 0:
                content = shown.stdout
                selected_path = rel_path
                blob = resolved_blob.stdout.strip()
                break
        if not selected_path:
            continue
        count = sum(1 for char in content if "\u4e00" <= char <= "\u9fff")
        entries.append({"commit": commit, "path": selected_path, "blob": blob, "time": timestamp, "action": _history_action(message), "message": message, "word_count": count, "delta": None})
        if previous_count is not None:
            entries[-2]["delta"] = previous_count - count
        previous_count = count
    return entries


@router.get("/books/{book}/chapters/{chapter}/history")
def chapter_history(book: str, chapter: int) -> dict[str, Any]:
    return {"versions": _git_chapter_history(_book_dir(book), chapter)}


@router.post("/books/{book}/director")
def open_book_director(book: str) -> dict[str, str]:
    _book_dir(book)
    try:
        open_talk(role="总导演", book=book, chapter=None)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"总导演启动失败：{exc}") from exc
    return {"message": "总导演已打开；以后再点会续接同一段对话"}


def _zebian_book_title(book_dir: Path) -> str:
    try:
        metadata = json.loads((book_dir / "book.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metadata = {}
    return str(metadata.get("display_name") or metadata.get("title") or book_dir.name)


def _zebian_opening_prompt(book_title: str, book_dir: Path) -> str:
    return (
        f"我们在写《{book_title}》。请使用 zebian skill 担任本书责编。"
        f"本书唯一目录是 {book_dir}，先读取作者已经存进设定集的内容，再和作者继续讨论；"
        "已带书名，不要再问写哪本。每轮回复的第一句都先复述“我们在写《"
        f"{book_title}》。”。"
    )


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _zebian_launch_command(
    launcher: Path, session_id: str, opening_prompt: str, project_root: Path,
) -> tuple[list[str], int]:
    terminal = shutil.which("wt.exe")
    if terminal:
        script = "& " + " ".join(
            _powershell_quote(value)
            for value in (str(launcher), "--session-id", session_id, opening_prompt)
        )
        return (
            [
                terminal,
                "-w",
                "new",
                "nt",
                "--title",
                "笔驭 · 责编",
                "-d",
                str(project_root),
                "powershell.exe",
                "-NoLogo",
                "-NoExit",
                "-Command",
                script,
            ],
            0,
        )
    return (
        [
            "cmd.exe",
            "/d",
            "/c",
            str(launcher),
            "--session-id",
            session_id,
            opening_prompt,
        ],
        getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )


@router.post("/books/{book}/zebian")
def open_zebian(book: str, request: Request) -> dict[str, str]:
    """Open the editor skill in a fresh Claude Code conversation."""
    book_dir = _book_dir(book)
    try:
        port = request.url.port
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="责编拉起来源端口无法识别，拒绝启动。") from exc
    if port not in {8080, 8090}:
        raise HTTPException(status_code=400, detail="责编拉起来源端口无效，只接受 8080 或 8090。")
    data_root = get_data_root().resolve()
    settings_url = f"{request.url.scheme}://127.0.0.1:{port}/api/settings/editor"
    book_title = _zebian_book_title(book_dir)
    opening_prompt = _zebian_opening_prompt(book_title, book_dir)
    launcher = _bookroom_bat()
    if not launcher.exists():
        raise HTTPException(
            status_code=500,
            detail={
                "message": f"责编没有启动：未找到 {launcher}",
                "opening_prompt": opening_prompt,
            },
        )
    env = os.environ.copy()
    env["BIYU_TRACK"] = "creative"
    env["BIYU_SETTINGS_EDITOR_URL"] = settings_url
    env["BIYU_SETTINGS_DATA_ROOT"] = str(data_root)
    env["BIYU_RUNTIME_ROLE"] = "test" if port == 8090 else "production"
    project_root = get_project_root()
    # A launcher-provided checkout root is authoritative. When the service is
    # started directly from an installed environment, use that interpreter's
    # virtual environment instead of guessing from site-packages parents.
    venv_scripts = project_root / ".venv" / "Scripts" if os.environ.get("BIYU_PROJECT_ROOT") else Path(sys.executable).resolve().parent
    biyu_executable = venv_scripts / "biyu.exe"
    if not biyu_executable.is_file():
        raise HTTPException(
            status_code=500,
            detail={
                "message": f"责编没有启动：未找到可执行命令 {biyu_executable}",
                "opening_prompt": opening_prompt,
            },
        )
    env["PATH"] = str(venv_scripts) + os.pathsep + env.get("PATH", "")
    command, creationflags = _zebian_launch_command(
        launcher, str(uuid4()), opening_prompt, project_root,
    )
    try:
        subprocess.Popen(
            command,
            cwd=str(project_root),
            env=env,
            creationflags=creationflags,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "message": f"责编没有启动：{exc}",
                "opening_prompt": opening_prompt,
            },
        ) from exc
    return {
        "message": f"《{book_title}》责编已打开；每次都是新对话。",
        "opening_prompt": opening_prompt,
    }


@router.post("/books/{book}/chapters/{chapter}/architect")
async def run_web_architect(book: str, chapter: int) -> StreamingResponse:
    """Run the in-pipeline Architect only; chapter Claude Code is retired."""
    book_dir = _book_dir(book)
    key = (book_dir.name, chapter)
    if not _web_architect_enabled():
        raise HTTPException(status_code=404, detail="网页导演功能尚未开启")
    if key in _WEB_ARCHITECT_RUNS:
        raise HTTPException(status_code=409, detail="导演正在写这一章的方案")

    queue: asyncio.Queue = asyncio.Queue()

    async def produce() -> None:
        started = time.time()
        _WEB_ARCHITECT_RUNS[key] = {"started_at": started}
        await queue.put({"type": "started", "message": "导演正在写这一章的方案"})
        await queue.put({"type": "progress", "message": "读细纲、世界观、人物卡"})
        try:
            result = await generate_planning_with_architect(book, chapter)
            if result["state"] == "rejected":
                await queue.put({"type": "rejected", **result})
            else:
                await queue.put({"type": "done", **result})
        except Exception as exc:
            await queue.put({"type": "error", "message": str(exc) or "导演没有写完，盘上方案未改变"})
        finally:
            _WEB_ARCHITECT_RUNS.pop(key, None)
            await queue.put(None)

    asyncio.create_task(produce())
    return StreamingResponse(sse_generator(queue), media_type="text/event-stream")


def _guard_version(path: Path, base_sha: str | None) -> None:
    if base_sha and _sha(_read(path)) != base_sha:
        raise HTTPException(status_code=409, detail="盘面已有更新；请先载入最新版或对照差异，当前修改尚未覆盖任何内容")


def _commit_official_edit(path: Path, chapter: int) -> None:
    """Commit only the official chapter, never adjacent reports or staged owner assets."""
    from biyu.git_helper import repo_root_for_book

    root = repo_root_for_book(path.parent.parent)
    relative = path.resolve().relative_to(root).as_posix()
    add = subprocess.run(["git", "add", "--", str(relative)], cwd=root, capture_output=True, text=True, encoding="utf-8")
    if add.returncode:
        raise RuntimeError(add.stderr.strip() or "git add failed")
    commit = subprocess.run(
        ["git", "commit", "--only", "-m", f"manual: CH{chapter} 作者在工作台直接修改正式正文", "--", str(relative)],
        cwd=root, capture_output=True, text=True, encoding="utf-8",
    )
    if commit.returncode:
        raise RuntimeError(commit.stderr.strip() or "git commit failed")


@router.put("/books/{book}/chapters/{chapter}/outline")
def save_outline(book: str, chapter: int, payload: dict[str, Any]) -> dict[str, Any]:
    book_dir = _book_dir(book)
    path = book_dir / "outlines" / f"ch{chapter}.md"
    sync_outline_version(book_dir, chapter)
    _guard_version(path, payload.get("base_sha"))
    if path.exists():
        save_outline_version(book_dir, chapter, path.read_text(encoding="utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload.get("content", ""), encoding="utf-8")
    save_outline_version(book_dir, chapter, path.read_text(encoding="utf-8"))
    write_workbench_step(book_dir, chapter, "planning")
    return chapter_snapshot(book_dir, chapter, book)


@router.get("/books/{book}/chapters/{chapter}/outline-template")
def outline_template(book: str, chapter: int) -> dict[str, str]:
    book_dir = _book_dir(book)
    outline = book_dir / "outlines" / f"ch{chapter}.md"
    if outline.exists():
        raise HTTPException(status_code=409, detail="\u672c\u7ae0\u5df2\u6709\u7ec6\u7eb2\uff1b\u4e3a\u4fdd\u62a4\u539f\u7a3f\uff0c\u6a21\u677f\u4e0d\u4f1a\u8986\u76d6\u3002")
    if not OUTLINE_TEMPLATE.exists():
        raise HTTPException(status_code=500, detail="\u7ec6\u7eb2\u6a21\u677f\u672a\u5b89\u88c5\uff1b\u8bf7\u8054\u7cfb\u7ef4\u62a4\u8005\u3002")
    return {"content": OUTLINE_TEMPLATE.read_text(encoding="utf-8")}


@router.put("/books/{book}/chapters/{chapter}/planning")
def save_planning_body(book: str, chapter: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Save director or author planning with one status contract and provenance."""
    book_dir = _book_dir(book)
    path = book_dir / "logs" / f"ch{chapter}" / "planning.md"
    draft_path = _planning_draft_path(book_dir, chapter)
    outline = book_dir / "outlines" / f"ch{chapter}.md"
    if not outline.exists() and not path.exists():
        raise HTTPException(status_code=409, detail="先保存本章细纲，再写方案")
    approved_active = _planning_status(_read(path)) == "已批"
    editing_path = draft_path if approved_active or draft_path.exists() else path
    existing = editing_path.read_text(encoding="utf-8") if editing_path.exists() else _read(path)
    _guard_version(editing_path if editing_path.exists() else path, payload.get("base_sha"))
    pending = book_dir / "chapters" / "_pending" / f"ch{chapter}.md"
    candidate_choice = str(payload.get("candidate_choice") or "")
    if payload.get("confirm") and pending.exists() and candidate_choice not in {"continue", "regenerate"}:
        raise HTTPException(status_code=409, detail="已有候选稿：请选择继续修改现有候选稿，或归档后按新方案重新生成")
    new_body = _planning_body(str(payload.get("content", "")))
    if not new_body.strip():
        raise HTTPException(status_code=409, detail="方案还是空的，请先写下方案内容")
    old_body = _planning_body(existing)
    old_source = _planning_source(existing)
    if not existing:
        source = "作者手写"
    elif new_body != old_body:
        source = "作者手写" if old_source == "作者手写" else "作者改过"
    else:
        source = old_source
    if payload.get("confirm"):
        from biyu.checklist.parser import ChecklistMissingError, parse_checklist

        try:
            checklist = parse_checklist(new_body)
        except ChecklistMissingError as exc:
            raise HTTPException(status_code=409, detail=f"方案不能确认：{exc}") from exc
        labels = {
            "must_happen": "必须发生", "must_not_happen": "必须不发生",
            "ending_state": "结尾状态", "info_layers": "信息层级",
        }
        missing = [
            labels[name] for name in labels
            if name in checklist.missing_category or not getattr(checklist, name)
        ]
        if missing:
            raise HTTPException(status_code=409, detail=f"方案不能确认：必检项缺少 {'、'.join(missing)}")
    status = "已批" if payload.get("confirm") else ("待批" if new_body != old_body or not existing else _planning_status(existing))
    saved_text = f"status: {status}\nsource: {source}\n{new_body}"
    destination = path if payload.get("confirm") else editing_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(saved_text, encoding="utf-8")
    if payload.get("confirm"):
        draft_path.unlink(missing_ok=True)
    # 作者保存或确认后，机器拦下态已经由人处理，不再继续遮住当前方案。
    _write_architect_state(book_dir, chapter, {"state": "idle", "missing_labels": []})
    if payload.get("confirm") and pending.exists() and candidate_choice == "regenerate":
        archive_dir = book_dir / "logs" / f"ch{chapter}" / "archived_candidates"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive = archive_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_sha(_read(pending))[:12]}.md"
        try:
            pending.replace(archive)
            mark_current_candidate_archived(book_dir, chapter)
        except OSError:
            path.write_text(existing, encoding="utf-8")
            raise HTTPException(status_code=500, detail="候选稿归档失败；方案和候选稿均保持原样")
    if payload.get("confirm"):
        save_plan_version(book_dir, chapter, f"source: {source}\n{new_body}")
    if payload.get("confirm") or not approved_active:
        write_workbench_step(book_dir, chapter, "generation" if payload.get("confirm") else "planning")
    return chapter_snapshot(book_dir, chapter, book)


@router.post("/books/{book}/chapters/{chapter}/plans/{version}/select")
def choose_plan_version(book: str, chapter: int, version: int) -> dict[str, Any]:
    book_dir = _book_dir(book)
    try:
        select_plan_version(book_dir, chapter, version)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _planning_draft_path(book_dir, chapter).unlink(missing_ok=True)
    _write_architect_state(book_dir, chapter, {"state": "idle", "missing_labels": []})
    write_workbench_step(book_dir, chapter, "generation")
    return chapter_snapshot(book_dir, chapter, book)


@router.post("/books/{book}/chapters/{chapter}/outlines/{version}/select")
def choose_outline_version(book: str, chapter: int, version: int) -> dict[str, Any]:
    book_dir = _book_dir(book)
    try:
        select_outline_version(book_dir, chapter, version)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    write_workbench_step(book_dir, chapter, "planning")
    return chapter_snapshot(book_dir, chapter, book)


@router.post("/books/{book}/chapters/{chapter}/candidates/{version}/select")
def choose_candidate_version(book: str, chapter: int, version: int) -> dict[str, Any]:
    book_dir = _book_dir(book)
    try:
        select_candidate_version(book_dir, chapter, version)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    write_workbench_step(book_dir, chapter, "reading")
    return chapter_snapshot(book_dir, chapter, book)


@router.post("/books/{book}/chapters/{chapter}/candidate/discard")
def discard_candidate(book: str, chapter: int) -> dict[str, Any]:
    book_dir = _book_dir(book)
    try:
        discard_current_candidate(book_dir, chapter)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    write_workbench_step(book_dir, chapter, "generation")
    return chapter_snapshot(book_dir, chapter, book)


@router.post("/books/{book}/chapters/{chapter}/trash/{entry_id}/restore")
def restore_recycled(book: str, chapter: int, entry_id: str) -> dict[str, Any]:
    book_dir = _book_dir(book)
    restored_kind = ""
    try:
        restored_kind = restore_trash(book_dir, chapter, entry_id)
    except FileNotFoundError:
        try:
            _restore_excerpt(book_dir, entry_id)
            restored_kind = "excerpt"
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if restored_kind == "candidate":
        write_workbench_step(book_dir, chapter, "reading")
    return chapter_snapshot(book_dir, chapter, book)


@router.delete("/books/{book}/chapters/{chapter}/trash/{entry_id}")
def permanently_delete_recycled(book: str, chapter: int, entry_id: str, confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        raise HTTPException(status_code=409, detail="彻底删除前需要再次确认")
    book_dir = _book_dir(book)
    try:
        purge_trash(book_dir, chapter, entry_id)
    except FileNotFoundError:
        try:
            _purge_excerpt(book_dir, entry_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return chapter_snapshot(book_dir, chapter, book)


@router.post("/books/{book}/chapters/{chapter}/diagnosis/route")
def route_diagnosis(book: str, chapter: int, payload: dict[str, Any]) -> dict[str, Any]:
    from biyu.ui.workbench_state import remember_diagnosis_return
    book_dir = _book_dir(book)
    layer = str(payload.get("layer", ""))
    step_by_layer = {"细纲层": "outline", "方案层": "planning", "执笔层": "revision"}
    if layer not in step_by_layer:
        raise HTTPException(status_code=400, detail="诊断层级无效，请重新诊断")
    diagnosis = read_diagnosis(book_dir, chapter)
    if diagnosis.get("layer") != layer:
        raise HTTPException(status_code=409, detail="诊断结果已经变化，请刷新后再分流")
    if not diagnosis_is_fresh(book_dir, chapter, diagnosis):
        raise HTTPException(status_code=409, detail="诊断已过期：候选稿或返修轮次已经变化，请重新诊断")
    remember_diagnosis_return(book_dir, chapter, "reading")
    write_workbench_step(book_dir, chapter, step_by_layer[layer])
    return chapter_snapshot(book_dir, chapter, book)


@router.post("/books/{book}/chapters/{chapter}/diagnosis/restore")
def restore_diagnosis_route(book: str, chapter: int) -> dict[str, Any]:
    from biyu.ui.workbench_state import pop_diagnosis_return

    book_dir = _book_dir(book)
    pop_diagnosis_return(book_dir, chapter)
    return chapter_snapshot(book_dir, chapter, book)


@router.put("/books/{book}/chapters/{chapter}/chapter")
def save_chapter(book: str, chapter: int, payload: dict[str, str]) -> dict[str, Any]:
    book_dir = _book_dir(book)
    pending = book_dir / "chapters" / "_pending" / f"ch{chapter}.md"
    official = book_dir / "chapters" / f"ch{chapter}.md"
    requested_target = payload.get("target") or ("pending" if pending.exists() else "official")
    if pending.exists() and requested_target == "official":
        raise HTTPException(status_code=409, detail="修订轮已有候选稿；正式正文已锁定，请在候选稿上修改")
    if requested_target not in {"pending", "official"}:
        raise HTTPException(status_code=400, detail="正文目标无效，请刷新后重试")
    path = pending if requested_target == "pending" else official
    if not path.exists():
        raise HTTPException(status_code=404, detail="正文还没有生成")
    _guard_version(path, payload.get("base_sha"))
    content = payload.get("content", "")
    if content == _read(path):
        result = chapter_snapshot(book_dir, chapter, book)
        result["save_notice"] = "没有变化，没有新版本"
        return result
    old_sha = _sha(_read(path))
    report_path = book_dir / "audit_reports" / f"ch{chapter}.json"
    review_state, _review_state_error = _read_review_state(book_dir, chapter)
    path.write_text(content, encoding="utf-8")
    if report_path.exists():
        _write_review_state(book_dir, chapter, {
            "candidate_sha": _sha(content),
            "editor_base_sha": str(review_state.get("editor_base_sha") or old_sha),
        })
    if requested_target == "official":
        try:
            path.relative_to(get_project_root())
            _commit_official_edit(path, chapter)
        except ValueError:
            pass  # isolated tests/out-of-repository consumers have no git contract
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=f"正文已保存，但自动留版本失败：{exc}") from exc
    return chapter_snapshot(book_dir, chapter, book)


@router.put("/books/{book}/chapters/{chapter}/annotations")
def save_annotations(book: str, chapter: int, payload: dict[str, Any]) -> dict[str, Any]:
    book_dir = _book_dir(book)
    pending = book_dir / "chapters" / "_pending" / f"ch{chapter}.md"
    if not pending.exists():
        raise HTTPException(status_code=409, detail="没有候选稿，当前没有可提交的修订批注")
    if payload.get("candidate_sha") != _sha(_read(pending)):
        raise HTTPException(status_code=409, detail="候选稿已有新版本；你的批注尚未覆盖，请刷新后核对")
    report_path = book_dir / "audit_reports" / f"ch{chapter}.json"
    try:
        data = json.loads(_read(report_path) or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=409, detail="审读报告无法读取，请重新审读后再批注") from exc
    previous_annotations = data.get("workbench_annotations", {})
    data["workbench_annotations"] = {
        str(item.get("id")): {
            **(
                previous_annotations.get(str(item.get("id")), {})
                if isinstance(previous_annotations, dict) else {}
            ),
            "selected": bool(item.get("selected", False)),
            "author_comment": str(item.get("author_comment", "")).strip(),
        }
        for item in payload.get("issues", []) if item.get("id")
    }
    data["workbench_general_comment"] = str(payload.get("general_comment", "")).strip()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return chapter_snapshot(book_dir, chapter, book)


@router.post("/books/{book}/chapters/{chapter}/revision-package")
def build_revision_package(book: str, chapter: int, payload: dict[str, Any]) -> dict[str, str]:
    from biyu.audit_reports.revisions import create_revision_package
    selected_issue_ids = [str(value) for value in payload.get("selected_issue_ids", [])]
    revision_problem_lines = [
        value for value in payload.get("revision_problem_lines", []) if isinstance(value, dict)
    ]
    try:
        _validate_visible_selection(
            selected_issue_ids,
            revision_problem_lines,
            [str(value) for value in payload.get("visible_selected_ids", [])],
        )
        package = create_revision_package(
            _book_dir(book), chapter,
            selected_issue_ids=selected_issue_ids,
            issue_comments={str(key): str(value) for key, value in payload.get("issue_comments", {}).items()},
            general_comment=str(payload.get("general_comment", "")),
            candidate_sha=str(payload.get("candidate_sha", "")),
            sample_problem_ids=[str(value) for value in payload.get("sample_problem_ids", [])],
            revision_problem_ids=[str(value) for value in payload.get("revision_problem_ids", [])],
            revision_problem_lines=revision_problem_lines,
            mode=payload.get("mode"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"package": str(package)}


def _validate_visible_selection(
    selected_issue_ids: list[str],
    revision_problem_lines: list[dict[str, Any]],
    visible_selected_ids: list[str],
) -> None:
    packaged_ids = selected_issue_ids + [
        str(item.get("id", "")) for item in revision_problem_lines if item.get("id")
    ]
    if (
        len(packaged_ids) != len(visible_selected_ids)
        or len(packaged_ids) != len(set(packaged_ids))
        or set(packaged_ids) != set(visible_selected_ids)
    ):
        raise ValueError("返修包与界面可见且勾选的问题不一致，请刷新后重新核对")


@router.post("/books/{book}/chapters/{chapter}/issues/{issue_id}/ignore")
def ignore_issue(book: str, chapter: int, issue_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    book_dir = _book_dir(book)
    pending = book_dir / "chapters" / "_pending" / f"ch{chapter}.md"
    if payload.get("candidate_sha") != _sha(_read(pending)):
        raise HTTPException(status_code=409, detail="候选稿已有新版本；请刷新后再忽略")
    report_path = book_dir / "audit_reports" / f"ch{chapter}.json"
    try:
        data = json.loads(_read(report_path) or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=409, detail="审读报告无法读取") from exc
    annotations = data.setdefault("workbench_annotations", {})
    annotations[issue_id] = {
        **annotations.get(issue_id, {}),
        "ignored": True,
        "ignored_at": datetime.now().isoformat(timespec="seconds"),
        "ignore_note": str(payload.get("note", "")).strip(),
    }
    report_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    history = book_dir / "logs" / f"ch{chapter}" / "revisions" / "ignored.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    with history.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "issue_id": issue_id,
            "candidate_sha": payload.get("candidate_sha"),
            "ignored_at": annotations[issue_id]["ignored_at"],
            "note": annotations[issue_id]["ignore_note"],
        }, ensure_ascii=False) + "\n")
    return chapter_snapshot(book_dir, chapter, book)


@router.delete("/books/{book}/chapters/{chapter}/issues/{issue_id}/ignore")
def unignore_issue(
    book: str, chapter: int, issue_id: str, candidate_sha: str,
) -> dict[str, Any]:
    book_dir = _book_dir(book)
    pending = book_dir / "chapters" / "_pending" / f"ch{chapter}.md"
    if candidate_sha != _sha(_read(pending)):
        raise HTTPException(status_code=409, detail="候选稿已有新版本；请刷新后再取消忽略")
    report_path = book_dir / "audit_reports" / f"ch{chapter}.json"
    try:
        data = json.loads(_read(report_path) or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=409, detail="审读报告无法读取") from exc
    annotations = data.setdefault("workbench_annotations", {})
    note = annotations.get(issue_id)
    if not isinstance(note, dict) or not note.get("ignored"):
        raise HTTPException(status_code=409, detail="这条意见当前没有被忽略")
    restored_at = datetime.now().isoformat(timespec="seconds")
    annotations[issue_id] = {
        **note,
        "ignored": False,
        "unignored_at": restored_at,
    }
    report_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    history = book_dir / "logs" / f"ch{chapter}" / "revisions" / "ignored.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    with history.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "issue_id": issue_id,
            "candidate_sha": candidate_sha,
            "unignored_at": restored_at,
            "action": "unignore",
        }, ensure_ascii=False) + "\n")
    return chapter_snapshot(book_dir, chapter, book)


@router.post("/books/{book}/chapters/{chapter}/actions/{action_id}")
async def run_action(book: str, chapter: int, action_id: str, payload: dict[str, Any]) -> StreamingResponse:
    """Buttons only select an argv registry row; CLI owns all action semantics."""
    if action_id == "talk":
        raise HTTPException(status_code=410, detail="本章导演网页旧入口已退役；请使用‘让导演写方案’。")

    async def produce(queue: asyncio.Queue) -> None:
        try:
            async for event in execute(action_id, book=book, chapter=chapter, confirmed=bool(payload.get("confirmed", False)), extra={key: str(value) for key, value in payload.items()}):
                await queue.put(event)
        except KeyError:
            await queue.put({"type": "error", "message": f"\u672a\u77e5\u52a8\u4f5c: {action_id}"})
        finally:
            await queue.put(None)

    queue: asyncio.Queue = asyncio.Queue()
    asyncio.create_task(produce(queue))
    return StreamingResponse(sse_generator(queue), media_type="text/event-stream")
    list_outline_versions,
    select_outline_version,
