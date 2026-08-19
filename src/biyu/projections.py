"""Immutable, per-chapter Observer projection shards."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Callable


def entries_from_truth(filename: str, content: str) -> dict[str, str]:
    """Convert one Observer markdown table into stable, lossless row entries."""
    lines = [line.rstrip() for line in content.strip().splitlines() if line.strip()]
    table_rows = [line for line in lines if line.lstrip().startswith("|")]
    if len(table_rows) < 2:
        return {"__whole__": content}
    entries: dict[str, str] = {"__header__": "\n".join(table_rows[:2])}
    for index, line in enumerate(table_rows[2:]):
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if filename == "particle_ledger.md":
            key = ":".join(cells[:3]) if len(cells) >= 3 else f"row-{index}"
        else:
            key = cells[0] if cells else f"row-{index}"
        entries[key] = line
    return entries


def _path(book_dir: Path, chapter: int) -> Path:
    directory = book_dir / "truth_files" / "projections"
    pointer = directory / f"ch{chapter}.current"
    if pointer.exists():
        selected = pointer.read_text(encoding="utf-8").strip()
        if selected and Path(selected).name == selected:
            return directory / selected
    return directory / f"ch{chapter}.yaml"


def write_shard(book_dir: Path, chapter: int, shard: dict[str, Any]) -> Path:
    """Persist one shard once. Existing shards are immutable."""
    path = _path(book_dir, chapter)
    if path.exists():
        raise FileExistsError(f"投影分片已存在，禁止覆盖: ch{chapter}")
    if int(shard.get("chapter", -1)) != chapter:
        raise ValueError("分片章节号不一致")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(shard, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def select_new_shard(book_dir: Path, chapter: int, shard: dict[str, Any]) -> Path:
    """Persist a new immutable version and atomically move the current pointer."""
    encoded = (json.dumps(shard, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    directory = book_dir / "truth_files" / "projections"
    directory.mkdir(parents=True, exist_ok=True)
    base = directory / f"ch{chapter}.yaml"
    if not base.exists():
        return write_shard(book_dir, chapter, shard)
    if base.read_bytes() == (json.dumps(shard, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"):
        return base
    version = directory / f"ch{chapter}_{hashlib.sha256(encoded).hexdigest()[:12]}.yaml"
    if not version.exists():
        version.write_bytes(encoded)
    pointer = directory / f"ch{chapter}.current"
    temporary = pointer.with_suffix(".tmp")
    temporary.write_text(version.name + "\n", encoding="utf-8")
    temporary.replace(pointer)
    return version


def read_shard(book_dir: Path, chapter: int) -> dict[str, Any]:
    path = _path(book_dir, chapter)
    if not path.exists():
        raise FileNotFoundError(f"缺少投影分片: ch{chapter}")
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"投影分片损坏: ch{chapter}") from exc
    if int(result.get("chapter", -1)) != chapter:
        raise ValueError(f"投影分片章节号不一致: ch{chapter}")
    return result


def read_shards(book_dir: Path, chapters: set[int]) -> list[dict[str, Any]]:
    """Read precisely the shards selected by the current official chapters."""
    return [read_shard(book_dir, chapter) for chapter in sorted(chapters)]


def select_shard_for_official(book_dir: Path, chapter: int, official_sha256: str) -> None:
    """Select the immutable shard that was produced from the restored official."""
    directory = book_dir / "truth_files" / "projections"
    matches = []
    hashed_candidates = 0
    for path in sorted(directory.glob(f"ch{chapter}*.yaml")) if directory.exists() else []:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if value.get("official_sha256"):
            hashed_candidates += 1
        if value.get("official_sha256") == official_sha256:
            matches.append(path)
    if not matches:
        if hashed_candidates:
            raise FileNotFoundError(f"缺少与正式稿匹配的投影分片: ch{chapter}")
        return  # A legacy migrated shard has no source hash to select by.
    selected = matches[-1]
    pointer = directory / f"ch{chapter}.current"
    temporary = pointer.with_suffix(".tmp")
    temporary.write_text(selected.name + "\n", encoding="utf-8")
    temporary.replace(pointer)


def repair_missing_shards(book_dir: Path, chapters: set[int], build_one: Callable[[int], dict[str, Any]]) -> list[int]:
    """Repair only missing shards; callers own any explicitly-authorized LLM work."""
    repaired: list[int] = []
    for chapter in sorted(chapters):
        try:
            read_shard(book_dir, chapter)
        except (FileNotFoundError, ValueError):
            write_shard(book_dir, chapter, build_one(chapter))
            repaired.append(chapter)
    return repaired
