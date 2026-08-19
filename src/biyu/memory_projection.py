"""Deterministic memory projection: shards first, author pins last.

This module is deliberately the only place that knows the Ring 5 formula.
Callers provide persisted chapter shards; it never calls an LLM or reads files.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class MemoryProjection:
    values: dict[str, dict[str, str]]
    conflicts: list[dict[str, str]]

    def texts(self) -> dict[str, str]:
        rendered: dict[str, str] = {}
        for filename, entries in self.values.items():
            if "__whole__" in entries:
                rendered[filename] = entries["__whole__"]
                continue
            header = entries.get("__header__", "")
            rows = [value for key, value in entries.items() if not key.startswith("__")]
            rendered[filename] = "\n".join([part for part in (header, *rows) if part]) + "\n"
        return rendered


def merge_machine_projection(
    shards: Iterable[dict[str, Any]],
    official_chapters: set[int],
    *,
    adapter: Any | None = None,
) -> dict[str, dict[str, str]]:
    """Replay persisted official shards in chapter order, without an adapter call."""
    del adapter  # Deliberately accepted only to make accidental use testable.
    merged: dict[str, dict[str, str]] = {}
    for shard in sorted(shards, key=lambda item: int(item["chapter"])):
        if int(shard["chapter"]) not in official_chapters:
            continue
        for filename, entries in shard.get("files", {}).items():
            destination = merged.setdefault(str(filename), {})
            for key, value in entries.items():
                if value is None:
                    destination.pop(str(key), None)
                else:
                    destination[str(key)] = str(value)
    return {name: dict(sorted(entries.items())) for name, entries in sorted(merged.items())}


def serialize_projection(values: dict[str, dict[str, str]]) -> bytes:
    """Canonical byte representation used by deterministic replay tests."""
    return (json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def rebuild_memory(
    shards: Iterable[dict[str, Any]],
    official_chapters: set[int],
    pins: dict[str, dict[str, str]],
) -> MemoryProjection:
    """Apply the sole formula: machine projection, then author pins."""
    values = merge_machine_projection(shards, official_chapters)
    conflicts: list[dict[str, str]] = []
    for compound_key, pin in sorted(pins.items()):
        filename, entry_key = compound_key.split(":", 1)
        target = values.setdefault(filename, {})
        machine = target.get(entry_key, "")
        pinned = str(pin["value"])
        resolution = pin.get("resolution", "")
        if machine != pinned and resolution != "keep":
            conflicts.append({"key": compound_key, "machine": machine, "pinned": pinned})
        target[entry_key] = pinned
    values = {name: dict(sorted(entries.items())) for name, entries in sorted(values.items())}
    return MemoryProjection(values=values, conflicts=conflicts)
