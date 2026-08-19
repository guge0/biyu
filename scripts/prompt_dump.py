#!/usr/bin/env python3
"""打印仓库根 prompts/ 中的现役提示词，供老板验证 DIY 修改即时生效。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PROMPT_GROUPS = {
    "writer": (
        ROOT / "prompts" / "writer" / "system.md",
        ROOT / "prompts" / "writer" / "layer3.md",
        ROOT / "prompts" / "writer" / "fragments.json",
    ),
    "editor": (
        ROOT / "prompts" / "editor" / "system.md",
        ROOT / "prompts" / "editor" / "fragments.json",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=sorted(PROMPT_GROUPS))
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    for path in PROMPT_GROUPS[args.role]:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise RuntimeError(f"Required prompt file could not be read: {path}") from exc
        print(f"===== {path.relative_to(ROOT).as_posix()} =====")
        print(content, end="" if content.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
