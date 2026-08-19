"""Voiceprint profile storage, compatibility loading, and deterministic merge."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from biyu.fingerprint.merge_policy import (
    SYSTEM_USAGE_POLICY,
    canonical_dimension,
    is_effective_line,
)
from biyu.fingerprint.profile_state import load_profile_state, save_profile_state

SELF_ID = "book:self"


def _voice_dir(book_dir: Path) -> Path:
    return Path(book_dir) / "声纹"


def _profile_path(book_dir: Path) -> Path:
    return _voice_dir(book_dir) / "本书自蒸馏.json"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _line_id(dimension: str, text: str) -> str:
    digest = hashlib.sha256(f"{dimension}\0{text}".encode("utf-8")).hexdigest()[:12]
    return f"voice-{digest}"


def _canonical_dimension(dimension: str) -> str:
    return canonical_dimension(dimension)


def _is_effective_line(line: dict) -> bool:
    return is_effective_line(line)


def load_self_profile(book_dir: Path) -> dict:
    path = _profile_path(book_dir)
    if not path.exists():
        return {
            "schema_version": 1,
            "id": SELF_ID,
            "name": "本书自蒸馏",
            "kind": "book",
            "lines": [],
        }
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("lines"), list):
        raise ValueError("本书声纹格式无效")
    return value


def replace_machine_lines(book_dir: Path, lines: list[dict]) -> dict:
    """Replace recomputable lines while preserving every author-owned line."""
    profile = load_self_profile(book_dir)
    author_lines = [
        dict(line) for line in profile["lines"]
        if isinstance(line, dict) and line.get("source") == "author"
    ]
    protected_dimensions = {
        canonical_dimension(str(line.get("dimension", "")))
        for line in author_lines
    }
    machine_lines = []
    for item in lines:
        dimension = str(item.get("dimension", "")).strip()
        text = str(item.get("text", "")).strip()
        if not dimension or not text or canonical_dimension(dimension) in protected_dimensions:
            continue
        machine_line = {
            "id": str(item.get("id") or _line_id(dimension, text)),
            "dimension": dimension,
            "text": text,
            "source": "machine",
        }
        why = str(item.get("why", "")).strip()
        if why:
            machine_line["why"] = why
        machine_lines.append(machine_line)
    profile["lines"] = author_lines + machine_lines
    _write_json(_profile_path(book_dir), profile)
    return profile


def edit_voice_line(
    book_dir: Path,
    line_id: str,
    text: str,
    why: str | None = None,
    profile_id: str | None = None,
) -> dict:
    text = text.strip()
    if not text:
        raise ValueError("声纹片段不能为空")
    candidates = [(_profile_path(book_dir), load_self_profile(book_dir))]
    imported_dir = _voice_dir(book_dir) / "导入作品"
    if imported_dir.exists():
        for path in sorted(imported_dir.glob("*.json")):
            profile = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(profile, dict) and isinstance(profile.get("lines"), list):
                candidates.append((path, profile))
    for directory_name in ("手写", "合并声纹"):
        directory = _voice_dir(book_dir) / directory_name
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            profile = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(profile, dict) and isinstance(profile.get("lines"), list):
                candidates.append((path, profile))
    for path, profile in candidates:
        if profile_id and str(profile.get("id")) != profile_id:
            continue
        for line in profile["lines"]:
            if line.get("id") == line_id:
                line["text"] = text
                if why is not None:
                    line["why"] = why.strip()
                line["source"] = "author"
                # source_ref is deliberately left untouched: ownership and
                # provenance are separate R5-3B fields.
                _write_json(path, profile)
                return line
    # Signed builtins and the legacy compatibility profile are project assets;
    # editing one creates a book-local authored copy instead of mutating them.
    external = list(_load_builtins(_default_builtins_dir()).values())
    legacy = _load_legacy(book_dir)
    if legacy:
        external.append(legacy)
    for profile in external:
        if profile_id and str(profile.get("id")) != profile_id:
            continue
        if not any(line.get("id") == line_id for line in profile.get("lines", [])):
            continue
        copied_lines = [dict(line) for line in profile["lines"]]
        edited = next(line for line in copied_lines if line.get("id") == line_id)
        edited["text"] = text
        if why is not None:
            edited["why"] = why.strip()
        edited["source"] = "author"
        profile_id = f"manual:{uuid.uuid4().hex}"
        copied = {
            "schema_version": 1,
            "id": profile_id,
            "name": f"{profile.get('name') or '声纹'}（我的修改）",
            "kind": "manual",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_profiles": [{
                "id": str(profile.get("id", "")),
                "name": str(profile.get("name", "")),
                "fingerprint": _profile_fingerprint(profile),
            }],
            "lines": copied_lines,
        }
        _write_json(_voice_dir(book_dir) / "手写" / f"{profile_id.removeprefix('manual:')}.json", copied)
        save_profile_state(book_dir, profile_id)
        return edited
    raise KeyError(f"声纹片段不存在: {line_id}")


def save_selection(book_dir: Path, active: str | None) -> dict:
    """Compatibility name for choosing the sole active profile."""
    saved = save_profile_state(book_dir, active)
    return {"active": saved["active"]}


def _load_builtins(builtins_dir: Path) -> dict[str, dict]:
    profiles: dict[str, dict] = {}
    if not builtins_dir.exists():
        return profiles
    for path in sorted(builtins_dir.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and value.get("id") and isinstance(value.get("lines"), list):
            value = dict(value)
            value.setdefault(
                "joined_at",
                datetime.fromtimestamp(
                    path.stat().st_mtime,
                    tz=timezone.utc,
                ).isoformat(),
            )
            profiles[str(value["id"])] = value
    return profiles


def _load_imported(book_dir: Path) -> dict[str, dict]:
    profiles: dict[str, dict] = {}
    imported_dir = _voice_dir(book_dir) / "导入作品"
    if not imported_dir.exists():
        return profiles
    for path in sorted(imported_dir.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if (
            isinstance(value, dict)
            and value.get("id")
            and value.get("kind") == "imported"
            and isinstance(value.get("lines"), list)
        ):
            profiles[str(value["id"])] = value
    return profiles


def _load_local_profiles(book_dir: Path) -> dict[str, dict]:
    profiles: dict[str, dict] = {}
    for directory_name in ("手写", "合并声纹"):
        directory = _voice_dir(book_dir) / directory_name
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and value.get("id") and isinstance(value.get("lines"), list):
                profiles[str(value["id"])] = value
    return profiles


def _load_legacy(book_dir: Path) -> dict | None:
    meta_path = Path(book_dir) / "book.json"
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    raw_path = meta.get("fingerprint_path")
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(book_dir) / path
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    lines = []
    description = str(raw.get("style_description", "")).strip()
    if description:
        lines.append({
            "id": "legacy-style",
            "dimension": "整体风格",
            "text": description,
            "why": "旧声纹对风格气质、情绪落点与叙事节奏的整体说明。",
            "source": "legacy",
        })
    for index, item in enumerate(raw.get("exemplar_passages", []), 1):
        passage = str(item.get("passage", "")).strip()
        if passage:
            lines.append({
                "id": f"legacy-example-{index}",
                "dimension": "代表段落",
                "text": passage,
                "why": str(item.get("why_representative", "")).strip(),
                "source": "legacy",
            })
    for index, item in enumerate(raw.get("ai_pitfalls", []), 1):
        pitfall = str(item.get("pitfall", "")).strip()
        if pitfall:
            lines.append({
                "id": f"legacy-pitfall-{index}",
                "dimension": "写作雷区",
                "text": pitfall,
                "why": str(item.get("why_it_happens", "")).strip(),
                "source": "legacy",
            })
    return {
        "schema_version": 1,
        "id": "legacy:fingerprint_path",
        "name": "现役旧声纹",
        "kind": "legacy",
        "usage_policy": [
            "这是参考，不是硬规则。",
            "不必每句话都对应某个特征，只在合适处让这种气质自然浮现。",
            "学习气质和处理方式，不照搬原文、人物或具体场景。",
        ],
        "lines": lines,
    }


def _default_builtins_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "assets" / "声纹库" / "内置"


def load_catalog(book_dir: Path, builtins_dir: Path | None = None) -> list[dict]:
    builtins = _load_builtins(Path(builtins_dir) if builtins_dir else _default_builtins_dir())
    catalog = list(builtins.values())
    catalog.extend(_load_imported(Path(book_dir)).values())
    catalog.extend(_load_local_profiles(Path(book_dir)).values())
    self_profile = load_self_profile(book_dir)
    if self_profile["lines"]:
        catalog.append(self_profile)
    legacy = _load_legacy(book_dir)
    if legacy:
        catalog.append(legacy)
    return catalog


def _profile_fingerprint(profile: dict) -> str:
    material = {
        key: value for key, value in profile.items()
        if key not in {"sources_stale", "source_status"}
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _with_source_status(catalog: list[dict]) -> list[dict]:
    by_id = {str(item.get("id")): item for item in catalog if item.get("id")}
    result = []
    for profile in catalog:
        item = dict(profile)
        refs = item.get("source_profiles", [])
        if item.get("kind") == "combined" and isinstance(refs, list):
            stale = any(
                not isinstance(ref, dict)
                or str(ref.get("id", "")) not in by_id
                or _profile_fingerprint(by_id[str(ref.get("id"))]) != str(ref.get("fingerprint", ""))
                for ref in refs
            )
            item["sources_stale"] = stale
        result.append(item)
    return result


def load_catalog_with_status(book_dir: Path, builtins_dir: Path | None = None) -> list[dict]:
    return _with_source_status(load_catalog(book_dir, builtins_dir))


def create_manual_profile(book_dir: Path, name: str, lines: list[dict]) -> dict:
    clean_name = str(name).strip() or "手写声纹"
    normalized = []
    for item in lines:
        dimension = str(item.get("dimension", "")).strip()
        text = str(item.get("text", "")).strip()
        if not dimension or not text:
            continue
        normalized.append({
            "id": str(item.get("id") or f"manual-line:{uuid.uuid4().hex}"),
            "dimension": dimension,
            "text": text,
            "why": str(item.get("why", "")).strip(),
            "source": "author",
        })
    if not normalized:
        raise ValueError("至少填写一条声纹")
    profile_id = f"manual:{uuid.uuid4().hex}"
    profile = {
        "schema_version": 1,
        "id": profile_id,
        "name": clean_name,
        "kind": "manual",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "lines": normalized,
    }
    _write_json(_voice_dir(book_dir) / "手写" / f"{profile_id.removeprefix('manual:')}.json", profile)
    save_profile_state(book_dir, profile_id)
    return profile


def mechanically_combine_profiles(
    book_dir: Path,
    source_ids: list[str],
    name: str,
    *,
    builtins_dir: Path | None = None,
) -> dict:
    """Create an editable profile by retaining every source line; never calls a model."""
    catalog = {str(item["id"]): item for item in load_catalog(book_dir, builtins_dir)}
    ids = list(dict.fromkeys(str(item) for item in source_ids))
    if len(ids) < 2:
        raise ValueError("机械合并至少选择两份声纹")
    missing = [item for item in ids if item not in catalog]
    if missing:
        raise ValueError(f"声纹不存在: {', '.join(missing)}")
    lines: list[dict] = []
    refs = []
    for profile_id in ids:
        profile = catalog[profile_id]
        refs.append({
            "id": profile_id,
            "name": str(profile.get("name") or profile_id),
            "fingerprint": _profile_fingerprint(profile),
        })
        for raw in profile.get("lines", []):
            if not isinstance(raw, dict):
                continue
            line = dict(raw)
            line["id"] = f"combined-{uuid.uuid4().hex}"
            line["source"] = "author" if raw.get("source") == "author" else "machine"
            line["source_profile"] = {
                "id": profile_id,
                "name": str(profile.get("name") or profile_id),
            }
            lines.append(line)
    profile_id = f"combined:{uuid.uuid4().hex}"
    profile = {
        "schema_version": 1,
        "id": profile_id,
        "name": str(name).strip() or "合并声纹",
        "kind": "combined",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_profiles": refs,
        "lines": lines,
    }
    _write_json(_voice_dir(book_dir) / "合并声纹" / f"{profile_id.removeprefix('combined:')}.json", profile)
    save_profile_state(book_dir, profile_id)
    return profile


def load_merged_voiceprint(book_dir: Path, builtins_dir: Path | None = None) -> dict:
    book_dir = Path(book_dir)
    catalog_list = _with_source_status(load_catalog(book_dir, builtins_dir))
    catalog = {profile["id"]: profile for profile in catalog_list}
    state = load_profile_state(book_dir)
    active = state["active"]
    if not state["saved"]:
        if SELF_ID in catalog:
            active = SELF_ID
        elif "legacy:fingerprint_path" in catalog:
            active = "legacy:fingerprint_path"
    profile = catalog.get(active) if active else None
    lines = [dict(line) for line in (profile or {}).get("lines", []) if isinstance(line, dict) and is_effective_line(line)]
    policy_block = "\n".join(f"- {rule}" for rule in SYSTEM_USAGE_POLICY)
    rendered_lines = []
    for line in lines:
        rendered = f"- {str(line.get('dimension', '')).strip()}：{str(line.get('text', '')).strip()}"
        why = str(line.get("why", "")).strip()
        if why:
            rendered += f"\n  为什么：{why}"
        rendered_lines.append(rendered)
    text = ""
    if profile:
        text = "【声纹风格层】\n【使用原则】\n" + policy_block + "\n\n【风格规则】\n" + "\n".join(rendered_lines)
    return {
        "profiles": [profile] if profile else [],
        "lines": lines,
        "active_profile": profile,
        "active_profile_id": active if profile else None,
        "usage_policy": list(SYSTEM_USAGE_POLICY) if profile else [],
        "text": text,
    }
