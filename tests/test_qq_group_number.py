"""QQ 群号只有一个：462502077。防止错号回流到界面、诊断包和文档里。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUP = "462502077"
WRONG = "892467108"
TEXT_SUFFIXES = {".py", ".js", ".html", ".css", ".md", ".txt", ".json", ".yaml", ".yml"}


def _texts():
    for base in (ROOT / "src", ROOT / "docs", ROOT / "README.md"):
        paths = [base] if base.is_file() else base.rglob("*")
        for p in paths:
            if p.is_file() and p.suffix in TEXT_SUFFIXES:
                yield p, p.read_text(encoding="utf-8", errors="ignore")


def test_wrong_group_number_absent():
    hits = [str(p.relative_to(ROOT)) for p, t in _texts() if WRONG in t]
    assert hits == []


def test_group_number_shown_in_app_and_readme():
    static = ROOT / "src" / "biyu" / "ui" / "static"
    for name in ("shell.js", "settings.html", "settings.js"):
        assert GROUP in (static / name).read_text(encoding="utf-8")
    assert GROUP in (ROOT / "src" / "biyu" / "ui" / "diagnostics.py").read_text(encoding="utf-8")
    assert GROUP in (ROOT / "README.md").read_text(encoding="utf-8")