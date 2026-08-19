"""Durable versions and author-facing failures for book-level founding assets."""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from biyu.config import get_project_root


class SetupAssetYamlError(ValueError):
    """A setup YAML error safe to show directly to an author."""


_WORLD_BOOK_LIST_SECTIONS = {
    "facts": "设定事实",
    "forbidden": "禁区",
    "geography": "地理设定",
    "factions": "势力设定",
    "timeline": "时间线",
}
_WORLD_BOOK_MAPPING_SECTIONS = {
    "narrative_anchors": "叙事锚点",
    "power_system": "力量体系",
}


_ASSETS: dict[str, dict[str, str]] = {
    "north_star": {"label": "北极星", "filename": "北极星.md", "stem": "north_star", "suffix": ".md"},
    "legacy_north_star": {"label": "北极星（兼容旧稿）", "filename": "", "stem": "north_star_legacy", "suffix": ".md"},
    "book_outline": {"label": "全书大纲", "filename": "大纲.md", "stem": "book_outline", "suffix": ".md"},
    "worldbook": {"label": "世界观", "filename": "worldbook.yaml", "stem": "worldbook", "suffix": ".yaml"},
    "characters": {"label": "角色设定", "filename": "characters.yaml", "stem": "characters", "suffix": ".yaml"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _number(path: Path) -> int:
    match = re.search(r"_v(\d+)$", path.stem)
    return int(match.group(1)) if match else 0


def _asset(asset_id: str) -> dict[str, str]:
    try:
        return _ASSETS[asset_id]
    except KeyError as exc:
        raise ValueError(f"未知立项资产: {asset_id}") from exc


def setup_asset_path(book_dir: Path, asset_id: str) -> Path:
    asset = _asset(asset_id)
    if asset_id == "legacy_north_star":
        return get_project_root() / "docs" / f"北极星_{book_dir.name}.md"
    return book_dir / asset["filename"]


def _versions_dir(book_dir: Path, asset_id: str) -> Path:
    _asset(asset_id)
    return book_dir / "logs" / "setup_assets" / asset_id


def _version_path(book_dir: Path, asset_id: str, version: int) -> Path:
    asset = _asset(asset_id)
    return _versions_dir(book_dir, asset_id) / f"{asset['stem']}_v{version}{asset['suffix']}"


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_bytes_atomically(path: Path, content: bytes) -> None:
    """Replace one file atomically without changing its bytes."""
    _atomic_write(path, content)


def _roundtrip_yaml() -> YAML:
    parser = YAML(typ="rt")
    parser.preserve_quotes = True
    parser.width = 4096
    return parser


def _load_roundtrip_document(path: Path, *, label: str) -> CommentedMap:
    parser = _roundtrip_yaml()
    try:
        value = parser.load(path.read_text(encoding="utf-8")) if path.exists() else CommentedMap()
    except Exception as exc:
        raise SetupAssetYamlError(
            f"{label}（{path.name}）的写法有误，请检查缩进、冒号或括号后再试。本次没有保存。"
        ) from exc
    if value is None:
        return CommentedMap()
    if not isinstance(value, CommentedMap):
        raise SetupAssetYamlError(f"{label}最外层必须是按字段组织的内容。本次没有保存。")
    return value


def _dump_roundtrip_document(value: CommentedMap) -> bytes:
    stream = StringIO()
    _roundtrip_yaml().dump(value, stream)
    return stream.getvalue().encode("utf-8")


def _replace_top_level_section(original: bytes, section: str, replacement: Any) -> bytes:
    """Splice one top-level YAML field while retaining every byte outside that field."""
    text = original.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    key_pattern = re.compile(rf"^{re.escape(section)}\s*:")
    any_key_pattern = re.compile(r"^[^\s#][^:]*\s*:")
    start = next((index for index, line in enumerate(lines) if key_pattern.match(line)), None)
    if start is None:
        start = len(lines)
        end = start
    else:
        end = next(
            (index for index in range(start + 1, len(lines)) if any_key_pattern.match(lines[index])),
            len(lines),
        )

    field = CommentedMap([(section, replacement)])
    field_text = _dump_roundtrip_document(field).decode("utf-8").replace("\n", newline)
    if start == len(lines) and text and not text.endswith(("\n", "\r")):
        field_text = newline + field_text
    return ("".join(lines[:start]) + field_text + "".join(lines[end:])).encode("utf-8")


def update_worldbook_section(
    book_dir: Path, section: str, value: Any, *, actor: str = "未记录",
) -> None:
    """Validate and replace exactly one worldbook section, retaining comments/order elsewhere."""
    if section in _WORLD_BOOK_LIST_SECTIONS:
        label = _WORLD_BOOK_LIST_SECTIONS[section]
        if not isinstance(value, list):
            raise SetupAssetYamlError(f"{label}需要逐条填写，不能填写成一组字段。本次没有保存。")
        replacement: Any = CommentedSeq(value)
    elif section in _WORLD_BOOK_MAPPING_SECTIONS:
        label = _WORLD_BOOK_MAPPING_SECTIONS[section]
        if not isinstance(value, dict):
            raise SetupAssetYamlError(f"{label}需要按字段填写。本次没有保存。")
        replacement = CommentedMap(value)
    else:
        raise SetupAssetYamlError(f"未识别的世界观段落：{section}。本次没有保存。")

    path = setup_asset_path(book_dir, "worldbook")
    _load_roundtrip_document(path, label="世界观")
    original = path.read_bytes() if path.exists() else b""
    content = _replace_top_level_section(original, section, replacement)
    # Validate the complete candidate before taking a version or touching disk.
    try:
        candidate = _roundtrip_yaml().load(content.decode("utf-8"))
    except Exception as exc:
        raise SetupAssetYamlError(f"{label}保存后的结构不合格。本次没有保存。") from exc
    if not isinstance(candidate, dict):
        raise SetupAssetYamlError(f"{label}保存后的结构不合格。本次没有保存。")
    if path.exists():
        save_setup_asset_version(
            book_dir, "worldbook", reason=f"before_section_write:{section}", actor=actor,
        )
    write_bytes_atomically(path, content)
    save_setup_asset_version(
        book_dir, "worldbook", reason=f"after_section_write:{section}", actor=actor,
    )


def update_characters_list(
    book_dir: Path, characters: Any, *, reason: str, actor: str = "未记录",
) -> None:
    """Legacy whole-list compatibility; new editors must use field-level helpers."""
    if not isinstance(characters, list):
        raise SetupAssetYamlError("人物卡必须是一组角色。本次没有保存。")
    for index, character in enumerate(characters, start=1):
        if not isinstance(character, dict):
            raise SetupAssetYamlError(f"第 {index} 张人物卡需要按字段填写。本次没有保存。")
        if not str(character.get("name") or "").strip():
            raise SetupAssetYamlError(f"第 {index} 张人物卡缺少角色名。本次没有保存。")

    path = setup_asset_path(book_dir, "characters")
    document = _load_roundtrip_document(path, label="角色设定")
    document["characters"] = CommentedSeq(characters)
    content = _dump_roundtrip_document(document)
    if path.exists():
        save_setup_asset_version(
            book_dir, "characters", reason=f"before_{reason}", actor=actor,
        )
    write_bytes_atomically(path, content)
    save_setup_asset_version(book_dir, "characters", reason=f"after_{reason}", actor=actor)


def update_character_card(
    book_dir: Path,
    character: Any,
    *,
    original_name: str | None = None,
    reason: str = "character_card_write",
    actor: str = "未记录",
) -> None:
    """Replace one named character card without replacing sibling cards or top-level keys."""
    if not isinstance(character, dict):
        raise SetupAssetYamlError("人物卡需要按字段填写。本次没有保存。")
    name = str(character.get("name") or "").strip()
    if not name:
        raise SetupAssetYamlError("人物卡缺少角色名。本次没有保存。")

    path = setup_asset_path(book_dir, "characters")
    document = _load_roundtrip_document(path, label="角色设定")
    cards = document.get("characters")
    if cards is None:
        cards = CommentedSeq()
        document["characters"] = cards
    if not isinstance(cards, list):
        raise SetupAssetYamlError("角色设定中的人物卡列表格式不合格。本次没有保存。")

    target = original_name or name
    index = next(
        (i for i, card in enumerate(cards) if isinstance(card, dict) and str(card.get("name") or "") == target),
        None,
    )
    replacement = CommentedMap(character)
    if index is None:
        cards.append(replacement)
    else:
        old = cards[index]
        if isinstance(old, CommentedMap):
            old.clear()
            old.update(replacement)
        else:
            cards[index] = replacement

    content = _dump_roundtrip_document(document)
    if path.exists():
        save_setup_asset_version(
            book_dir, "characters", reason=f"before_{reason}:{target}", actor=actor,
        )
    write_bytes_atomically(path, content)
    save_setup_asset_version(
        book_dir, "characters", reason=f"after_{reason}:{name}", actor=actor,
    )


def update_character_fields(
    book_dir: Path,
    name: str,
    fields: Any,
    *,
    reason: str = "character_fields_write",
    actor: str = "未记录",
) -> None:
    """Patch fields on one existing character, leaving all sibling cards untouched."""
    target_name = str(name or "").strip()
    if not target_name:
        raise SetupAssetYamlError("请选择要修改的人物卡。本次没有保存。")
    if not isinstance(fields, dict) or not fields:
        raise SetupAssetYamlError("请填写至少一个要修改的人物字段。本次没有保存。")
    if any(not isinstance(key, str) or not key.strip() for key in fields):
        raise SetupAssetYamlError("人物字段名称不合格。本次没有保存。")
    if "name" in fields and not str(fields.get("name") or "").strip():
        raise SetupAssetYamlError("角色名不能为空。本次没有保存。")
    if "aliases" in fields and not isinstance(fields["aliases"], dict):
        raise SetupAssetYamlError("称谓指引需要按称呼关系填写。本次没有保存。")
    for list_field, label in (
        ("voice_examples", "说话示例"),
        ("forbidden_in_narrative", "禁用称谓"),
        ("tier_history", "角色档位历史"),
    ):
        if list_field in fields and not isinstance(fields[list_field], list):
            raise SetupAssetYamlError(f"{label}需要逐条填写。本次没有保存。")

    path = setup_asset_path(book_dir, "characters")
    document = _load_roundtrip_document(path, label="角色设定")
    cards = document.get("characters")
    if not isinstance(cards, list):
        raise SetupAssetYamlError("角色设定中的人物卡列表格式不合格。本次没有保存。")
    target = next(
        (card for card in cards if isinstance(card, dict) and str(card.get("name") or "") == target_name),
        None,
    )
    if target is None:
        raise SetupAssetYamlError(f"没有找到角色“{target_name}”。本次没有保存。")
    for key, value in fields.items():
        target[key] = value

    content = _dump_roundtrip_document(document)
    try:
        candidate = _roundtrip_yaml().load(content.decode("utf-8"))
    except Exception as exc:
        raise SetupAssetYamlError("人物卡保存后的结构不合格。本次没有保存。") from exc
    candidate_cards = candidate.get("characters") if isinstance(candidate, dict) else None
    if not isinstance(candidate_cards, list) or any(
        not isinstance(card, dict) or not str(card.get("name") or "").strip()
        for card in candidate_cards
    ):
        raise SetupAssetYamlError("人物卡保存后的结构不合格。本次没有保存。")

    save_setup_asset_version(
        book_dir, "characters", reason=f"before_{reason}:{target_name}", actor=actor,
    )
    write_bytes_atomically(path, content)
    final_name = str(target.get("name") or target_name)
    save_setup_asset_version(
        book_dir, "characters", reason=f"after_{reason}:{final_name}", actor=actor,
    )


def update_north_star_text(
    book_dir: Path, content: Any, *, actor: str = "未记录",
) -> None:
    """Validate and atomically replace the book-local North Star with exact versions."""
    if not isinstance(content, str):
        raise SetupAssetYamlError("北极星需要填写成文字。本次没有保存。")
    normalized = content.strip()
    if not normalized:
        raise SetupAssetYamlError("北极星不能为空。本次没有保存。")
    if not re.search(r"(?m)^#\s*北极星(?:\s|·|$)", normalized):
        raise SetupAssetYamlError("北极星需要以“# 北极星”开头。本次没有保存。")
    if not re.search(r"(?m)^##\s*一句话故事\s*$", normalized):
        raise SetupAssetYamlError("北极星缺少“一句话故事”这一段。本次没有保存。")
    story_match = re.search(
        r"(?ms)^##\s*一句话故事\s*$\s*(.+?)(?=^##\s|\Z)", normalized,
    )
    if story_match is None or not story_match.group(1).strip():
        raise SetupAssetYamlError("北极星的“一句话故事”还没有内容。本次没有保存。")

    path = setup_asset_path(book_dir, "north_star")
    payload = (normalized + "\n").encode("utf-8")
    if path.exists():
        save_setup_asset_version(
            book_dir, "north_star", reason="before_north_star_write", actor=actor,
        )
    write_bytes_atomically(path, payload)
    save_setup_asset_version(
        book_dir, "north_star", reason="after_north_star_write", actor=actor,
    )


def update_book_outline_text(
    book_dir: Path, content: Any, *, actor: str = "未记录",
) -> None:
    """Validate and atomically replace the single book-outline text cell."""
    if not isinstance(content, str):
        raise SetupAssetYamlError("大纲需要填写成文字。本次没有保存。")
    normalized = content.strip()
    if not normalized:
        raise SetupAssetYamlError("大纲不能为空。本次没有保存。")
    if not re.search(r"(?m)^#\s*(?:全书)?大纲(?:\s|·|$)", normalized):
        raise SetupAssetYamlError("大纲需要以“# 大纲”开头。本次没有保存。")
    if not re.search(r"(?m)^##\s*\S+", normalized):
        raise SetupAssetYamlError("大纲至少需要一个以“##”开头的分段。本次没有保存。")

    path = setup_asset_path(book_dir, "book_outline")
    payload = (normalized + "\n").encode("utf-8")
    if path.exists():
        save_setup_asset_version(
            book_dir, "book_outline", reason="before_book_outline_write", actor=actor,
        )
    write_bytes_atomically(path, payload)
    save_setup_asset_version(
        book_dir, "book_outline", reason="after_book_outline_write", actor=actor,
    )


def _write_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_write(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def save_setup_asset_version(
    book_dir: Path, asset_id: str, *, reason: str, actor: str = "未记录",
) -> int | None:
    """Snapshot the asset's exact bytes, deduplicating identical versions."""
    source = setup_asset_path(book_dir, asset_id)
    if not source.exists():
        return None
    content = source.read_bytes()
    directory = _versions_dir(book_dir, asset_id)
    directory.mkdir(parents=True, exist_ok=True)
    versions = sorted(directory.glob(f"{_asset(asset_id)['stem']}_v*{_asset(asset_id)['suffix']}"), key=_number)
    existing = next((path for path in versions if path.read_bytes() == content), None)
    version = _number(existing) if existing else (_number(versions[-1]) + 1 if versions else 1)
    if existing is None:
        target = _version_path(book_dir, asset_id, version)
        _atomic_write(target, content)
        _write_json(
            target.with_suffix(".json"),
            {
                "version": version,
                "created_at": _now(),
                "reason": reason,
                "source": str(source),
                "actor": actor,
            },
        )
    _atomic_write(directory / "current", f"v{version}\n".encode("utf-8"))
    return version


def sync_setup_asset_version(book_dir: Path, asset_id: str, *, reason: str = "managed_read") -> int | None:
    """Absorb the current bytes when a managed path observes the asset."""
    return save_setup_asset_version(book_dir, asset_id, reason=reason)


def _current_version(book_dir: Path, asset_id: str) -> int | None:
    pointer = _versions_dir(book_dir, asset_id) / "current"
    try:
        version = int(pointer.read_text(encoding="utf-8").strip().removeprefix("v"))
    except (OSError, ValueError):
        return None
    return version if _version_path(book_dir, asset_id, version).exists() else None


def list_setup_asset_versions(book_dir: Path) -> list[dict[str, Any]]:
    """Return existing author-facing version cards without creating baselines."""
    result: list[dict[str, Any]] = []
    for asset_id, asset in _ASSETS.items():
        path = setup_asset_path(book_dir, asset_id)
        directory = _versions_dir(book_dir, asset_id)
        if not path.exists() and not directory.exists():
            continue
        current = _current_version(book_dir, asset_id)
        versions = []
        pattern = f"{asset['stem']}_v*{asset['suffix']}"
        for version_path in sorted(directory.glob(pattern), key=_number, reverse=True):
            version = _number(version_path)
            meta = _read_json(version_path.with_suffix(".json"))
            versions.append({
                "version": version,
                "current": version == current,
                "created_at": meta.get("created_at", ""),
                "reason": meta.get("reason", ""),
                "actor": meta.get("actor") or "未记录",
                "content": version_path.read_text(encoding="utf-8"),
            })
        result.append({
            "asset_id": asset_id,
            "label": asset["label"],
            "exists": path.exists(),
            "versions": versions,
        })
    return result


def restore_setup_asset_version(book_dir: Path, asset_id: str, version: int) -> bytes:
    """Restore exact bytes while retaining the file being replaced as a version."""
    source = _version_path(book_dir, asset_id, version)
    if not source.exists():
        raise FileNotFoundError(f"{_asset(asset_id)['label']}第 {version} 版不存在")
    target = setup_asset_path(book_dir, asset_id)
    if target.exists():
        save_setup_asset_version(book_dir, asset_id, reason="before_restore")
    content = source.read_bytes()
    _atomic_write(target, content)
    _atomic_write(_versions_dir(book_dir, asset_id) / "current", f"v{version}\n".encode("utf-8"))
    return content


def _notice_path(book_dir: Path) -> Path:
    return book_dir / "logs" / "setup_assets" / "restore_notice.json"


def record_setup_restore_notice(book_dir: Path, *, version: int, reason: str) -> dict[str, Any]:
    message = f"刚才{reason}恢复了角色资料；你之前的编辑保存在版本 {version}，可以在书籍页找回。"
    value = {
        "active": True,
        "message": message,
        "version": version,
        "reason": reason,
        "created_at": _now(),
    }
    _write_json(_notice_path(book_dir), value)
    return value


def load_setup_restore_notice(book_dir: Path) -> dict[str, Any]:
    value = _read_json(_notice_path(book_dir))
    if not value:
        return {"active": False, "message": "", "version": None, "reason": "", "created_at": ""}
    return {
        "active": value.get("active") is True,
        "message": str(value.get("message") or ""),
        "version": value.get("version"),
        "reason": str(value.get("reason") or ""),
        "created_at": str(value.get("created_at") or ""),
    }


def acknowledge_setup_restore_notice(book_dir: Path) -> dict[str, Any]:
    value = _read_json(_notice_path(book_dir))
    value["active"] = False
    _write_json(_notice_path(book_dir), value)
    return load_setup_restore_notice(book_dir)


def _yaml_error(path: Path, label: str, exc: yaml.MarkedYAMLError) -> SetupAssetYamlError:
    mark = getattr(exc, "problem_mark", None)
    line = f"第 {mark.line + 1} 行附近" if mark is not None else "内容中"
    return SetupAssetYamlError(
        f"{label}（{path.name}）{line}写法有误，请检查冒号、缩进或括号后再试。"
        "本次没有开始生成，也没有产生费用。"
    )


def load_setup_yaml(path: Path, *, label: str) -> dict[str, Any]:
    """Load with PyYAML while translating syntax failures for the author."""
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.MarkedYAMLError as exc:
        raise _yaml_error(path, label, exc) from exc
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SetupAssetYamlError(
            f"{label}（{path.name}）需要从字段名称开始书写，请检查最外层格式后再试。"
            "本次没有开始生成，也没有产生费用。"
        )
    return value


def validate_characters_yaml_before_model(book_dir: Path) -> None:
    path = book_dir / "characters.yaml"
    if path.exists():
        load_setup_yaml(path, label="角色设定")
