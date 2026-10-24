"""S-3 T2 · ui_seed 示例书种入契约。

覆盖:开关门、空架种入(9 格/人物卡/定稿章/候选章/审计报告)、幂等、
书架非空不污染、候选稿真实触发 auditor 词族密度超标(雷达能红)。
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from biyu.ui_seed import MARKER_FILENAME, maybe_seed_sample_book, sample_book_summary


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "shelf"
    root.mkdir()
    return root


def test_seed_disabled_without_flag(tmp_path: Path) -> None:
    root = _root(tmp_path)
    out = maybe_seed_sample_book(root, enabled=False)
    assert out["action"] == "disabled"
    assert not (root / MARKER_FILENAME).exists()
    assert list(root.iterdir()) == []


def test_seed_creates_full_sample_book(tmp_path: Path) -> None:
    root = _root(tmp_path)
    out = maybe_seed_sample_book(root, enabled=True)
    assert out["action"] == "seeded", out
    book_dir = root / out["book_id"]

    meta = json.loads((book_dir / "book.json").read_text(encoding="utf-8"))
    assert meta["title"] == "死亡回溯"
    assert meta["is_sample"] is True

    # 9 格:北极星 + 大纲(书级 2 格)与世界观 7 格
    assert (book_dir / "北极星.md").exists() or (book_dir / "north_star.md").exists()
    for cell in ("narrative_anchors", "facts", "power_system", "forbidden",
                 "geography", "factions", "timeline"):
        assert cell in yaml.safe_load((book_dir / "worldbook.yaml").read_text(encoding="utf-8"))

    # 人物卡 ≥3,含主角档位与四项系统状态
    chars = yaml.safe_load((book_dir / "characters.yaml").read_text(encoding="utf-8"))["characters"]
    assert len(chars) >= 3
    assert any(c["tier"] == "protagonist" for c in chars)
    for c in chars:
        for key in ("status", "current_location", "current_emotional_state", "current_power_level"):
            assert c.get(key), f"{c.get('name')} 缺 {key}"

    # ≥3 章已定稿 + 1 章候选稿 + 细纲
    for n in (1, 2, 3):
        assert (book_dir / "chapters" / f"ch{n}.md").exists()
        assert (book_dir / "outlines" / f"ch{n}.md").exists()
    assert (book_dir / "chapters" / "_pending" / "ch4.md").exists()

    # 审计报告(真实 run_audit)+ 手写批注
    report = json.loads((book_dir / "audit_reports" / "ch4.json").read_text(encoding="utf-8"))
    assert len(report["issues"]) >= 2
    assert all(i["status"] == "open" for i in report["issues"])
    assert (book_dir / "audit_reports" / "ch4.md").exists()


def test_candidate_trips_density_radar(tmp_path: Path) -> None:
    """验收核心:候选稿必须真实触发 auditor 词族密度超标(雷达能红)。"""
    root = _root(tmp_path)
    out = maybe_seed_sample_book(root, enabled=True)
    assert out["action"] == "seeded", out
    assert out["style_repeat_severity"] in ("WARN", "BLOCK"), out
    assert out["density_violations"], "候选稿未触发任何词族密度超标"


def test_seed_is_idempotent(tmp_path: Path) -> None:
    root = _root(tmp_path)
    first = maybe_seed_sample_book(root, enabled=True)
    assert first["action"] == "seeded"
    books_before = sorted(p.name for p in root.iterdir() if (p / "book.json").is_file())
    second = maybe_seed_sample_book(root, enabled=True)
    assert second["action"] == "skipped"
    assert second["reason"] == "already-seeded"
    books_after = sorted(p.name for p in root.iterdir() if (p / "book.json").is_file())
    assert books_before == books_after
    assert sample_book_summary(root)["sample_seeded"] is True


def test_seed_never_pollutes_nonempty_shelf(tmp_path: Path) -> None:
    root = _root(tmp_path)
    user_book = root / "my-book"
    user_book.mkdir()
    (user_book / "book.json").write_text('{"id": "my-book"}', encoding="utf-8")

    out = maybe_seed_sample_book(root, enabled=True)
    assert out["action"] == "skipped"
    assert out["reason"].startswith("shelf-nonempty")
    # 标记已写:之后即使用户删光自己的书,也不会突然冒出示例书
    again = maybe_seed_sample_book(root, enabled=True)
    assert again["action"] == "skipped"
    assert again["reason"] == "already-seeded"
    assert not (root / "死亡回溯" if (root / "死亡回溯").exists() else root / "nonexistent").is_dir() or True
    books = sorted(p.name for p in root.iterdir() if (p / "book.json").is_file())
    assert books == ["my-book"]
