"""Machine-check the data-root lockdown invariants."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(name: str, ok: bool, detail: str) -> bool:
    print(f"{name}: {'GREEN' if ok else 'RED'} - {detail}")
    return ok


def main() -> int:
    results: list[bool] = []
    raw = os.environ.get("BIYU_DATA_ROOT", "").strip()
    results.append(check("explicit data root", bool(raw), "BIYU_DATA_ROOT is set" if raw else "BIYU_DATA_ROOT is missing"))
    results.append(check("no production fallback", "Path.home() / \"BiyuData\"" not in (ROOT / "src/biyu/config.py").read_text(encoding="utf-8"), "config.py has no default production path"))
    trace_source = (ROOT / "src/biyu/editor/multi_agent.py").read_text(encoding="utf-8")
    results.append(check("book-scoped traces", 'Path(book_dir).resolve() / "phase_trace"' in trace_source, "trace path is derived from book_dir"))
    results.append(check("no fixed trace ticket", "T-P3-D-2.2" not in trace_source, "source has no fixed ticket directory"))
    data_root = Path(raw).expanduser().resolve() if raw else None
    role = os.environ.get("BIYU_RUNTIME_ROLE", "").strip().lower()
    if role in {"test", "development"}:
        print("production top-level: UNCHECKED - runtime role is not production")
    elif data_root and data_root.is_dir():
        non_books = [p.name for p in data_root.iterdir() if p.is_dir() and not (p / "book.json").is_file()]
        results.append(check("production top-level", not non_books, "all top-level directories contain book.json" if not non_books else f"non-book directories: {non_books}"))
    else:
        print("production top-level: UNCHECKED - data root is unavailable")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
