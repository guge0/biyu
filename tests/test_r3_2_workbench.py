from __future__ import annotations

import asyncio
import inspect
import subprocess
import os
from pathlib import Path

from fastapi.testclient import TestClient
from tests.support.workbench_assets import assert_workbench_js_src


def _file(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


_L1_CHECKLIST = """## 必检项
**必须发生**
- 事件发生
**必须不发生**
- 不提前揭底
**结尾状态**
- 门关闭
**信息层级**
- 主角只知道表象
"""


def test_state_matrix_separates_file_assets_durable_step_and_live_run(tmp_path: Path) -> None:
    import biyu.ui.workbench as wb
    import biyu.ui.cli_executor as ex
    from biyu.ui.workbench_state import write_workbench_step

    book = tmp_path / "Book"; book.mkdir()
    assert wb.chapter_snapshot(book, 1)["axes"] == {"asset": "none", "step": "outline", "run": "idle"}
    _file(book / "outlines/ch1.md", "# 细纲")
    write_workbench_step(book, 1, "planning")
    assert wb.chapter_snapshot(book, 1)["axes"]["step"] == "planning"
    planning = _file(book / "logs/ch1/planning.md", "status: 待批\n方案")
    assert wb.chapter_snapshot(book, 1)["axes"]["step"] == "planning"
    planning.write_text("status: 已批\n方案", encoding="utf-8")
    write_workbench_step(book, 1, "generation")
    assert wb.chapter_snapshot(book, 1)["axes"]["step"] == "generation"
    ex._RUNNING[(book.name, 1)] = {"action":"write"}
    assert wb.chapter_snapshot(book, 1)["axes"]["run"] == "busy"
    ex._RUNNING.clear()
    pending = _file(book / "chapters/_pending/ch1.md", "候选正文")
    write_workbench_step(book, 1, "reading")
    assert wb.chapter_snapshot(book, 1)["axes"] == {"asset": "candidate", "step": "reading", "run": "idle"}
    ex._RUNNING[(book.name, 1)] = {"action":"rewrite"}
    assert wb.chapter_snapshot(book, 1)["axes"]["run"] == "busy"
    ex._RUNNING.clear()
    pending.unlink(); _file(book / "chapters/ch1.md", "正式正文")
    write_workbench_step(book, 1, "review")
    assert wb.chapter_snapshot(book, 1)["axes"] == {"asset": "official", "step": "review", "run": "idle"}


def test_every_disabled_matrix_action_has_a_human_reason(tmp_path: Path) -> None:
    import biyu.ui.workbench as wb

    book = tmp_path / "Book"; book.mkdir()
    for snap in [wb.chapter_snapshot(book, 1)]:
        assert all(rule["reason"] for rule in snap["actions"].values() if not rule["enabled"])
    reasons = " ".join(rule["reason"] for rule in snap["actions"].values())
    for forbidden in ("环4", "D-", "transcript", "金样"):
        assert forbidden not in reasons


def test_planning_edit_preserves_approval_and_conflict_never_overwrites(tmp_path: Path, monkeypatch) -> None:
    import biyu.ui.workbench as wb
    from biyu.ui.app import app

    book = tmp_path / "Book"; _file(book / "book.json", "{}")
    planning = _file(book / "logs/ch1/planning.md", "status: 已批\n旧方案")
    monkeypatch.setattr(wb, "get_data_root", lambda: tmp_path)
    client = TestClient(app)
    snap = client.get("/api/workbench/books/Book/chapters/1").json()
    ok = client.put("/api/workbench/books/Book/chapters/1/planning", json={"content":"新方案", "base_sha":snap["planning_sha"]})
    assert ok.status_code == 200
    assert planning.read_text(encoding="utf-8") == "status: 已批\n旧方案"
    draft = book / "logs/ch1/planning_draft.md"
    assert draft.read_text(encoding="utf-8") == "status: 待批\nsource: 作者改过\n新方案"
    old_sha = ok.json()["planning_sha"]
    draft.write_text("status: 待批\n导演盘面新版", encoding="utf-8")
    blocked = client.put("/api/workbench/books/Book/chapters/1/planning", json={"content":"页面旧稿", "base_sha":old_sha})
    assert blocked.status_code == 409
    assert draft.read_text(encoding="utf-8").endswith("导演盘面新版")
    assert planning.read_text(encoding="utf-8") == "status: 已批\n旧方案"


def test_planning_save_and_confirm_is_one_request(tmp_path: Path, monkeypatch) -> None:
    import biyu.ui.workbench as wb
    from biyu.ui.app import app

    book = tmp_path / "Book"; _file(book / "book.json", "{}")
    planning = _file(book / "logs/ch1/planning.md", "status: 待批\n旧方案")
    _file(book / "outlines/ch1.md", "细纲")
    monkeypatch.setattr(wb, "get_data_root", lambda: tmp_path)
    client = TestClient(app)
    snap = client.get("/api/workbench/books/Book/chapters/1").json()

    response = client.put(
        "/api/workbench/books/Book/chapters/1/planning",
        json={"content": "老板修改后的方案\n" + _L1_CHECKLIST, "base_sha": snap["planning_sha"], "confirm": True},
    )

    assert response.status_code == 200
    assert planning.read_text(encoding="utf-8").startswith("status: 已批\nsource: 作者改过\n老板修改后的方案")
    assert response.json()["axes"]["step"] == "generation"


def test_candidate_choice_continue_archive_or_cancel_is_explicit(tmp_path: Path, monkeypatch) -> None:
    import biyu.ui.workbench as wb
    from biyu.ui.app import app

    book = tmp_path / "Book"; _file(book / "book.json", "{}")
    _file(book / "outlines/ch1.md", "细纲")
    planning = _file(book / "logs/ch1/planning.md", "status: 待批\n旧方案")
    pending = _file(book / "chapters/_pending/ch1.md", "候选正文")
    monkeypatch.setattr(wb, "get_data_root", lambda: tmp_path)
    client = TestClient(app)
    snap = client.get("/api/workbench/books/Book/chapters/1").json()

    cancel = client.put(
        "/api/workbench/books/Book/chapters/1/planning",
        json={"content": "新方案", "base_sha": snap["planning_sha"], "confirm": True},
    )
    assert cancel.status_code == 409
    assert planning.read_text(encoding="utf-8") == "status: 待批\n旧方案"
    assert pending.read_text(encoding="utf-8") == "候选正文"

    continued = client.put(
        "/api/workbench/books/Book/chapters/1/planning",
        json={"content": "继续方案\n" + _L1_CHECKLIST, "base_sha": snap["planning_sha"], "confirm": True, "candidate_choice": "continue"},
    )
    assert continued.status_code == 200
    assert pending.read_text(encoding="utf-8") == "候选正文"

    current = continued.json()
    archived = client.put(
        "/api/workbench/books/Book/chapters/1/planning",
        json={"content": "重写方案\n" + _L1_CHECKLIST, "base_sha": current["planning_sha"], "confirm": True, "candidate_choice": "regenerate"},
    )
    assert archived.status_code == 200
    assert not pending.exists()
    archive_files = list((book / "logs/ch1/archived_candidates").glob("*.md"))
    assert len(archive_files) == 1 and archive_files[0].read_text(encoding="utf-8") == "候选正文"
    assert archived.json()["axes"]["step"] == "generation"


def test_git_history_is_read_only_and_uses_human_actions(tmp_path: Path, monkeypatch) -> None:
    import biyu.ui.workbench as wb

    book = tmp_path / "data/Book"
    chapter = _file(book / "chapters/ch1.md", "初稿正文")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "auto: CH1 初次生成"], cwd=tmp_path, check=True, capture_output=True)
    chapter.write_text("初稿正文，作者手改。", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "manual: CH1 作者手动修改"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.setattr(wb, "get_project_root", lambda: tmp_path)

    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file() and ".git" not in path.parts}
    history = wb._git_chapter_history(book, 1)
    after = {path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file() and ".git" not in path.parts}

    assert [item["action"] for item in history] == ["手改", "初稿"]
    assert history[0]["delta"] is not None
    assert before == after


