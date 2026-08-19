"""Render Q-1's read-only zebian preload and lookup catalogs."""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from biyu.config import find_book_dir
from biyu.injection_tools import (
    build_book_material_catalog,
    build_character_catalog,
    build_worldbook_catalog,
)
from biyu.pipeline import _read_north_star
from biyu.truth_files import read_all_truth_files


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def render_zebian_context(book_dir: Path) -> str:
    north_star, _ = _read_north_star(book_dir)
    outline = _text(book_dir / "大纲.md")
    world_path = book_dir / "worldbook.yaml"
    world = yaml.safe_load(_text(world_path)) or {} if world_path.exists() else {}
    anchors = world.get("narrative_anchors", {}) if isinstance(world, dict) else {}
    truth = read_all_truth_files(book_dir)
    blocks = [
        f"# 北极星\n{north_star or '（空）'}",
        f"# 大纲\n{outline or '（空）'}",
        "# 创作锚点\n" + (yaml.safe_dump(anchors, allow_unicode=True, sort_keys=False).strip() or "（空）"),
        "# truth_files\n" + "\n\n".join(
            f"## {name}\n{content or '（空）'}" for name, content in truth.items()
        ),
        "# 世界观其余格目录\n"
        + build_worldbook_catalog(book_dir, exclude_fields={"narrative_anchors"}),
        "# 人物卡目录\n" + build_character_catalog(book_dir),
        "# 章节与细纲目录\n" + build_book_material_catalog(book_dir),
    ]
    return "\n\n".join(blocks)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("book")
    args = parser.parse_args()
    print(render_zebian_context(find_book_dir(args.book)))


if __name__ == "__main__":
    main()
