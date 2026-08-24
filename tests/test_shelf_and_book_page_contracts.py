from __future__ import annotations

import re
from pathlib import Path


STATIC = Path("src/biyu/ui/static")


def _genre_map(source: str) -> dict[str, str]:
    block = source.split("var GENRE_MAP = {", 1)[1].split("};", 1)[0]
    return dict(re.findall(r'^\s*([a-z0-9_]+):\s*"([^"]+)",?$', block, re.MULTILINE))


def _rule(source: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", source)
    assert match is not None, f"缺少显式样式规则：{selector}"
    return re.sub(r"\s+", "", match.group(1))


def test_every_supported_genre_code_has_a_chinese_label_and_unknown_is_not_raw() -> None:
    genre_js = (STATIC / "genre.js").read_text(encoding="utf-8")
    genre_map = _genre_map(genre_js)
    supported_codes: set[str] = set()
    for page in STATIC.glob("*.html"):
        source = page.read_text(encoding="utf-8")
        genre_selects = re.findall(
            r'<select[^>]*id="[^"]*genre[^"]*"[^>]*>(.*?)</select>',
            source,
            re.DOTALL,
        )
        for select in genre_selects:
            supported_codes.update(re.findall(r'<option value="([a-z0-9_]+)">', select))

    assert supported_codes
    assert supported_codes <= genre_map.keys(), sorted(supported_codes - genre_map.keys())
    assert all(re.search(r"[\u4e00-\u9fff]", genre_map[code]) for code in supported_codes)
    assert "return GENRE_MAP[key] || String(code)" not in genre_js
    assert 'return GENRE_MAP[key] || "未知题材"' in genre_js


def test_solid_shelf_link_keeps_centered_text_color_in_all_interaction_states() -> None:
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    expected_color = "color:var(--paper)"
    for selector in (
        ".continue-book-btn",
        ".continue-book-btn:hover",
        ".continue-book-btn:visited",
        ".continue-book-btn:focus",
    ):
        assert expected_color in _rule(styles, selector)

    default_rule = _rule(styles, ".continue-book-btn")
    assert "display:inline-flex" in default_rule
    assert "align-items:center" in default_rule
    assert "justify-content:center" in default_rule
    assert "text-align:center" in default_rule


def test_shelf_and_book_page_copy_and_click_signals_match_the_author_contract() -> None:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    book = (STATIC / "book.html").read_text(encoding="utf-8")

    assert "继续:" not in index + app_js
    assert "本次会话累计:" not in index
    assert "继续：" in index + app_js
    assert "text-decoration:underline" in _rule(styles, ".book-card .book-more-toggle")

    assert "✍" not in book
    assert "📖" not in book
    assert '<div class="entry-icon">编</div>' not in book
    assert ">复制开场白</span>" in book
    assert ">一键复制开场白</span>" not in book
    primary_rule = _rule(book, ".entry-card-primary")
    assert "width:100%" in primary_rule
    assert "align-items:center" in primary_rule
    assert "justify-content:center" in primary_rule
    assert "text-align:center" in primary_rule


def test_editor_session_controls_reuse_compact_book_page_styles() -> None:
    book = (STATIC / "book.html").read_text(encoding="utf-8")

    tools_rule = _rule(book, ".zebian-session-tools")
    hidden_rule = _rule(book, ".zebian-session-tools[hidden]")
    button_rule = _rule(book, ".zebian-session-tools button")
    assert "grid-template-columns:minmax(0,1fr)auto" in tools_rule
    assert "display:none" in hidden_rule
    assert "white-space:nowrap" in button_rule
    assert 'class="b2 bs"' in book
    assert '>新对话</button>' in book
    assert 'style="display:flex' not in book
    assert "if (event.target !== event.currentTarget) return;" in book


def test_disabled_backup_status_is_explicit_even_when_an_old_status_file_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import biyu.ui.backup as backup

    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("BIYU_BACKUP_ROOT", str(tmp_path / "backup"))
    monkeypatch.delenv("BIYU_AUTO_BACKUP", raising=False)
    status = backup.backup_status()

    assert status["state"] == "disabled"
    assert status["message"] == "备份没有开"
    assert status["enabled"] is False
