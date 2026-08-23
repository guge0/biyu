"""Default-off settings collection API with cell-scoped safe writes."""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from biyu.config import feature_enabled
from biyu.setup_asset_versions import (
    SetupAssetYamlError,
    setup_asset_path,
    update_book_outline_text,
    update_character_card,
    update_character_fields,
    update_north_star_text,
    update_worldbook_section,
)
from biyu.ui.workbench import _book_dir


router = APIRouter(prefix="/api/settings", tags=["settings"])
_now_seconds = time.time

WORLD_CELLS: dict[str, tuple[str, str, str]] = {
    "world_narrative_anchors": ("narrative_anchors", "创作锚点", "mapping"),
    "world_facts": ("facts", "不可变硬设定", "list"),
    "world_power_system": ("power_system", "力量·修炼体系", "mapping"),
    "world_forbidden": ("forbidden", "绝对禁止", "list"),
    "world_geography": ("geography", "地理", "list"),
    "world_factions": ("factions", "势力", "list"),
    "world_timeline": ("timeline", "时间线锚点", "list"),
}


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    content: str | None = None
    fields: dict[str, Any] | None = None


class VersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str


class CreateCharacterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: dict[str, Any] | None = None


def _enabled() -> None:
    if not feature_enabled("settings_page"):
        raise HTTPException(status_code=404, detail="设定集尚未开启。")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes() if path.exists() else b"").hexdigest()


def _parse_sections(content: str) -> list[dict[str, str]]:
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", content))
    if not matches:
        raise HTTPException(
            status_code=400,
            detail="这一块切不开，没有保存。请切回编辑加标题，或分开粘。",
        )
    sections: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        body = content[match.end():end].strip()
        sections.append({"title": match.group(1).strip(), "content": body, "length": len(body)})
    return sections


def _world_document(book_dir: Path) -> dict[str, Any]:
    path = setup_asset_path(book_dir, "worldbook")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    except yaml.YAMLError as exc:
        raise SetupAssetYamlError("世界观的写法有误，本次没有保存。") from exc
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SetupAssetYamlError("世界观最外层必须按字段组织，本次没有保存。")
    return value


def _world_content(value: Any, shape: str) -> str:
    def render(item: Any) -> str:
        return yaml.safe_dump(item, allow_unicode=True, sort_keys=False).strip()

    if shape == "mapping":
        if not isinstance(value, dict):
            return ""
        return "\n\n".join(f"## {key}\n{render(item)}" for key, item in value.items())
    if not isinstance(value, list):
        return ""
    return "\n\n".join(f"## 条目 {index}\n{render(item)}" for index, item in enumerate(value, 1))


def _characters(book_dir: Path) -> list[dict[str, Any]]:
    path = setup_asset_path(book_dir, "characters")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    except yaml.YAMLError as exc:
        raise SetupAssetYamlError("人物卡的写法有误，本次没有保存。") from exc
    cards = value.get("characters", []) if isinstance(value, dict) else []
    return [dict(card) for card in cards if isinstance(card, dict) and str(card.get("name") or "").strip()]


def _history_path(book_dir: Path, cell_id: str) -> Path:
    safe = hashlib.sha256(cell_id.encode("utf-8")).hexdigest()[:20]
    return book_dir / "logs" / "settings_history" / f"{safe}.json"


