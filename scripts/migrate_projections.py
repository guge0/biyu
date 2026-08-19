"""One-time projection-shard migration for an isolated book only."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Awaitable, Callable


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


async def migrate(
    book_dir: Path,
    repair_one: Callable[[int, Path], Awaitable[tuple[bool, float]]],
    *,
    hard_stop: float = 0.50,
) -> dict:
    if book_dir.name.casefold() == "siwanghuisu":
        raise PermissionError("禁止对老板真书执行投影迁移")
    from biyu.observer import backup_truth_files_pre_ring4
    backup = backup_truth_files_pre_ring4(book_dir)
    chapters = sorted(
        int(path.stem[2:]) for path in (book_dir / "chapters").glob("ch*.md")
        if path.stem[2:].isdigit()
    )
    repaired: list[int] = []
    spent = 0.0
    before = {chapter: _sha(book_dir / "truth_files/projections" / f"ch{chapter}.yaml") for chapter in chapters}
    for chapter in chapters:
        shard = book_dir / "truth_files/projections" / f"ch{chapter}.yaml"
        if shard.exists():
            continue
        if spent >= hard_stop:
            raise RuntimeError(f"迁移达到硬停线 ¥{hard_stop:.2f}")
        ok, cost = await repair_one(chapter, book_dir / "chapters" / f"ch{chapter}.md")
        spent += cost
        if spent > hard_stop:
            raise RuntimeError(f"迁移超过硬停线 ¥{hard_stop:.2f}")
        if not ok:
            raise RuntimeError(f"ch{chapter} 分片补建失败")
        repaired.append(chapter)
    after = {chapter: _sha(book_dir / "truth_files/projections" / f"ch{chapter}.yaml") for chapter in chapters}
    return {"book": book_dir.name, "backup": str(backup), "repaired": repaired, "cost": spent, "before": before, "after": after}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("book", type=Path, help="隔离书目录；禁止 siwanghuisu")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    from biyu.config import get_registry
    from biyu.observer import update_official_chapter_projection
    adapter = get_registry().get_adapter_for_stage("writer")

    async def repair(chapter: int, official: Path) -> tuple[bool, float]:
        costs: list[float] = []
        ok = await update_official_chapter_projection(args.book, chapter, official, adapter, _log_cost_fn=lambda cost, _latency: costs.append(cost))
        return ok, sum(costs)

    result = asyncio.run(migrate(args.book.resolve(), repair))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
