from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "docs" / "index.html"


def test_c1_landing_page_is_delivered_in_repository() -> None:
    assert LANDING.is_file()
    page = LANDING.read_text(encoding="utf-8")
    assert "<title>笔驭 — 一套管得住 AI 的长篇小说工序</title>" in page
    assert "读稿定夺这一屏" in page
    assert "这是真的，点点看" in page


def test_c2_readme_links_landing_page_at_top() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    top = "\n".join(readme.splitlines()[:6])
    assert "[了解笔驭](https://guge0.github.io/biyu/)" in top


def test_readme_has_one_public_landing_entry_and_ends_with_group_invitation() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.count("https://guge0.github.io/biyu/") == 1
    assert "[`docs/index.html`](docs/index.html)" not in readme
    assert "GitHub Issues" not in readme
    assert 'src="docs/images/qq-group.jpg"' in readme
    assert (ROOT / "docs" / "images" / "qq-group.jpg").is_file()


def test_c4_product_first_screen_remains_shelf() -> None:
    product = (ROOT / "src/biyu/ui/static/index.html").read_text(encoding="utf-8")
    assert "笔驭作者工作台 · 书架" in product
    assert 'id="book-list"' in product
    assert "一套管得住 AI 的长篇小说工序" not in product


def test_c5_landing_is_static_zero_dependency_and_not_packaged() -> None:
    page = LANDING.read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert not re.search(r'<script\s+[^>]*src=', page, re.IGNORECASE)
    assert not re.search(r'<link\s+[^>]*href=', page, re.IGNORECASE)
    assert "fetch(" not in page
    assert "http://" not in page and "https://" not in page
    assert "docs/index.html" not in pyproject


def test_landing_page_does_not_leak_local_data_paths() -> None:
    page = LANDING.read_text(encoding="utf-8")
    for forbidden in (
        r"C:\\Users",
        r"D:\\Biyu",
        r"E:\\webnovel",
        "Gugger",
        "BiyuData",
    ):
        assert forbidden not in page