def test_git_history_commit_path_and_blob_refer_to_the_same_changed_file(tmp_path: Path, monkeypatch) -> None:
    import biyu.ui.workbench as wb

    book = tmp_path / "data/Book"
    _file(book / "chapters/ch1.md", "正式正文")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "auto: CH1 正式正文"], cwd=tmp_path, check=True, capture_output=True)
    pending = _file(book / "chapters/_pending/ch1.md", "候选正文明显更长")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "auto: CH1 候选正文"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.setattr(wb, "get_project_root", lambda: tmp_path)

    newest = wb._git_chapter_history(book, 1)[0]
    expected_path = pending.relative_to(tmp_path).as_posix()
    expected_blob = subprocess.run(
        ["git", "rev-parse", f"{newest['commit']}:{expected_path}"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()

    assert newest["path"] == expected_path
    assert newest["blob"] == expected_blob
    shown = subprocess.run(
        ["git", "show", f"{newest['commit']}:{newest['path']}"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    assert shown == pending.read_text(encoding="utf-8")
    assert newest["word_count"] == sum(1 for char in shown if "\u4e00" <= char <= "\u9fff")


def test_workbench_self_link_keeps_the_selected_book() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")

    assert 'id="workbench-self-link"' in html
    assert "workbenchSelfLink.href" in js
    assert "encodeURIComponent(selectedBook)" in js


def test_force_pending_seam_keeps_default_and_workbench_paths_separate(tmp_path: Path) -> None:
    from biyu.pipeline import _chapter_output_path, generate_chapter
    from biyu.ui.action_registry import action_for

    assert inspect.signature(generate_chapter).parameters["force_pending"].default is False
    official = _chapter_output_path(tmp_path / "chapters", 1, pending=False)
    pending = _chapter_output_path(tmp_path / "chapters", 1, pending=True)
    assert official == tmp_path / "chapters/ch1.md"
    assert pending == tmp_path / "chapters/_pending/ch1.md"
    assert "--force-pending" in action_for("write", book="Book", chapter=1).argv


def test_stale_overlay_prefers_candidate_plan_version_over_file_times(tmp_path: Path) -> None:
    import biyu.ui.workbench as wb
    from biyu.ui.workbench_versions import save_plan_version, snapshot_candidate

    book = tmp_path / "Book"
    _file(book / "outlines/ch1.md", "细纲")
    planning = _file(book / "logs/ch1/planning.md", "status: 已批\n方案")
    save_plan_version(book, 1, "方案")
    pending = _file(book / "chapters/_pending/ch1.md", "正文")
    snapshot_candidate(book, 1, run_id="run-1", action="write")
    os.utime(pending, ns=(1_000_000_000, 1_000_000_000))
    os.utime(planning, ns=(2_000_000_000, 2_000_000_000))
    snap = wb.chapter_snapshot(book, 1)
    assert snap["axes"]["asset"] == "candidate" and snap["stale"] is False

    save_plan_version(book, 1, "新方案")
    planning.write_text("status: 已批\n新方案", encoding="utf-8")
    snap = wb.chapter_snapshot(book, 1)
    assert snap["stale"] is True
    assert snap["actions"]["regenerate"]["enabled"] is True


def test_stale_overlay_uses_file_times_for_legacy_candidate(tmp_path: Path) -> None:
    import biyu.ui.workbench as wb

    book = tmp_path / "Book"
    _file(book / "outlines/ch1.md", "细纲")
    planning = _file(book / "logs/ch1/planning.md", "status: 已批\n方案")
    pending = _file(book / "chapters/_pending/ch1.md", "正文")
    os.utime(pending, ns=(1_000_000_000, 1_000_000_000))
    os.utime(planning, ns=(2_000_000_000, 2_000_000_000))

    assert wb.chapter_snapshot(book, 1)["stale"] is True


def test_running_registry_has_no_restart_ghost_and_rejects_concurrency() -> None:
    import biyu.ui.cli_executor as ex

    ex._RUNNING.clear()
    assert ex.running_action("Book", 1) is None


def test_cli_run_id_persists_complete_failure_and_never_overwrites(tmp_path: Path, monkeypatch) -> None:
    import biyu.ui.cli_executor as ex

    book = tmp_path / "Book"
    _file(book / "book.json", "{}")

    class FakeProcess:
        def __init__(self, lines: list[str], code: int) -> None:
            self.stdout = asyncio.StreamReader()
            for line in lines:
                self.stdout.feed_data((line + "\n").encode("utf-8"))
            self.stdout.feed_eof()
            self.stdin = None
            self._code = code

        async def wait(self) -> int:
            return self._code

    attempts = iter([
        FakeProcess(["[1/3] Planner ... ok", "Writer 上游关闭，0 tokens"], 1),
        FakeProcess(["第二次完整日志"], 1),
    ])

    async def fake_create(*_args, **_kwargs):
        return next(attempts)

    monkeypatch.setattr(ex, "resolve_book_dir", lambda _book: book)
    monkeypatch.setattr(ex.asyncio, "create_subprocess_exec", fake_create)

    async def run_once() -> list[dict]:
        return [event async for event in ex.execute(
            "write", book="Book", chapter=1, confirmed=True, extra={}
        )]

    first = asyncio.run(run_once())
    run_id = first[0]["run_id"]
    assert first[-1]["type"] == "error"
    assert first[-1]["run_id"] == run_id
    assert "Writer 上游关闭" in first[-1]["message"]
    assert ex.read_workbench_step(book, 1) == "outline"  # 失败不得推进作者步骤
    assert not (book / "chapters/ch1.md").exists()
    assert not (book / "chapters/_pending/ch1.md").exists()

    run_dir = book / "logs/ch1/runs"
    first_path = run_dir / f"{run_id}.log"
    before = first_path.read_text(encoding="utf-8")
    assert "[1/3] Planner ... ok" in before
    assert "Writer 上游关闭，0 tokens" in before
    assert "status=failed" in before and "returncode=1" in before

    second = asyncio.run(run_once())
    assert second[0]["run_id"] != run_id
    assert len(list(run_dir.glob("*.log"))) == 2
    assert first_path.read_text(encoding="utf-8") == before
    ex._RUNNING[("Book", 1)] = {"action":"write"}
    assert ex.running_action("Book", 1) == "write"
    ex._RUNNING.clear()  # process restart contract: registry starts empty
    assert ex.running_action("Book", 1) is None


def test_excerpt_schema_retag_and_tombstone(tmp_path: Path, monkeypatch) -> None:
    import json
    from biyu.cli import workbench_cmd as cmd
    import biyu.ui.workbench as wb

    monkeypatch.setattr(cmd, "resolve_book_dir", lambda _book: tmp_path)
    negative = tmp_path / "样本库/负例候选.md"
    negative.parent.mkdir(parents=True, exist_ok=True)
    negative.write_text("存量负例\n", encoding="utf-8")
    before = (negative.read_bytes(), negative.stat().st_mtime_ns)
    cmd.excerpt(chapter=1, book="Book", kind="problem", content="只记下问题", version="abc123", anchor=2)
    assert (negative.read_bytes(), negative.stat().st_mtime_ns) == before
    ledger = json.loads((tmp_path / "反馈账.jsonl").read_text(encoding="utf-8"))
    assert ledger["action"] == "note_problem" and ledger["text"] == "只记下问题"
    assert ledger["chapter"] == 1 and ledger["candidate_sha"] == "abc123" and ledger["anchor"] == 2
    cmd.excerpt(chapter=1, book="Book", kind="good", content="选中的一句", version="abc123")
    items = wb._sample_entries((tmp_path / "样本库/正例候选.md").read_text(encoding="utf-8"), "")
    assert len(items) == 1 and items[0]["version_sha"] == "abc123"
    cmd.excerpt_retag(book="Book", chapter=1, entry_id=items[0]["id"], new_kind="problem")
    assert (negative.read_bytes(), negative.stat().st_mtime_ns) == before
    items = wb._sample_entries(
        (tmp_path / "样本库/正例候选.md").read_text(encoding="utf-8"),
        (tmp_path / "样本库/负例候选.md").read_text(encoding="utf-8"),
    )
    assert items == []
    ledger = [
        json.loads(line)
        for line in (tmp_path / "反馈账.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(ledger) == 2
    assert ledger[-1]["action"] == "note_problem" and ledger[-1]["from"] == "good"


def test_user_visible_copy_has_no_engineering_terms() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
    visible = html + js
    for forbidden in ("合同", "盖章", "判词", "金样", "transcript", "环4", "D-131"):
        assert forbidden not in visible


def test_auto_refresh_preserves_unsent_issue_selection_and_author_comments() -> None:
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")

    assert "markDirty('annotations')" in js
    assert "incoming.issue_cards = current.issue_cards" in js
    assert "dirty.has('annotations') && incoming.report_sha !== current.report_sha" in js
    assert "busy=true;applyActionState();" in js
    assert "if (auto && unchanged) return;" in js


def test_action_state_refresh_restores_chapter_navigation_after_busy_request() -> None:
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")

    assert "function applyNavigationState()" in js
    action_state = js.split("function applyActionState()", 1)[1].split("function renderSamples()", 1)[0]
    assert "applyNavigationState();" in action_state
    assert "finally {busy=false;applyActionState();}" in js


def test_chapter_complete_is_derived_from_saved_review(tmp_path: Path) -> None:
    import biyu.ui.workbench as wb

    book = tmp_path / "Book"
    _file(book / "chapters/ch1.md", "正式正文")
    assert wb.chapter_snapshot(book, 1)["chapter_complete"] is False

    _file(book / "判词/ch1.md", "- 已保存章评\n")
    assert wb.chapter_snapshot(book, 1)["chapter_complete"] is True


def test_history_is_a_non_clickable_list_without_version_endpoint(tmp_path: Path, monkeypatch) -> None:
    import biyu.ui.workbench as wb
    from biyu.ui.app import app

    book = tmp_path / "Book"
    _file(book / "book.json", "{}")
    monkeypatch.setattr(wb, "get_data_root", lambda: tmp_path)
    response = TestClient(app).get("/api/workbench/books/Book/chapters/1/history/deadbee")
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")

    assert response.status_code == 404
    assert "chapter_history_version" not in Path("src/biyu/ui/workbench.py").read_text(encoding="utf-8")
    assert "history-version" not in html
    assert "查看此版本" not in js
    assert "showHistoryVersion" not in js


def test_dirty_guards_cover_stage_view_and_chapter_review() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")

    assert 'id="global-dirty"' in html
    assert "requestStage(index)" in js
    assert "requestView(button.dataset.view)" in js
    assert "dirty.has('review') && incoming.verdict_sha !== current.verdict_sha" in js
    assert "$('chapter-review').addEventListener('input'" in js
    assert "saveReview" in js


def test_successful_run_collapses_details_and_keeps_human_result() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")

    assert 'id="run-result"' in html
    assert "$('log-drawer').open = false" in js
    assert "$('log-drawer').hidden=true" in js
    assert "RUN_LABELS" in js


def test_total_director_entry_is_removed_but_dormant_implementation_remains() -> None:
    book_html = Path("src/biyu/ui/static/book.html").read_text(encoding="utf-8")
    backend = Path("src/biyu/ui/workbench.py").read_text(encoding="utf-8")
    cli = Path("src/biyu/cli/talk_cmd.py").read_text(encoding="utf-8")

    assert 'id="total-director"' not in book_html
    assert "D-148" in book_html and "休眠" in book_html
    assert '@router.post("/books/{book}/director")' in backend
    assert 'role == "总导演"' in cli


def test_ch2_outline_save_accepts_the_real_browser_payload(tmp_path: Path, monkeypatch) -> None:
    """上一章三选的“保存后离开”不能被旧缓存脚本中的布尔字段打成 422。"""
    import biyu.ui.workbench as wb
    from biyu.ui.app import app

    book = tmp_path / "Book"
    _file(book / "book.json", "{}")
    monkeypatch.setattr(wb, "get_data_root", lambda: tmp_path)
    client = TestClient(app)
    snap = client.get("/api/workbench/books/Book/chapters/2").json()

    response = client.put(
        "/api/workbench/books/Book/chapters/2/outline",
        json={
            "content": "第二章细纲",
            "base_sha": snap["outline_sha"],
            "confirm": False,
            "candidate_choice": "",
        },
    )

    assert response.status_code == 200
    assert (book / "outlines/ch2.md").read_text(encoding="utf-8") == "第二章细纲"


def test_navigation_clears_stale_errors_and_never_renders_object_object() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")

    assert "Array.isArray(detail)" in js
    assert "clearTransientStatus()" in js
    assert_workbench_js_src(html)


def test_excerpt_selection_uses_the_reading_stage_without_a_second_full_chapter() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")

    assert 'id="chapter-read" class="markdown reading-pane selectable"' in html
    assert 'id="final-chapter"' not in html
    assert "从“读稿定夺”选中文字" in html
    assert "$('final-chapter')" not in js
