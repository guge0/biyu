from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


SCRIPT = Path("scripts/make_r5b_fixture.py")


def _module():
    spec = importlib.util.spec_from_file_location("make_r5b_fixture", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(root: Path) -> str:
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rows.append(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes())
    return hashlib.sha256(b"\n".join(rows)).hexdigest()


def test_fixture_is_reproducible(tmp_path: Path) -> None:
    fixture = _module()
    first = fixture.build_fixture(tmp_path, force=True)
    digest = _digest(first)
    second = fixture.build_fixture(tmp_path)
    assert first == second
    assert _digest(second) == digest
    fixture.build_fixture(tmp_path, force=True)
    assert _digest(first) == digest


def test_fixture_meets_all_conditions(tmp_path: Path) -> None:
    fixture = _module()
    book = fixture.build_fixture(tmp_path, force=True)
    checks = fixture.validate_fixture(book)
    assert len(checks) == 8
    assert all(checks.values())
    report = json.loads((book / "audit_reports/ch1.json").read_text(encoding="utf-8"))
    assert len(report["issues"]) >= 2
    assert len((book / "chapters/_pending/ch1.md").read_text(encoding="utf-8").split("\n\n")) >= 6


def test_fixture_zero_llm(tmp_path: Path, monkeypatch) -> None:
    import biyu.config

    monkeypatch.setattr(
        biyu.config,
        "get_registry",
        lambda: (_ for _ in ()).throw(AssertionError("fixture must not request an adapter")),
    )
    fixture = _module()
    fixture.build_fixture(tmp_path, force=True)


def test_fixture_contains_no_real_book_content(tmp_path: Path) -> None:
    fixture = _module()
    book = fixture.build_fixture(tmp_path, force=True)
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in book.rglob("*")
        if path.is_file()
    )
    assert "合成甲" in text and "北坊测试门" in text
    real_root = Path("data/siwanghuisu")
    for sentinel in ("合成甲", "合成乙", "北坊测试门"):
        assert not any(
            sentinel in path.read_text(encoding="utf-8", errors="ignore")
            for path in real_root.rglob("*")
            if path.is_file() and path.stat().st_size < 2_000_000
        )