def _history(book_dir: Path, cell_id: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(_history_path(book_dir, cell_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _record_history(book_dir: Path, cell_id: str, content: str, *, actor: str = "未记录") -> None:
    path = _history_path(book_dir, cell_id)
    items = _history(book_dir, cell_id)
    now = _now_seconds()
    item = {"saved_at": now, "content": content, "actor": actor}
    if items and now - float(items[0].get("saved_at", 0)) <= 120:
        items[0]["saved_at"] = now
        items[0]["actor"] = actor
    else:
        items.insert(0, item)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _cell(book_dir: Path, cell_id: str) -> dict[str, Any]:
    if cell_id == "north_star":
        path = setup_asset_path(book_dir, "north_star")
        label, content = "北极星", path.read_text(encoding="utf-8") if path.exists() else ""
    elif cell_id == "book_outline":
        path = setup_asset_path(book_dir, "book_outline")
        label, content = "大纲", path.read_text(encoding="utf-8") if path.exists() else ""
    elif cell_id in WORLD_CELLS:
        section, label, shape = WORLD_CELLS[cell_id]
        path = setup_asset_path(book_dir, "worldbook")
        content = _world_content(_world_document(book_dir).get(section), shape)
    else:
        raise HTTPException(status_code=404, detail="没有这一个设定格。")
    history = _history(book_dir, cell_id)
    return {
        "id": cell_id,
        "label": label,
        "content": content,
        "length": len(content),
        "version": _sha(path),
        "history": history[:5],
        "older_history": history[5:],
        "older_count": max(0, len(history) - 5),
    }


def _character_cell(book_dir: Path, name: str) -> dict[str, Any]:
    card = next((card for card in _characters(book_dir) if str(card.get("name")) == name), None)
    if card is None:
        raise HTTPException(status_code=404, detail=f"没有找到人物“{name}”。")
    path = setup_asset_path(book_dir, "characters")
    content = "## 人物卡\n" + yaml.safe_dump(card, allow_unicode=True, sort_keys=False).strip()
    aliases = card.get("aliases") if isinstance(card.get("aliases"), dict) else {}
    raw_voice_examples = card.get("voice_examples")
    voice_examples = (
        [raw_voice_examples]
        if isinstance(raw_voice_examples, str)
        else list(raw_voice_examples or [])
    )
    sections = {
        "基础": {
            "name": str(card.get("name") or ""),
            "tier": str(card.get("tier") or "supporting"),
            "role": str(card.get("role") or ""),
        },
        "背景": str(card.get("background") or ""),
        "性格": str(card.get("personality") or ""),
        "称谓": {
            "叙述者怎么称呼他": str(aliases.get("narrator_default") or ""),
            "他怎么自称": str(aliases.get("self_referent") or ""),
            "别人怎么叫他": dict(aliases.get("called_by") or {}) if isinstance(aliases.get("called_by"), dict) else {},
            "正文里不许用的称呼": list(card.get("forbidden_in_narrative") or []),
        },
        "语声样本": voice_examples,
    }
    state_keys = ("status", "current_location", "current_emotional_state", "current_power_level")
    state = {key: card.get(key) for key in state_keys if key in card}
    mapped = {"name", "tier", "role", "background", "personality", "aliases", "forbidden_in_narrative", "voice_examples", *state_keys, "archived", "tier_history"}
    other = {key: value for key, value in card.items() if key not in mapped}
    history = _history(book_dir, f"character:{name}")
    def editable_length(value: Any) -> int:
        if isinstance(value, dict):
            return sum(editable_length(item) for item in value.values())
        if isinstance(value, list):
            return sum(editable_length(item) for item in value)
        return len(str(value or ""))

    display_length = sum(editable_length(value) for value in (
        sections["基础"].get("role"), sections["背景"], sections["性格"],
        aliases.get("narrator_default"), aliases.get("self_referent"),
        aliases.get("called_by"), sections["称谓"].get("正文里不许用的称呼"),
        sections["语声样本"],
    ))
    return {
        **card,
        "content": content,
        "sections": sections,
        "state": state,
        "other": other,
        "other_count": len(other),
        "display_length": display_length,
        "last_saved_at": history[0].get("saved_at") if history else None,
        "version": _sha(path),
        "history": history[:5],
        "older_history": history[5:],
        "older_count": max(0, len(history) - 5),
    }


@router.get("/status")
def settings_status() -> dict[str, bool]:
    return {"enabled": feature_enabled("settings_page")}


@router.get("/books/{book}")
def settings_snapshot(book: str) -> dict[str, Any]:
    return _settings_snapshot(book)


def _settings_snapshot(book: str, *, include_data_root: bool = False) -> dict[str, Any]:
    _enabled()
    book_dir = _book_dir(book)
    cells = [_cell(book_dir, "north_star"), _cell(book_dir, "book_outline")]
    cells.extend(_cell(book_dir, cell_id) for cell_id in WORLD_CELLS)
    characters = [_character_cell(book_dir, str(card["name"])) for card in _characters(book_dir)]
    meta_path = book_dir / "book.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    result = {
        "book": {"title": meta.get("display_name") or meta.get("title") or book_dir.name},
        "cells": cells,
        "characters": characters,
    }
    if include_data_root:
        result["data_root"] = str(book_dir.parent)
        result["character_version"] = _sha(setup_asset_path(book_dir, "characters"))
    return result


def settings_completion(book_dir: Path) -> dict[str, int | bool]:
    """Return the nine core-cell completion state without creating history."""
    cells = [_cell(book_dir, "north_star"), _cell(book_dir, "book_outline")]
    cells.extend(_cell(book_dir, cell_id) for cell_id in WORLD_CELLS)
    filled = sum(bool(str(cell["content"]).strip()) for cell in cells)
    required = len(cells)
    return {
        "settings_filled_count": filled,
        "settings_required_count": required,
        "settings_ready": filled == required,
    }


@router.get("/editor/books/{book}")
def editor_settings_snapshot(book: str) -> dict[str, Any]:
    return _settings_snapshot(book, include_data_root=True)


@router.put("/books/{book}/cells/{cell_id}")
def save_cell(book: str, cell_id: str, request: SaveRequest) -> dict[str, Any]:
    return _save_cell(book, cell_id, request, actor="作者")


def _save_cell(book: str, cell_id: str, request: SaveRequest, *, actor: str) -> dict[str, Any]:
    _enabled()
    book_dir = _book_dir(book)
    current = _cell(book_dir, cell_id)
    if request.version != current["version"]:
        raise HTTPException(status_code=409, detail="这格在你打开后已经被改过。请重新读取，默认没有覆盖。")
    _parse_sections(request.content)
    previous_content = current["content"]
    try:
        if cell_id == "north_star":
            update_north_star_text(book_dir, request.content, actor=actor)
        elif cell_id == "book_outline":
            update_book_outline_text(book_dir, request.content, actor=actor)
        elif cell_id in WORLD_CELLS:
            section, _label, shape = WORLD_CELLS[cell_id]
            sections = _parse_sections(request.content)
            try:
                parsed = [yaml.safe_load(item["content"]) for item in sections]
            except yaml.YAMLError as exc:
                raise HTTPException(status_code=400, detail="这一格里的结构无法识别，本次没有保存。") from exc
            value: Any = (
                {item["title"]: parsed[index] for index, item in enumerate(sections)}
                if shape == "mapping" else parsed
            )
            update_worldbook_section(book_dir, section, value, actor=actor)
        else:
            raise HTTPException(status_code=404, detail="没有这一个设定格。")
    except SetupAssetYamlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _record_history(book_dir, cell_id, previous_content, actor=actor)
    return {"status": "ok", "cell": _cell(book_dir, cell_id)}


@router.put("/editor/books/{book}/cells/{cell_id}")
def editor_save_cell(book: str, cell_id: str, request: SaveRequest) -> dict[str, Any]:
    return _save_cell(book, cell_id, request, actor="责编")


@router.post("/books/{book}/cells/{cell_id}/history/{index}/restore")
def restore_cell_history(book: str, cell_id: str, index: int, request: VersionRequest) -> dict[str, Any]:
    _enabled()
    book_dir = _book_dir(book)
    current = _cell(book_dir, cell_id)
    if request.version != current["version"]:
        raise HTTPException(status_code=409, detail="这格在你打开后已经被改过。请重新读取，默认没有覆盖。")
    history = _history(book_dir, cell_id)
    if index < 0 or index >= len(history):
        raise HTTPException(status_code=404, detail="这一版历史不存在。")
    content = str(history[index].get("content") or "")
    # Reuse the exact same cell save contract; this snapshots the current bytes
    # before restoring and keeps sibling worldbook fields untouched.
    result = _save_cell(
        book, cell_id, SaveRequest(version=request.version, content=content), actor="作者",
    )
    return {"status": "ok", "cell": result["cell"]}


@router.put("/books/{book}/characters/{name}")
def save_character(book: str, name: str, request: SaveRequest) -> dict[str, Any]:
    return _save_character(book, name, request, actor="作者")


@router.post("/books/{book}/characters")
def create_character(book: str, request: CreateCharacterRequest) -> dict[str, Any]:
    """Explicit author create action; updating an unknown name must not create a card."""
    _enabled()
    book_dir = _book_dir(book)
    fields = request.fields if isinstance(request.fields, dict) else {}
    base = fields.get("基础") if isinstance(fields.get("基础"), dict) else {}
    name = str(base.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请先填写人物姓名。")
    if any(str(card.get("name") or "").strip() == name for card in _characters(book_dir)):
        raise HTTPException(status_code=409, detail="已经有同名人物卡了，请换一个姓名。")
    patch = _character_fields_to_patch(fields, name)
    update_character_card(book_dir, patch, original_name=None, reason="settings_character_create", actor="作者")
    return {"status": "ok", "character": _character_cell(book_dir, name)}


def _save_character(
    book: str, name: str, request: SaveRequest, *, actor: str, allow_create: bool = False,
) -> dict[str, Any]:
    _enabled()
    book_dir = _book_dir(book)
    decoded = unquote(name)
    try:
        current = _character_cell(book_dir, decoded)
        original_name: str | None = decoded
    except HTTPException as exc:
        if not allow_create or exc.status_code != 404:
            raise
        path = setup_asset_path(book_dir, "characters")
        current = {"version": _sha(path), "content": ""}
        original_name = None
    if request.version != current["version"]:
        raise HTTPException(status_code=409, detail="这张人物卡在你打开后已经被改过。请重新读取。")
    if request.fields is not None:
        patch = _character_fields_to_patch(request.fields, decoded)
        if request.fields == current.get("sections"):
            return {"status": "ok", "character": current}
        raw_card = next(
            (card for card in _characters(book_dir) if str(card.get("name")) == decoded),
            None,
        )
        value = dict(raw_card or {})
        value["name"] = patch["name"]
        for key in ("tier", "role", "background", "personality", "forbidden_in_narrative", "voice_examples"):
            value[key] = patch[key]
        if (
            isinstance(value.get("voice_examples"), list)
            and isinstance((raw_card or {}).get("voice_examples"), str)
            and value["voice_examples"] == [(raw_card or {})["voice_examples"]]
        ):
            value["voice_examples"] = (raw_card or {})["voice_examples"]
        aliases = dict(value.get("aliases") or {})
        aliases.update(patch["aliases"])
        value["aliases"] = aliases
    else:
        if request.content is None:
            raise HTTPException(status_code=400, detail="人物卡没有可保存的内容。")
        sections = _parse_sections(request.content)
        try:
            value = yaml.safe_load(sections[0]["content"])
        except yaml.YAMLError as exc:
            raise HTTPException(status_code=400, detail="人物卡内容无法识别，本次没有保存。") from exc
        if not isinstance(value, dict) or str(value.get("name") or "") != decoded:
            raise HTTPException(status_code=400, detail="人物卡必须保留原姓名，本次没有保存。")
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="人物卡内容无法识别，本次没有保存。")
    if request.fields is not None:
        unchanged = value == raw_card
        if unchanged:
            return {"status": "ok", "character": _character_cell(book_dir, decoded)}
    previous_content = current["content"]
    update_character_card(
        book_dir, value, original_name=original_name, reason="settings_character_write", actor=actor,
    )
    _record_history(book_dir, f"character:{decoded}", previous_content, actor=actor)
    return {"status": "ok", "character": _character_cell(book_dir, decoded)}


def _character_fields_to_patch(fields: dict[str, Any], name: str) -> dict[str, Any]:
    """Translate the five author-facing sections into a minimal card patch."""
    allowed_sections = {"基础", "背景", "性格", "称谓", "语声样本"}
    if set(fields) - allowed_sections:
        raise HTTPException(status_code=400, detail="人物卡只能保存五段中文内容，本次没有保存。")
    base = fields.get("基础") if isinstance(fields.get("基础"), dict) else {}
    if str(base.get("name") or name) != name:
        raise HTTPException(status_code=400, detail="人物姓名暂不支持修改，本次没有保存。")
    aliases = fields.get("称谓") if isinstance(fields.get("称谓"), dict) else {}
    called_by = aliases.get("别人怎么叫他", {})
    forbidden = aliases.get("正文里不许用的称呼", [])
    if not isinstance(called_by, dict) or not isinstance(forbidden, list):
        raise HTTPException(status_code=400, detail="称谓内容格式不正确，本次没有保存。")
    voice_examples = fields.get("语声样本") or []
    if isinstance(voice_examples, str):
        voice_examples = [voice_examples]
    if not isinstance(voice_examples, list):
        raise HTTPException(status_code=400, detail="语声样本格式不正确，本次没有保存。")
    return {
        "name": name,
        "tier": str(base.get("tier") or "supporting"),
        "role": str(base.get("role") or ""),
        "background": str(fields.get("背景") or ""),
        "personality": str(fields.get("性格") or ""),
        "aliases": {
            "narrator_default": str(aliases.get("叙述者怎么称呼他") or ""),
            "self_referent": str(aliases.get("他怎么自称") or ""),
            "called_by": called_by,
        },
        "forbidden_in_narrative": forbidden,
        "voice_examples": voice_examples,
    }


@router.put("/editor/books/{book}/characters/{name}")
def editor_save_character(book: str, name: str, request: SaveRequest) -> dict[str, Any]:
    return _save_character(book, name, request, actor="责编", allow_create=True)


@router.post("/books/{book}/characters/{name}/history/{index}/restore")
def restore_character_history(
    book: str, name: str, index: int, request: VersionRequest,
) -> dict[str, Any]:
    _enabled()
    book_dir = _book_dir(book)
    decoded = unquote(name)
    current = _character_cell(book_dir, decoded)
    if request.version != current["version"]:
        raise HTTPException(status_code=409, detail="这张人物卡在你打开后已经被改过。请重新读取。")
    history = _history(book_dir, f"character:{decoded}")
    if index < 0 or index >= len(history):
        raise HTTPException(status_code=404, detail="这一版历史不存在。")
    content = str(history[index].get("content") or "")
    result = _save_character(
        book, decoded, SaveRequest(version=request.version, content=content), actor="作者",
    )
    return {"status": "ok", "character": result["character"]}


@router.post("/books/{book}/characters/{name}/archive")
def archive_character(book: str, name: str, request: VersionRequest) -> dict[str, Any]:
    return _archive_character(book, name, request, actor="作者")


@router.post("/books/{book}/characters/{name}/restore")
def restore_character(book: str, name: str, request: VersionRequest) -> dict[str, Any]:
    return _restore_character(book, name, request, actor="作者")


def _archive_character(book: str, name: str, request: VersionRequest, *, actor: str) -> dict[str, Any]:
    _enabled()
    book_dir = _book_dir(book)
    decoded = unquote(name)
    current = _character_cell(book_dir, decoded)
    if request.version != current["version"]:
        raise HTTPException(status_code=409, detail="这张人物卡在你打开后已经被改过。请重新读取。")
    previous_content = current["content"]
    update_character_fields(
        book_dir, decoded, {"archived": True}, reason="settings_character_archive", actor=actor,
    )
    _record_history(book_dir, f"character:{decoded}", previous_content, actor=actor)
    return {"status": "ok", "character": _character_cell(book_dir, decoded)}


def _restore_character(book: str, name: str, request: VersionRequest, *, actor: str) -> dict[str, Any]:
    _enabled()
    book_dir = _book_dir(book)
    decoded = unquote(name)
    current = _character_cell(book_dir, decoded)
    if request.version != current["version"]:
        raise HTTPException(status_code=409, detail="这张人物卡在你打开后已经被改过。请重新读取。")
    previous_content = current["content"]
    update_character_fields(
        book_dir, decoded, {"archived": False}, reason="settings_character_restore", actor=actor,
    )
    _record_history(book_dir, f"character:{decoded}", previous_content, actor=actor)
    return {"status": "ok", "character": _character_cell(book_dir, decoded)}


@router.post("/editor/books/{book}/characters/{name}/archive")
def editor_archive_character(book: str, name: str, request: VersionRequest) -> dict[str, Any]:
    return _archive_character(book, name, request, actor="责编")
