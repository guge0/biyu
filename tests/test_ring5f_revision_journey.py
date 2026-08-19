import json
import re
from pathlib import Path

import pytest

from biyu.ui.workbench import _validate_visible_selection


HTML = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
JS = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
CSS = Path("src/biyu/ui/static/styles.css").read_text(encoding="utf-8")


def test_url_syncs_on_navigate():
    assert "function syncWorkbenchLocation()" in JS
    assert "params.set('book',$('book').value)" in JS
    assert "params.set('chapter',String(current.chapter))" in JS
    assert "history.replaceState(null,'',`/workbench.html?${params}`)" in JS
    assert "await fetchSnapshot();syncWorkbenchLocation();" in JS


def test_reload_restores_book_and_chapter():
    assert "function locationDraftKey(book)" in JS
    assert "localStorage.setItem(locationDraftKey(book),String(current.chapter))" in JS
    assert "params.get('chapter')||localStorage.getItem(locationDraftKey(wanted))||'1'" in JS
    assert "memoryLink.href=`/memory.html?book=${encodedBook}&chapter=${chapter}`" in JS


def test_missing_book_falls_back_visibly():
    assert "const requestedBook=params.get('book')" in JS
    assert "data.books.some(item=>item.id===requestedBook)" in JS
    assert "showNotice(`找不到书籍“${requestedBook}”，已回到${fallbackName}`)" in JS


def test_no_native_prompt():
    assert "prompt(" not in JS
    tools = re.search(r'<div id="selection-tools".*?</div>', HTML, re.S)
    assert tools
    for label in ("让写手改这句", "记下问题（暂不修改）", "记为好句"):
        assert label in tools.group(0)
    assert "两个都要" not in tools.group(0)


def test_selection_card_appears_immediately():
    assert "function revisionQueue()" in JS
    assert "return [...revisionLines,...(current.issue_cards||[])]" in JS
    assert "row.className='issue-list-row'" in JS
    assert "card.source==='author_selection'" in JS
    assert "renderIssues();persistRevisionDraft();markDirty('annotations')" in JS


def test_selection_card_editable_removable():
    for label in ("我划的", "编辑提出", "这条送去返修", "定位正文", "移除"):
        assert label in JS
    assert "revisionLines=revisionLines.filter(item=>item.id!==card.id)" in JS
    assert "card.author_comment=comment.value" in JS
    assert "updateRevisionCount()" in JS


def test_selection_draft_survives_reload():
    assert "function revisionDraftKey()" in JS
    assert "${$('book').value}:${current.chapter}:${current.chapter_sha}" in JS
    assert "localStorage.setItem(revisionDraftKey(),JSON.stringify(revisionLines))" in JS
    assert "const saved=JSON.parse(localStorage.getItem(revisionDraftKey())||'[]')" in JS


def test_package_matches_visible_selection():
    assert "function visibleSelectedCards()" in JS
    assert "const selected=visibleSelectedCards()" in JS
    assert "visible_selected_ids:selected.map(card=>card.id)" in JS
    assert "selected_issue_ids:selected.filter(card=>card.source!=='author_selection').map(card=>card.id)" in JS
    assert "revision_problem_lines:selected.filter(card=>card.source==='author_selection')" in JS
    _validate_visible_selection(
        ["editor-1"], [{"id": "manual-1"}], ["manual-1", "editor-1"]
    )
    with pytest.raises(ValueError, match="界面可见"):
        _validate_visible_selection(
            ["editor-1"], [{"id": "manual-hidden"}], ["editor-1"]
        )


