import re
from pathlib import Path


STATIC = Path("src/biyu/ui/static")
HIDDEN_TARGETS = (
    "/editor.html",
    "/propose.html",
    "/prompts.html",
    "/preferences.html",
    "/reviews.html",
)
PRUNED_RETAINED_TARGETS = HIDDEN_TARGETS[:-1]
RETAINED_PAGES = (
    "index.html",
    "book.html",
    "workbench.html",
    "memory.html",
    "voiceprint.html",
    "overview.html",
    "summaries.html",
    "good-sentences.html",
)
SIX_PAGE_NAV = (
    "propose.html",
    "editor.html",
    "prompts.html",
    "preferences.html",
    "summaries.html",
)


def _text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _top_nav(html: str) -> str:
    match = re.search(r'<nav class="top-nav">.*?</nav>', html, re.DOTALL)
    assert match is not None
    return match.group(0)


def test_retained_pages_do_not_link_to_pruned_pages() -> None:
    for page in RETAINED_PAGES:
        html = _text(page)
        for target in HIDDEN_TARGETS:
            assert f'href="{target}' not in html, f"{page} still links to {target}"


def test_all_four_navigation_surfaces_hide_pruned_targets() -> None:
    surfaces = {
        "shelf_top": _top_nav(_text("index.html")),
        "book_top": _top_nav(_text("book.html")),
        "six_page_top": "\n".join(_top_nav(_text(page)) for page in SIX_PAGE_NAV),
        "book_internal_four": "\n".join(
            _top_nav(_text(page))
            for page in ("overview.html", "workbench.html", "memory.html", "voiceprint.html")
        ),
    }
    for label, html in surfaces.items():
        for target in HIDDEN_TARGETS:
            assert f'href="{target}' not in html, f"{label} still links to {target}"


def test_pruned_pages_still_exist_for_direct_url_access() -> None:
    for target in PRUNED_RETAINED_TARGETS:
        path = STATIC / target.removeprefix("/")
        assert path.is_file()
        assert path.stat().st_size > 0
    assert not (STATIC / "reviews.html").exists()


def test_pruned_direct_urls_still_serve() -> None:
    from fastapi.testclient import TestClient
    from biyu.ui.app import app

    client = TestClient(app)
    for target in PRUNED_RETAINED_TARGETS:
        response = client.get(target)
        assert response.status_code == 200, target
    assert client.get("/reviews.html").status_code == 404


def test_every_retained_destination_has_a_shelf_path() -> None:
    app_js = _text("app.js")
    book_html = _text("book.html")
    workbench_html = _text("workbench.html")
    assert "/book.html?book=" in app_js
    assert 'href="/workbench.html?book=' in book_html
    assert 'href="/summaries.html?book=' in book_html
    assert 'href="/overview.html?book=' in book_html
    assert 'href="/good-sentences.html?book=' in book_html
    for target in ("/memory.html", "/voiceprint.html"):
        assert f'href="{target}?book=' in book_html
    assert 'id="memory-link"' not in workbench_html
    assert 'id="voiceprint-link"' not in workbench_html
    assert 'href="/overview.html' not in workbench_html
