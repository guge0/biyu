from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
JS = (ROOT / "src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
CSS = (ROOT / "src/biyu/ui/static/styles.css").read_text(encoding="utf-8")


def css_number(name: str) -> float:
    match = re.search(rf"{re.escape(name)}:([\d.]+)px", CSS)
    assert match, f"missing CSS budget token {name}"
    return float(match.group(1))


def css_integer(name: str) -> int:
    match = re.search(rf"{re.escape(name)}:(\d+)(?:;|\}})", CSS)
    assert match, f"missing CSS integer token {name}"
    return int(match.group(1))


def test_header_height_budget():
    fixed = sum(
        css_number(name)
        for name in (
            "--workbench-topbar",
            "--workbench-title-row",
            "--workbench-step-row",
            "--workbench-stage-gap",
        )
    )
    assert fixed <= 180
    title_row = re.search(
        r'<header class="workbench-header workbench-title-row [^"]+">(?P<body>.*?)</header>',
        HTML,
        re.S,
    )
    assert title_row
    assert 'id="entry-status"' in title_row.group("body")
    # W-1：工具条按目标结构改 .toolbar（原 chapter-picker 类名废止）
    assert 'class="toolbar workbench-chapter-nav"' in title_row.group("body")


def test_prose_visible_lines():
    # S-1 规范：正文 18px / 行距 2.1 → 行高 37.8px；一屏 14 行
    assert css_number("--prose-line-height") == 37.8
    assert css_integer("--prose-normal-lines") == 14
    assert css_number("--prose-normal-height") == 529.2
    assert re.search(
        r"\.reading-column>#chapter-read,.reading-column>#chapter-edit"
        r"\{[^}]*min-height:var\(--prose-normal-height\)",
        CSS,
    )


def test_interruption_state_line_budgets():
    assert css_integer("--prose-interrupted-lines") == 6
    assert css_number("--prose-interrupted-height") == 226.8
    assert css_integer("--prose-collapsed-lines") == 9
    assert css_number("--prose-collapsed-height") == 340.2
    assert re.search(
        r"\.reading-column:has\(\.reading-interruption:not\(\[hidden\]\)\)"
        r">#chapter-read\{[^}]*min-height:var\(--prose-interrupted-height\)",
        CSS,
    )
    assert re.search(
        r"\.reading-column:has\(\.diagnosis-card:not\(\[hidden\]\):not\(\[open\]\)\)"
        r">#chapter-read\{[^}]*min-height:var\(--prose-collapsed-height\)",
        CSS,
    )


def test_stage_fills_viewport():
    assert re.search(
        r"\.workbench \.stage-shell\{[^}]*flex:1[^}]*min-height:0[^}]*position:relative",
        CSS,
    )
    assert re.search(
        r"\.workbench \.reading-layout\{[^}]*height:100%[^}]*grid-template-columns:",
        CSS,
    )
    assert re.search(
        r"\.workbench \.reading-column,.workbench \.review-column"
        r"\{[^}]*height:100%[^}]*box-sizing:border-box",
        CSS,
    )


def test_right_pane_card_and_actions_coexist():
    pane = re.search(
        r'<aside class="review-column">(?P<body>.*?)</aside>',
        HTML,
        re.S,
    )
    assert pane
    body = pane.group("body")
    assert 'class="review-toolbar"' in body
    assert body.index('id="issue-list"') < body.index('class="revision-actions"')
    assert re.search(
        r"\.workbench \.revision-actions\{[^}]*position:sticky[^}]*bottom:0"
        r"[^}]*isolation:isolate",
        CSS,
    )


def test_no_overlap_in_right_pane():
    assert "margin-top:-" not in CSS
    assert "overflow:hidden" not in re.search(
        r"\.workbench \.review-column\{(?P<body>[^}]*)\}",
        CSS,
    ).group("body")
    assert re.search(
        r"\.workbench \.issue-card\{[^}]*position:relative[^}]*z-index:1",
        CSS,
    )


def test_book_chapter_controls_present():
    title_match = re.search(
        r'<header class="workbench-header workbench-title-row [^"]+">(?P<body>.*?)</header>',
        HTML,
        re.S,
    )
    title_row = title_match.group("body")
    for element_id in ("book", "chapter", "previous-chapter", "next-chapter"):
        assert f'id="{element_id}"' in title_row
    assert 'workbench-command-row' in title_match.group(0)
    assert 'id="load"' not in title_row
    assert 'id="stage-bar"' in title_row
    assert 'id="workbench-more-toggle"' in title_row
    assert "$('load').onclick" not in JS
    assert "$('previous-chapter').onclick" in JS
    assert "$('next-chapter').onclick" in JS
    assert "$('chapter').addEventListener('change'" in JS


def test_step_nav_disabled_reason_preserved():
    assert "button.setAttribute('aria-disabled', locked ? 'true' : 'false')" in JS
    assert "showNotice(button.title)" in JS
    assert "完成前一阶段后自动解锁" in JS
    assert re.search(
        r"\.workbench \.stage-button\{[^}]*background:transparent[^}]*border-bottom:",
        CSS,
    )


def test_step_nav_remains_keyboard_focusable():
    assert "document.createElement('button')" in JS
    assert "button.disabled = index > current.stage" not in JS
    assert "button.tabIndex = 0" in JS
    assert 'aria-label="写作阶段"' in HTML


def test_interruptions_stay_inside_reading_surface():
    reading_start = HTML.index('<section class="reading-column">')
    review_start = HTML.index('<aside class="review-column">', reading_start)
    reading_body = HTML[reading_start:review_start]
    assert 'id="diagnosis-card"' in reading_body
    assert 'id="reading-failure-card"' in reading_body
    assert re.search(
        r'<div id="run-surface" class="run-surface[^"]*" hidden>.*?'
        r'id="run-progress".*?id="run-result".*?id="log-drawer"',
        HTML,
        re.S,
    )
    assert re.search(
        r"\.workbench \.run-surface\{[^}]*position:absolute[^}]*inset:0"
        r"[^}]*z-index:",
        CSS,
    )


def test_persisted_busy_state_reopens_run_surface():
    assert "function renderPersistedRunState()" in JS
    assert "if(current.axes?.run!=='busy'||busy)return" in JS
    assert "$('run-surface').hidden=false" in JS
    assert "renderPersistedRunState();" in JS
    assert "clearTransientStatus();await fetchSnapshot()" in JS


def test_running_card_keeps_reading_surface_readable():
    run_surface = re.search(
        r"\.workbench \.run-surface\{(?P<body>[^}]*)\}",
        CSS,
    )
    assert run_surface
    assert "background:transparent" in run_surface.group("body")
    assert "pointer-events:none" in run_surface.group("body")
    assert re.search(
        r"\.stage-shell:has\(\.reading-layout:not\(\[hidden\]\)\) "
        r"\.run-surface\{[^}]*right:",
        CSS,
    )
    assert ".workbench .run-card{pointer-events:auto;" in CSS


def test_running_card_shows_only_the_truthful_current_progress_stage():
    for label in ("规划结构", "写手生成正文", "字数与本地检查", "编辑审读", "规则核查", "保存候选稿"):
        assert label in JS
    for obsolete in ("打包本轮意见", "写手改稿", "编辑复审", "落盘新候选版"):
        assert obsolete not in JS
    assert "const stages=[label||'正在启动…']" in JS
    assert "本章正在处理中，进度正在写入日志" not in JS
    assert 'id="run-elapsed"' in HTML
    assert 'class="run-foot"' in HTML
    assert "function renderRunProgress(" in JS
    assert "function updateRunElapsed()" in JS
    assert ".run-card .progress-item.pi-active .pi-icon" in CSS


def test_busy_state_does_not_repeat_disabled_reasons_through_card():
    assert "const running=busy||current.axes?.run==='busy'" in JS
    assert "el.textContent=running?'':" in JS


def test_long_prose_scrolls_without_bleeding_under_actions():
    reading_column = re.search(
        r"\.workbench \.reading-column\{(?P<body>[^}]*)\}",
        CSS,
    )
    assert reading_column
    assert "overflow-y:hidden" in reading_column.group("body")
    assert re.search(
        r"\.reading-column>#chapter-read,.reading-column>#chapter-edit"
        r"\{[^}]*flex:1 1 var\(--prose-normal-height\)"
        r"[^}]*overflow-y:auto",
        CSS,
    )
    assert ".workbench .reading-column>.action-row{flex:none" in CSS
    assert "const container=fromText?$('revision-list-shell'):readingScrollElement()" in JS
    assert "$('chapter-read').scrollTop" not in JS


def test_saved_excerpts_can_be_opened_before_adoption():
    assert "function canOpenStage(index)" in JS
    assert "index===4&&((current.samples||[]).length>0||current.actions?.excerpt?.enabled)" in JS
    assert "查看已记录摘句；采用为正式正文后可保存章评" in JS
    assert "采用为正式正文后才能保存章评" in JS
    assert "showNotice(button.title)" in JS
    assert ".workbench .notice-banner" in CSS
