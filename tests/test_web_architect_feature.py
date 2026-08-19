from __future__ import annotations

from pathlib import Path

import pytest


VALID_PLAN = """# 第九章 创作者细纲

## 必检项
- **必须发生**：姜聆当众复述登记簿结论
- **必须不发生**：不揭晓回溯原因
- **结尾状态**：马文把封存刀放上验尸台
- **信息层级**：先公开追问，再私下识刀
"""


@pytest.fixture
def plan_book(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from biyu.ui import workbench

    book = tmp_path / "Book"
    (book / "outlines").mkdir(parents=True)
    (book / "logs" / "ch9").mkdir(parents=True)
    (book / "book.json").write_text(
        '{"id":"book","title":"Book","genre":"dushi"}', encoding="utf-8"
    )
    (book / "outlines" / "ch9.md").write_text("第九章细纲", encoding="utf-8")
    monkeypatch.setattr(workbench, "_book_dir", lambda _book: book)
    return book


def test_feature_defaults_off_but_can_be_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from biyu.ui import workbench

    class Registry:
        enabled = False

        def get_feature(self, _name: str) -> bool:
            return self.enabled

    registry = Registry()
    monkeypatch.setattr(workbench, "get_registry", lambda: registry)
    assert workbench._web_architect_enabled() is False
    registry.enabled = True
    assert workbench._web_architect_enabled() is True


def test_controlled_example_defaults_web_architect_on_after_owner_acceptance() -> None:
    example = Path("config/models.yaml.example").read_text(encoding="utf-8")
    assert "  web_architect: true" in example


def test_old_chapter_director_button_is_deleted() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
    assert "打开本章导演" not in html
    assert 'data-action="talk"' not in html
    assert "action==='talk'" not in js
    assert 'id="run-architect"' in html


@pytest.mark.asyncio
async def test_old_chapter_talk_action_is_retired() -> None:
    from fastapi import HTTPException
    from biyu.ui import workbench

    with pytest.raises(HTTPException) as exc:
        await workbench.run_action("book", 9, "talk", {})
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_degraded_output_never_overwrites_existing_plan(
    plan_book: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from biyu.ui import workbench

    path = plan_book / "logs/ch9/planning.md"
    path.write_text("status: 待批\nsource: 作者手写\n盘上旧方案", encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    monkeypatch.setattr(workbench, "_web_architect_enabled", lambda: True)

    async def degraded(*_args, **_kwargs):
        return workbench.WebArchitectResult(VALID_PLAN, 0.01, "degraded")

    monkeypatch.setattr(workbench, "_call_web_architect", degraded)
    result = await workbench.generate_planning_with_architect("book", 9)

    assert result["state"] == "rejected"
    assert path.read_text(encoding="utf-8") == before


@pytest.mark.asyncio
async def test_incomplete_output_is_rejected_without_overwriting(
    plan_book: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from biyu.ui import workbench

    path = plan_book / "logs/ch9/planning.md"
    path.write_text("status: 待批\nsource: 作者手写\n盘上旧方案", encoding="utf-8")
    monkeypatch.setattr(workbench, "_web_architect_enabled", lambda: True)
    monkeypatch.setattr(
        workbench, "_call_web_architect", lambda *_args, **_kwargs: _result("## 必检项\n- **必须发生**：有")
    )

    result = await workbench.generate_planning_with_architect("book", 9)

    assert result["state"] == "rejected"
    assert result["missing_labels"] == ["必须不发生", "结尾停在哪", "信息层级"]
    assert path.read_text(encoding="utf-8").endswith("盘上旧方案")


@pytest.mark.asyncio
async def test_complete_output_lands_as_director_draft(
    plan_book: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from biyu.ui import workbench

    monkeypatch.setattr(workbench, "_web_architect_enabled", lambda: True)
    monkeypatch.setattr(workbench, "_call_web_architect", lambda *_args, **_kwargs: _result(VALID_PLAN))

    result = await workbench.generate_planning_with_architect("book", 9)

    path = plan_book / "logs/ch9/planning.md"
    assert result["state"] == "draft"
    assert path.read_text(encoding="utf-8") == f"status: 待批\nsource: 导演产出\n{VALID_PLAN}"


@pytest.mark.asyncio
async def test_rewrite_keeps_approved_plan_active_and_lands_separate_draft(
    plan_book: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from biyu.ui import workbench

    active = plan_book / "logs/ch9/planning.md"
    active.write_text(f"status: 已批\nsource: 作者手写\n{VALID_PLAN}", encoding="utf-8")
    before = active.read_text(encoding="utf-8")
    monkeypatch.setattr(workbench, "_web_architect_enabled", lambda: True)
    monkeypatch.setattr(workbench, "_call_web_architect", lambda *_args, **_kwargs: _result(VALID_PLAN + "\n新一版"))

    result = await workbench.generate_planning_with_architect("book", 9)

    assert result["state"] == "draft"
    assert active.read_text(encoding="utf-8") == before
    assert (plan_book / "logs/ch9/planning_draft.md").read_text(encoding="utf-8").startswith(
        "status: 待批\nsource: 导演产出\n"
    )


def test_approved_plan_does_not_disable_architect() -> None:
    from biyu.ui import workbench

    actions = workbench._state_actions(
        "generation", "idle", stale=False, has_outline=True,
        has_planning=True, planning_status="已批",
    )
    assert actions["architect"]["enabled"] is True


class _AwaitableResult:
    def __init__(self, text: str):
        self.text = text
        self.cost = 0.1
        self.status = "ok"

    def __await__(self):
        async def done():
            return self

        return done().__await__()


def _result(text: str) -> _AwaitableResult:
    return _AwaitableResult(text)
