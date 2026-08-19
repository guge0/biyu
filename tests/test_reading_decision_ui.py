from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from biyu.checklist.engine import normalize


HTML = Path("src/biyu/ui/static/workbench.html")
JS = Path("src/biyu/ui/static/workbench.js")
CSS = Path("src/biyu/ui/static/styles.css")


def test_read_review_edit_skeleton_and_adoption_slip_are_present() -> None:
    html = HTML.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    script = JS.read_text(encoding="utf-8")

    for element_id in (
        "reading-state",
        "reading-check-state",
        "review-entry",
        "review-exit",
        "review-stale",
        "adopt-button",
        "adopt-gate",
        "adopt-gate-list",
        "adopt-confirm",
        "adopt-review",
    ):
        assert f'id="{element_id}"' in html
    assert "重新检查" not in html
    assert "重新检查" not in script
    assert "function setReadingView" in script
    assert "function requestAdopt" in script
    assert "function cancelIgnoreIssue" in script
    assert ".workbench .reading-layout.reading-view-read" in css
    assert ".workbench .adopt-slip-list" in css and "overflow-y:auto" in css
    assert "@media (max-width:1040px)" in css
    assert "@media (max-width:720px)" in css
    assert not re.search(r'id="diagnosis-card"[^>]*\sopen(?:\s|>)', html)