def test_package_persists_exact_visible_selection(tmp_path):
    from biyu.audit_reports.revisions import create_revision_package, text_sha

    candidate = "候选正文"
    (tmp_path / "chapters/_pending").mkdir(parents=True)
    (tmp_path / "chapters/_pending/ch1.md").write_text(candidate, encoding="utf-8")
    (tmp_path / "logs/ch1").mkdir(parents=True)
    (tmp_path / "logs/ch1/planning.md").write_text("方案", encoding="utf-8")
    (tmp_path / "audit_reports").mkdir()
    (tmp_path / "audit_reports/ch1.json").write_text(
        json.dumps({"issues": [{"id": "editor-1", "description": "编辑问题"}]}),
        encoding="utf-8",
    )
    visible_ids = ["manual-1", "editor-1"]
    _validate_visible_selection(
        ["editor-1"], [{"id": "manual-1"}], visible_ids
    )
    package = create_revision_package(
        tmp_path,
        1,
        selected_issue_ids=["editor-1"],
        issue_comments={"editor-1": "编辑批注"},
        general_comment="",
        candidate_sha=text_sha(candidate),
        revision_problem_lines=[
            {
                "id": "manual-1",
                "text": "作者划句",
                "anchor": 2,
                "author_comment": "作者批注",
            }
        ],
        mode="local_revision",
    )
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    issues = json.loads((package / "issues.json").read_text(encoding="utf-8"))
    assert len(manifest["selected_issue_ids"]) == len(visible_ids)
    assert set(manifest["selected_issue_ids"]) == set(visible_ids)
    assert len(issues) == len(visible_ids)
    assert {item["id"] for item in issues} == set(visible_ids)


def test_right_pane_hierarchy():
    assert 'id="revision-list-shell"' in HTML
    assert '<summary>整体意见' in HTML
    assert '<summary>原始审读报告' in HTML
    assert 'id="revision-count"' in HTML
    assert 'id="completed-count"' in HTML
    assert ".workbench .revision-list-shell{flex:1;min-height:0;overflow-y:auto" in CSS


def test_review_cards_restore_bulk_selection_from_v3_prototype():
    assert 'id="revision-select-all"' in HTML
    assert 'id="revision-clear-all"' in HTML
    assert "function setRevisionSelection(selected)" in JS
    assert "revisionQueue().forEach(card=>{if(!card.ignored)card.selected=selected;})" in JS
    assert "persistRevisionDraft();markDirty('annotations');renderIssues();" in JS
    assert "$('revision-select-all').onclick=()=>setRevisionSelection(true)" in JS
    assert "$('revision-clear-all').onclick=()=>setRevisionSelection(false)" in JS


def test_excerpt_receipt_names_destination_without_redundant_button():
    # 读稿页收敛 B2:顶部重复按钮已删,只剩右栏折叠行
    assert 'id="sample-shortcut"' not in HTML
    assert 'id="sample-shortcut-good"' not in HTML
    assert 'id="sample-shortcut-problem"' not in HTML
    assert 'id="sample-preview"' in HTML
    assert 'id="sample-preview-list"' in HTML
    assert "记下问题（暂不修改）" in HTML
    assert "记为好句" in HTML
    assert "function showExcerptReceipt(kind)" in JS
    assert "openSamplePreview" not in JS
    assert "已记下问题，暂不修改本章；见右栏「本章记录」。" in JS
    assert "已记为好句；见右栏「本章记录」。" in JS
    assert "在本页查看" not in JS
    assert "sample-shortcut" not in JS
    assert "appendFeedback(action)" in JS
    assert "await stream('excerpt'" not in JS
    receipt = JS[JS.index("function showExcerptReceipt"):JS.index("function canOpenStage")]
    assert "openSamplePreview" not in receipt


def test_footer_not_covering_last_card():
    assert re.search(
        r"\.workbench \.review-column\{[^}]*overflow-y:hidden",
        CSS,
    )
    assert HTML.index('id="revision-list-shell"') < HTML.index('class="revision-actions"')
    assert re.search(r"\.workbench \.revision-actions\{[^}]*position:sticky[^}]*bottom:0", CSS)
    assert "提交本轮修改（${selected.length} 项）" in JS
    assert "$('review-position').textContent=" not in JS