def test_frontend_quote_normalization_matches_backend_samples() -> None:
    source = JS.read_text(encoding="utf-8")
    match = re.search(
        r"(?s)(const QUOTE_NORMALIZE_RE = /.*?/[a-z]*;\s*"
        r"function normalizeQuotedText\(text\)\s*\{.*?\})\s*"
        r"function quoteStillExists",
        source,
    )
    assert match, "workbench.js must expose the small normalization function as a testable block"
    samples = [
        " 她说：\"我死过一次。\" ",
        "她说，“我死过一次”",
        "全角　空格【标记】—省略…",
        "标点不同，但字不能近似",
        "",
    ]
    node_script = (
        match.group(1)
        + "\nconsole.log(JSON.stringify("
        + json.dumps(samples, ensure_ascii=False)
        + ".map(normalizeQuotedText)));"
    )
    result = subprocess.run(
        ["node", "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert json.loads(result.stdout) == [normalize(item) for item in samples]

    quote_match = re.search(
        r"(?s)(const QUOTE_NORMALIZE_RE = /.*?/[a-z]*;\s*"
        r"function normalizeQuotedText\(text\).*?\}\s*"
        r"function quoteStillExists\(quote,text\).*?\})\s*let current",
        source,
    )
    assert quote_match
    quote_cases = [
        ["她说：我死过一次。", "前文 她说，“我死过一次” 后文"],
        ["她说我死过一次", "她说我差点死过一次"],
        ["目标原句", "相邻一段只有近似目标句"],
        ["", "任何正文"],
    ]
    quote_script = (
        quote_match.group(1)
        + "\nconsole.log(JSON.stringify("
        + json.dumps(quote_cases, ensure_ascii=False)
        + ".map(([quote,text])=>quoteStillExists(quote,text))));"
    )
    quote_result = subprocess.run(
        ["node", "-e", quote_script],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert json.loads(quote_result.stdout) == [True, False, False, False]


def test_reading_layout_keeps_three_width_contracts() -> None:
    css = CSS.read_text(encoding="utf-8")
    assert "--reading-article-width:744px" in css
    assert "--reading-review-width:360px" in css
    assert "grid-template-columns:66px minmax(504px,744px)" in css
    assert "grid-template-columns:minmax(0,1fr) var(--reading-review-width)" in css
    assert re.search(
        r"@media \(max-width:1199px\).*?\.reading-layout\.reading-aside-open"
        r" \.review-column\{[^}]*position:absolute[^}]*grid-column:1/-1[^}]*top:0"
        r"[^}]*bottom:var\(--reading-actions-height\)",
        css,
        re.S,
    )
    assert re.search(
        r"@media \(max-width:1199px\).*?\.reading-layout\.reading-aside-open"
        r" \.reading-actions-side\{[^}]*display:none",
        css,
        re.S,
    )
    assert re.search(
        r"@media \(max-width:559px\).*?\.reading-layout\.reading-aside-open"
        r" \.review-column\{[^}]*width:100%",
        css,
        re.S,
    )
    assert re.search(
        r"@media \(max-width:781px\).*?grid-template-columns:40px minmax\(504px,648px\)",
        css,
        re.S,
    )
    assert re.search(
        r"\.reading-prose-grid\{[^}]*flex:1 1 0[^}]*min-height:0"
        r"[^}]*overflow-y:auto[^}]*scrollbar-gutter:stable",
        css,
    )
    assert re.search(
        r"\.reading-layout \.reading-column\{[^}]*overflow:hidden", css
    )
    assert re.search(
        r"\.reading-layout \.reading-actions\{[^}]*position:static", css
    )
    assert not re.search(
        r"\.reading-layout \.reading-actions\{[^}]*position:sticky", css
    )
    assert re.search(
        r"\.reading-prose>#chapter-read,[^}]*height:100%[^}]*min-height:0"
        r"[^}]*max-width:744px[^}]*line-height:1\.9",
        css,
    )
    assert re.search(
        r"\.reading-prose>#chapter-read,[^}]*\.reading-prose>#official-chapter"
        r"\{[^}]*overflow:visible",
        css,
    )
    assert re.search(r"\.reading-prose>#chapter-read p,[^}]*\{[^}]*text-indent:2em", css)
    assert re.search(r"\.reading-prose>#chapter-read p,[^}]*\{[^}]*margin:0 0 1\.05em", css)
    assert re.search(
        r"\.reading-layout \.diagnosis-card\{[^}]*position:relative[^}]*bottom:auto",
        css,
    )
    assert re.search(
        r"\.reading-layout \.reading-actions\{[^}]*height:var\(--reading-actions-height\)", css
    )


def test_reading_mode_and_aside_are_orthogonal() -> None:
    html = HTML.read_text(encoding="utf-8")
    script = JS.read_text(encoding="utf-8")

    assert '>收起意见</button>' in html
    assert "let readingAsideOpen=false" in script
    assert "function setReadingAside(open" in script
    assert "setReadingAside(false)" in script
    assert "setReadingAside(true" in script
    assert "if(readingView==='edit')" in script


def test_reading_paper_dialogs_and_real_progress_contract() -> None:
    html = HTML.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    script = JS.read_text(encoding="utf-8")

    for element_id in (
        "regenerate-gate",
        "regenerate-confirm",
        "regenerate-cancel",
        "run-surface",
        "reading-failure-card",
    ):
        assert f'id="{element_id}"' in html
    assert "function requestRegenerate" in script
    assert "if(dirty.size&&!await resolveDirty())return;" in script
    assert "function progressStageFromLog" in script
    assert "正在启动…" in script
    assert "renderRunProgress(action==='rewrite'?1:0" not in script
    assert ".workbench .reading-paper-veil" in css
    assert ".workbench .reading-paper" in css


def test_checklist_status_messages_are_honest_about_version_and_unresolved() -> None:
    script = JS.read_text(encoding="utf-8")

    assert "戏核核对结果对应的是另一版正文" in script
    assert "本章戏核核对结果无版本信息，不予采用" in script
    assert "条判不了" in script
    assert "check_source_meta?.checklist" in script


def test_v6_issue_list_and_detail_contract() -> None:
    html = HTML.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    script = JS.read_text(encoding="utf-8")

    for element_id in (
        "review-list-view",
        "review-detail-view",
        "review-detail-back",
        "review-detail-position",
        "issue-detail",
        "issue-detail-selected",
        "issue-detail-prev",
        "issue-detail-next",
    ):
        assert f'id="{element_id}"' in html
    assert "let activeIssueId=''" in script
    assert "function openIssueDetail(" in script
    assert "function renderIssueDetail(" in script
    assert "function moveIssueDetail(" in script
    assert "勾选后回清单提交" in html
    assert ".workbench .issue-list-row" in css
    assert "-webkit-line-clamp:1" in css
    assert re.search(r"\.issue-list-pick\{[^}]*flex:0 0 30px", css)
    assert not re.search(r"\.issue-card\{[^}]*overflow-y\s*:\s*(?:auto|scroll)", css)
    assert ".workbench .revision-actions{position:sticky" in css
    assert re.search(r"\.workbench \.review-list-view\{[^}]*overflow-y:auto", css)
    assert re.search(
        r"\.workbench \.reading-layout \.revision-list-shell\{[^}]*flex:none"
        r"[^}]*overflow:visible",
        css,
    )
    assert re.search(r"\.workbench \.review-detail-view\{[^}]*overflow-y:auto", css)
    assert re.search(r"\.workbench \.review-toolbar\{[^}]*border-bottom:0", css)
    assert html.index('id="revision-mode"') < html.index('class="revision-actions"')
    assert re.search(
        r"\.workbench \.review-column \.sample-preview\{[^}]*border:0!important",
        css,
    )


def test_v6_more_menu_and_readonly_banner_contract() -> None:
    html = HTML.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    script = JS.read_text(encoding="utf-8")

    assert '<details class="reading-more">' not in html
    for element_id in (
        "reading-more-toggle",
        "reading-more-menu",
        "reading-readonly-tag",
    ):
        assert f'id="{element_id}"' in html
    assert "function setReadingMoreOpen(" in script
    assert "event.key==='Escape'" in script
    assert re.search(r"\.reading-more-menu\{[^}]*width:220px[^}]*overflow-y:auto", css)
    assert re.search(r"\.reading-more-menu button\{[^}]*height:36px", css)
    assert re.search(r"\.workbench>#error-banner[^}]*max-height:44px", css)
    assert re.search(r"\.reading-readonly-tag\{[^}]*font-size:", css)
    assert "HUD" not in html
    assert "看运行纸条" not in html


def test_v6_top_notice_priority_has_one_explicit_dispatcher() -> None:
    script = JS.read_text(encoding="utf-8")

    assert "function syncTopNoticePriority(" in script
    assert "['error-banner','failure-card','reading-failure-card','setup-restore-notice','replica-warning','memory-banner']" in script
    assert "syncTopNoticePriority();" in script


def test_v6_official_is_a_third_exclusive_reading_mode() -> None:
    html = HTML.read_text(encoding="utf-8")
    script = JS.read_text(encoding="utf-8")

    assert 'id="reading-mode-official"' in html
    assert 'id="official-chapter"' in html
    assert html.index('id="official-chapter"') < html.index('class="reading-prose"') + 400
    assert 'id="official-copy"' not in html
    assert 'id="reading-official-toggle"' not in html
    assert "function requestOfficialReadingView(" in script
    assert "function restoreCandidateReadingView(" in script
    assert "正在看正式稿 · 只读" in script
    assert "readingOfficialRestore" in script


def test_reading_scroll_is_owned_by_the_whole_left_pane() -> None:
    html = HTML.read_text(encoding="utf-8")
    script = JS.read_text(encoding="utf-8")

    assert 'id="reading-scroll"' in html
    assert "function readingScrollElement()" in script
    assert "chapterScroll:readingScrollElement().scrollTop" in script
    assert "readingScrollElement().scrollTop=restore?.chapterScroll||0" in script
    assert "const container=fromText?$('revision-list-shell'):readingScrollElement()" in script
    assert "$('chapter-read').scrollTop" not in script
    assert "$('official-chapter').scrollTop" not in script


def test_reading_chrome_collapses_only_for_idle_pure_reading() -> None:
    css = CSS.read_text(encoding="utf-8")
    script = JS.read_text(encoding="utf-8")

    assert "--reading-actions-height:44px" in css
    assert re.search(r"\.reading-layout\.reading-pure\{[^}]*--reading-actions-height:40px", css)
    assert re.search(r"reading-pure:not\(\[hidden\]\).*?\.stage-bar\{[^}]*position:fixed", css)
    assert re.search(r"\.reading-chrome-hidden \.reading-actions\{[^}]*transform:translateY", css)
    assert ":has(#reading-decision.reading-chrome-hidden) .stage-bar" in css
    assert re.search(r"reading-chrome-hidden[^}]*\{[^}]*transform:translateY", css)
    assert "transition:transform .18s" in css
    assert "@media (prefers-reduced-motion:reduce)" in css
    assert re.search(r"#adopt-button\{[^}]*background:none[^}]*border:1px solid var\(--stroke\)", css)
    assert re.search(r"#adopt-button:not\(:disabled\):hover.*?background:var\(--solid\)", css)
    assert re.search(r"\.revision-mode-options\{[^}]*width:max-content", css)
    assert re.search(r"\.reading-actions-main>#adopt-button\{[^}]*height:32px", css)
    assert re.search(r"\.reading-actions-main>#save-chapter\{[^}]*height:32px", css)
    assert re.search(r"#reading-more-toggle\{[^}]*height:32px", css)
    assert re.search(
        r"\.revision-mode-options label:has\(input:checked\) span"
        r"\{[^}]*color:var\(--paper\)[^}]*background:var\(--solid\)",
        css,
    )
    assert "label:focus-within{outline:2px" not in css
    assert re.search(r"label:has\(input:focus-visible\)\{[^}]*outline:1px", css)

    assert "function isPureReadingChrome()" in script
    assert "function syncReadingChromeMode()" in script
    assert "function handleReadingChromeScroll()" in script
    assert "1400" in script
    assert "scrollTop>8" in script
    assert "clientY>=window.innerHeight-90" in script


def test_narrow_reading_chrome_scrolls_horizontally_without_wrapping() -> None:
    css = CSS.read_text(encoding="utf-8")

    assert re.search(
        r"@media \(max-width:800px\).*?body:has\(\.workbench\)>\.top-nav\{[^}]*white-space:nowrap"
        r"[^}]*overflow-x:auto",
        css,
        re.S,
    )
    assert re.search(
        r"@media \(max-width:800px\).*?\.stage-bar\{[^}]*white-space:nowrap"
        r"[^}]*overflow-x:auto",
        css,
        re.S,
    )
    assert re.search(
        r"@media \(max-width:559px\).*?\.reading-layout\.reading-aside-open"
        r" \.review-column\{[^}]*width:100%",
        css,
        re.S,
    )


def test_official_mode_only_appears_as_a_candidate_comparison() -> None:
    """正式稿第三档只解决候选稿与已采用版本的对照，不重复当前正文。"""
    source = JS.read_text(encoding="utf-8")
    match = re.search(
        r"(function shouldShowOfficialMode\(snapshot\)\{.*?\})\s*(?:function|let) ",
        source,
    )
    assert match, "workbench.js must expose the official-mode state predicate"
    cases = [
        {"manuscript_state": "candidate", "official_text": "正式正文"},
        {"manuscript_state": "candidate", "official_text": ""},
        {"manuscript_state": "official", "official_text": "正式正文"},
        {"manuscript_state": "missing", "official_text": ""},
    ]
    node_script = (
        match.group(1)
        + "\nconsole.log(JSON.stringify("
        + json.dumps(cases, ensure_ascii=False)
        + ".map(shouldShowOfficialMode)));"
    )
    result = subprocess.run(
        ["node", "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert json.loads(result.stdout) == [True, False, False, False]


def test_v6_history_is_a_fifth_paper_and_legacy_bottom_blocks_are_removed() -> None:
    html = HTML.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    script = JS.read_text(encoding="utf-8")

    assert 'id="history-dialog"' in html
    assert 'id="history-list"' in html
    assert 'id="history-dialog-close"' in html
    assert 'id="history-drawer"' not in html
    assert 'id="replica-status"' not in html
    assert "function openHistoryDialog(" in script
    assert "function closeHistoryDialog(" in script
    assert re.search(r"\.history-slip\{[^}]*max-height:80vh", css)
    assert re.search(r"\.history-slip-list\{[^}]*overflow-y:auto", css)


def test_v6_missing_components_are_segmented_visible_and_single_source() -> None:
    html = HTML.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    script = JS.read_text(encoding="utf-8")

    assert 'class="revision-mode-options"' in html
    assert re.search(r"\.revision-mode-options\{[^}]*grid-template-columns:repeat\(2,max-content\)", css)
    assert re.search(r"\.revision-mode-options input\{[^}]*position:absolute[^}]*opacity:0", css)
    assert "readNum.textContent=String(current.chapter||0)" in script
    assert "const checkLine=current.check_state==='unchecked'" in script
    assert "current.check_state==='checked_with_issues'?'':" in script


def test_v6_owner_visual_rejection_keeps_actions_and_notice_in_their_own_rows() -> None:
    css = CSS.read_text(encoding="utf-8")
    script = JS.read_text(encoding="utf-8")

    assert "classList.toggle('reading-has-top-notice',visibleIndex>=0)" in script
    assert re.search(
        r"\.workbench\.reading-has-top-notice \.reading-decision-head"
        r"\{[^}]*top:calc\(52px \+ 44px\)",
        css,
    )
    assert re.search(
        r"\.reading-actions-main>button\{[^}]*align-self:center",
        css,
    )


def test_v6_owner_visual_rejection_keeps_review_entry_visible_before_1200px() -> None:
    css = CSS.read_text(encoding="utf-8")

    assert re.search(
        r"@media \(max-width:1199px\).*?"
        r"#active-voiceprint[^}]*display:none.*?"
        r"#reading-word-count[^}]*display:none",
        css,
        re.S,
    )
    assert re.search(
        r"\.reading-review-entry\{[^}]*flex:0 0 auto",
        css,
    )
    assert re.search(
        r"@media \(min-width:901px\) and \(max-width:1199px\).*?"
        r"\.reading-decision-head\{[^}]*left:350px",
        css,
        re.S,
    )
    assert re.search(
        r"@media \(min-width:801px\) and \(max-width:1199px\).*?"
        r"\.workbench-title-row \.toolbar\{[^}]*flex-wrap:nowrap",
        css,
        re.S,
    )
