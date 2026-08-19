from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


SYSTEM_USAGE_POLICY = [
    "这是参考，不是硬规则。",
    "不必每句话都对应某条规则，只在合适的场景与情绪节点让它自然生效。",
    "学的是处理方式，不照搬具体人物、意象、场景。",
    "与本书自蒸馏冲突时，以本书为准。",
]


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _ledger_line(
    *,
    item_id: str,
    action: str,
    scope: str = "sentence",
    chapter: int = 1,
    round_no: int = 1,
    text: str = "原句",
    comment: str = "",
) -> str:
    item = {
        "id": item_id,
        "created_at": "2026-07-26T00:00:00+08:00",
        "book": "fixture",
        "chapter": chapter,
        "round": round_no,
        "scope": scope,
        "action": action,
        "author_comment": comment,
        "in_revision_package": action == "revise",
    }
    if scope == "sentence":
        item.update(candidate_sha="sha", anchor=1, text=text)
    else:
        item["verdict"] = "章级意见"
    return json.dumps(item, ensure_ascii=False)


def _self_profile(book: Path, *, line_text: str = "VOICEPRINT_SENTINEL") -> None:
    _write(
        book / "声纹/本书自蒸馏.json",
        json.dumps(
            {
                "schema_version": 1,
                "id": "book:self",
                "name": "本书自蒸馏",
                "kind": "book",
                "lines": [
                    {
                        "id": "line-1",
                        "dimension": "句子节奏",
                        "text": line_text,
                        "why": "帮助写手理解规则所服务的阅读效果。",
                        "source": "machine",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    _write(book / "声纹/选择.json", '{"selected":["book:self"]}')


def test_candidate_pool_includes_both_actions_and_excludes_chapter(tmp_path: Path) -> None:
    from biyu.fingerprint.distillation import build_candidate_pool
    from biyu.fingerprint.ledger import read_feedback_entries

    _write(
        tmp_path / "反馈账.jsonl",
        "\n".join(
            [
                _ledger_line(item_id="revise", action="revise"),
                _ledger_line(item_id="note", action="note_problem"),
                _ledger_line(item_id="good", action="good"),
                _ledger_line(item_id="chapter", action="note_problem", scope="chapter"),
            ]
        )
        + "\n",
    )
    pool = build_candidate_pool(read_feedback_entries(tmp_path))
    assert {item["action"] for item in pool["problems"]} == {"revise", "note_problem"}
    assert [item["id"] for item in pool["goods"]] == ["good"]
    assert "chapter" not in {item["id"] for values in pool.values() for item in values}


def test_no_auto_classification_and_singleton_is_kept(tmp_path: Path) -> None:
    from biyu.fingerprint.distillation import review_snapshot

    _write(
        tmp_path / "反馈账.jsonl",
        _ledger_line(
            item_id="only",
            action="note_problem",
            text="只出现一次。",
            comment="这一句仍要作者判断",
        )
        + "\n",
    )
    snapshot = review_snapshot(tmp_path)
    assert len(snapshot["groups"]) == 1
    assert snapshot["groups"][0]["count"] == 1
    assert snapshot["groups"][0]["decision"] == ""
    assert snapshot["confirmed_negative_ids"] == []


def test_repeated_author_diagnosis_is_grouped_without_auto_decision(tmp_path: Path) -> None:
    from biyu.fingerprint.distillation import review_snapshot

    _write(
        tmp_path / "反馈账.jsonl",
        "\n".join(
            [
                _ledger_line(item_id="a", action="revise", comment="句子太整齐"),
                _ledger_line(item_id="b", action="note_problem", chapter=3, comment="句子太整齐"),
            ]
        )
        + "\n",
    )
    snapshot = review_snapshot(tmp_path)
    assert len(snapshot["groups"]) == 1
    assert snapshot["groups"][0]["count"] == 2
    assert snapshot["groups"][0]["decision"] == ""


def test_legacy_negatives_are_separate_and_not_auto_imported(tmp_path: Path) -> None:
    from biyu.fingerprint.distillation import review_snapshot, save_group_decision

    _write(tmp_path / "样本库/负例候选.md", "- 旧问题一\n- 旧问题二\n")
    first = review_snapshot(tmp_path)
    legacy = next(group for group in first["groups"] if group["kind"] == "legacy")
    assert first["confirmed_negative_ids"] == []
    save_group_decision(tmp_path, legacy["id"], "specific")
    second = review_snapshot(tmp_path)
    assert not any(group["kind"] == "legacy" for group in second["groups"])


def test_edited_line_persists_and_survives_redistill(tmp_path: Path) -> None:
    from biyu.fingerprint.library import edit_voice_line, load_self_profile, replace_machine_lines

    replace_machine_lines(
        tmp_path,
        [{"dimension": "句子节奏", "text": "机器初稿"}],
    )
    line_id = load_self_profile(tmp_path)["lines"][0]["id"]
    edit_voice_line(tmp_path, line_id, "作者改过", "作者保留的理由")
    replace_machine_lines(
        tmp_path,
        [
            {"dimension": "句子节奏", "text": "机器重算"},
            {"dimension": "标点", "text": "少用感叹号"},
        ],
    )
    lines = load_self_profile(tmp_path)["lines"]
    assert any(line["text"] == "作者改过" and line["source"] == "author" for line in lines)
    assert any(line.get("why") == "作者保留的理由" for line in lines)
    assert not any(line["text"] == "机器重算" for line in lines)
    assert any(line["dimension"] == "标点" for line in lines)


def test_single_active_voiceprint_and_api_value(tmp_path: Path) -> None:
    from biyu.fingerprint.library import load_merged_voiceprint, save_selection

    assets = tmp_path / "assets"
    _write(
        assets / "jiangnan.json",
        json.dumps(
            {
                "schema_version": 1,
                "id": "builtin:jiangnan",
                "name": "江南文风",
                "kind": "builtin",
                "lines": [
                    {"id": "j1", "dimension": "比喻密度", "text": "多用意象", "source": "signed"},
                    {"id": "j2", "dimension": "意象", "text": "具体物象承载情绪", "source": "signed"},
                ],
            },
            ensure_ascii=False,
        ),
    )
    _self_profile(tmp_path, line_text="每千字不超过两处比喻")
    profile = json.loads((tmp_path / "声纹/本书自蒸馏.json").read_text(encoding="utf-8"))
    profile["lines"][0]["dimension"] = "比喻密度"
    _write(tmp_path / "声纹/本书自蒸馏.json", json.dumps(profile, ensure_ascii=False))
    save_selection(tmp_path, "book:self")

    merged = load_merged_voiceprint(tmp_path, builtins_dir=assets)
    assert next(line for line in merged["lines"] if line["dimension"] == "比喻密度")["text"] == "每千字不超过两处比喻"
    assert merged["active_profile_id"] == "book:self"
    assert not any(line["dimension"] == "意象" for line in merged["lines"])
    assert "这是参考，不是硬规则" in merged["text"]
    assert "为什么" in merged["text"]


def test_usage_policy_always_injected(
    tmp_path: Path,
) -> None:
    from biyu.fingerprint.library import load_merged_voiceprint
    from biyu.fingerprint.merge_policy import SYSTEM_USAGE_POLICY as production_policy

    _self_profile(tmp_path)
    merged = load_merged_voiceprint(tmp_path, builtins_dir=tmp_path / "none")

    assert production_policy == SYSTEM_USAGE_POLICY
    assert merged["active_profile_id"] == "book:self"
    assert merged["usage_policy"] == SYSTEM_USAGE_POLICY
    assert all(rule in merged["text"] for rule in SYSTEM_USAGE_POLICY)


def test_cost_estimate_matches_magnitude(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import biyu.ui.voiceprint as voiceprint_module

    class Adapter:
        cost_per_1k_input = 0.001
        cost_per_1k_output = 0.0035

        def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
            return (
                prompt_tokens * self.cost_per_1k_input
                + completion_tokens * self.cost_per_1k_output
            ) / 1000

    class Registry:
        def get_adapter_for_stage(self, _stage: str):
            return Adapter()

    monkeypatch.setattr(voiceprint_module, "get_registry", lambda: Registry())
    _write(
        tmp_path / "反馈账.jsonl",
        _ledger_line(item_id="one", action="good", text="短句") + "\n",
    )
    small = voiceprint_module._estimate(tmp_path)

    _write(
        tmp_path / "反馈账.jsonl",
        "\n".join(
            _ledger_line(
                item_id=f"long-{index}",
                action="good",
                text="这是一条用于核对输入量增长的较长反馈。" * 20,
            )
            for index in range(10)
        )
        + "\n",
    )
    large = voiceprint_module._estimate(tmp_path)

    assert 0 < small["estimated_cost_yuan"] < large["estimated_cost_yuan"] < 0.02
    assert small["estimate_kind"] == "upper_bound"
    assert large["estimated_input_units"] > small["estimated_input_units"]
    assert large["feedback_count"] == 10


def test_redistill_reads_all_feedback(tmp_path: Path) -> None:
    from biyu.fingerprint.distillation import record_distillation, review_snapshot

    _write(
        tmp_path / "反馈账.jsonl",
        _ledger_line(item_id="old", action="note_problem", chapter=1, comment="句子太整齐")
        + "\n",
    )
    record_distillation(tmp_path, review_snapshot(tmp_path))
    with (tmp_path / "反馈账.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            _ledger_line(
                item_id="new",
                action="revise",
                chapter=8,
                comment="句子太整齐",
            )
            + "\n"
        )

    snapshot = review_snapshot(tmp_path)
    assert [item["id"] for item in snapshot["groups"][0]["items"]] == ["old", "new"]
    assert snapshot["new_feedback_count"] == 1


def test_judged_group_stays_judged(tmp_path: Path) -> None:
    from biyu.fingerprint.distillation import review_snapshot, save_group_decision

    _write(
        tmp_path / "反馈账.jsonl",
        _ledger_line(item_id="old", action="note_problem", comment="句子太整齐") + "\n",
    )
    group = review_snapshot(tmp_path)["groups"][0]
    save_group_decision(tmp_path, group["id"], "specific")

    snapshot = review_snapshot(tmp_path)
    assert snapshot["groups"] == []
    assert snapshot["all_groups"][0]["decision"] == "specific"
    assert snapshot["all_groups"][0]["needs_reconfirmation"] is False


def test_grown_group_resurfaces(tmp_path: Path) -> None:
    from biyu.fingerprint.distillation import (
        build_distillation_payload,
        review_snapshot,
        save_group_decision,
    )

    ledger = tmp_path / "反馈账.jsonl"
    _write(
        ledger,
        _ledger_line(item_id="old", action="note_problem", comment="句子太整齐") + "\n",
    )
    group = review_snapshot(tmp_path)["groups"][0]
    save_group_decision(tmp_path, group["id"], "common")
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(
            _ledger_line(
                item_id="new",
                action="revise",
                chapter=7,
                comment="句子太整齐",
            )
            + "\n"
        )

    snapshot = review_snapshot(tmp_path)
    grown = snapshot["groups"][0]
    assert grown["id"] == group["id"]
    assert grown["previous_decision"] == "common"
    assert grown["decision"] == ""
    assert grown["new_count"] == 1
    assert grown["needs_reconfirmation"] is True
    payload = build_distillation_payload(snapshot)
    payload_ids = [
        item["id"]
        for payload_group in payload["confirmed_problem_groups"]
        for item in payload_group["items"]
    ]
    assert payload_ids == ["old"]

    save_group_decision(tmp_path, grown["id"], "common")
    confirmed = review_snapshot(tmp_path)
    payload = build_distillation_payload(confirmed)
    payload_ids = [
        item["id"]
        for payload_group in payload["confirmed_problem_groups"]
        for item in payload_group["items"]
    ]
    assert payload_ids == ["old", "new"]


def test_legacy_judgment_migrates_before_growth(tmp_path: Path) -> None:
    from biyu.fingerprint.distillation import review_snapshot

    ledger = tmp_path / "反馈账.jsonl"
    _write(
        ledger,
        _ledger_line(item_id="old", action="note_problem", comment="句子太整齐") + "\n",
    )
    old_group = "problem-" + hashlib.sha256(b"old").hexdigest()[:12]
    _write(
        tmp_path / "声纹" / "复核状态.json",
        json.dumps({"decisions": {old_group: "common"}}, ensure_ascii=False),
    )

    settled = review_snapshot(tmp_path)
    assert settled["groups"] == []
    persisted = json.loads(
        (tmp_path / "声纹" / "复核状态.json").read_text(encoding="utf-8")
    )
    assert persisted["version"] == 2
    assert persisted["groups"][settled["all_groups"][0]["id"]]["member_ids"] == ["old"]

    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(
            _ledger_line(
                item_id="new",
                action="revise",
                chapter=7,
                comment="句子太整齐",
            )
            + "\n"
        )
    grown = review_snapshot(tmp_path)["groups"][0]
    assert grown["previous_decision"] == "common"
    assert grown["new_count"] == 1
    assert grown["needs_reconfirmation"] is True


def test_clustering_zero_llm_on_full_reread(tmp_path: Path) -> None:
    from biyu.fingerprint.distillation import review_snapshot

    _write(
        tmp_path / "反馈账.jsonl",
        "\n".join(
            _ledger_line(
                item_id=f"item-{index}",
                action="note_problem",
                chapter=index,
                comment="句子太整齐",
            )
            for index in range(1, 4)
        )
        + "\n",
    )
    adapter = MagicMock()

    snapshot = review_snapshot(tmp_path)

    assert snapshot["groups"][0]["count"] == 3
    adapter.generate.assert_not_called()


def test_redistill_state_persists(tmp_path: Path) -> None:
    from biyu.fingerprint.distillation import (
        record_distillation,
        review_snapshot,
        save_group_decision,
    )

    _write(
        tmp_path / "反馈账.jsonl",
        _ledger_line(item_id="old", action="note_problem", comment="句子太整齐") + "\n",
    )
    group = review_snapshot(tmp_path)["groups"][0]
    save_group_decision(tmp_path, group["id"], "common")
    record_distillation(tmp_path, review_snapshot(tmp_path))

    persisted = json.loads(
        (tmp_path / "声纹/复核状态.json").read_text(encoding="utf-8")
    )
    reloaded = review_snapshot(tmp_path)
    assert persisted["last_distilled_at"]
    assert persisted["last_feedback_ids"] == ["old"]
    assert persisted["groups"][group["id"]]["decision"] == "common"
    assert reloaded["last_distilled_at"] == persisted["last_distilled_at"]
    assert reloaded["new_feedback_count"] == 0


def test_source_breakdown_present(tmp_path: Path, monkeypatch) -> None:
    import biyu.ui.voiceprint as voiceprint_module

    _write(
        tmp_path / "反馈账.jsonl",
        "\n".join(
            [
                _ledger_line(item_id="revise", action="revise", chapter=1),
                _ledger_line(item_id="note", action="note_problem", chapter=8),
                _ledger_line(item_id="good", action="good", chapter=3),
                _ledger_line(
                    item_id="chapter",
                    action="note_problem",
                    scope="chapter",
                    chapter=8,
                ),
            ]
        )
        + "\n",
    )
    monkeypatch.setattr(voiceprint_module, "_book_dir", lambda _book: tmp_path)
    workspace = voiceprint_module.get_workspace("fixture")

    assert workspace["sources"] == {
        "revise": 1,
        "note_problem": 1,
        "good": 1,
        "chapter_excluded": 1,
        "chapter_range": "第 1–8 章",
    }


def test_voiceprint_page_carries_book() -> None:
    html = Path("src/biyu/ui/static/voiceprint.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/voiceprint.js").read_text(encoding="utf-8")
    assert 'id="book"' in html
    assert "/api/workbench/books" in js
    assert "history.replaceState" in js
    assert "encodeURIComponent(book)" in js


def test_nav_preserves_book_across_pages() -> None:
    workbench = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
    memory = Path("src/biyu/ui/static/memory.js").read_text(encoding="utf-8")
    voiceprint = Path("src/biyu/ui/static/voiceprint.js").read_text(encoding="utf-8")
    assert "/voiceprint.html?book=" in workbench
    assert "/voiceprint.html?book=" in memory
    assert "/workbench.html?book=" in voiceprint
    assert "/memory.html?book=" in voiceprint


def test_workbench_shows_active_voiceprint() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
    assert 'id="active-voiceprint"' in html
    assert "refreshActiveVoiceprint" in js
    assert "/api/voiceprint/books/" in js
    assert "声纹：" in js


def test_single_active_book_profile_does_not_union_builtin(tmp_path: Path) -> None:
    from biyu.fingerprint.library import load_merged_voiceprint, save_selection

    assets = tmp_path / "assets"
    _write(
        assets / "builtin.json",
        json.dumps({
            "id": "builtin:test",
            "name": "内置",
            "kind": "builtin",
            "lines": [
                {"id": "b1", "dimension": "句子长短与节奏", "text": "内置节奏"},
                {"id": "b2", "dimension": "明确避坑", "text": "内置避坑"},
            ],
        }, ensure_ascii=False),
    )
    _write(
        tmp_path / "声纹/本书自蒸馏.json",
        json.dumps({
            "id": "book:self",
            "name": "本书自蒸馏",
            "kind": "book",
            "lines": [
                {"id": "s1", "dimension": "句子长短与节奏偏好", "text": "本书节奏"},
                {"id": "s2", "dimension": "明确禁用的表达", "text": "本书避坑"},
            ],
        }, ensure_ascii=False),
    )
    save_selection(tmp_path, "book:self")
    merged = load_merged_voiceprint(tmp_path, builtins_dir=assets)
    texts = {line["text"] for line in merged["lines"]}
    assert texts == {"本书节奏", "本书避坑"}
    assert "内置节奏" not in texts


def test_insufficient_active_profile_does_not_pull_in_inactive_builtin(tmp_path: Path) -> None:
    from biyu.fingerprint.library import load_merged_voiceprint, save_selection

    assets = tmp_path / "assets"
    _write(
        assets / "builtin.json",
        json.dumps({
            "id": "builtin:test",
            "name": "内置",
            "kind": "builtin",
            "lines": [{"id": "b1", "dimension": "比喻与通感", "text": "内置比喻规则"}],
        }, ensure_ascii=False),
    )
    _write(
        tmp_path / "声纹/本书自蒸馏.json",
        json.dumps({
            "id": "book:self",
            "name": "本书自蒸馏",
            "kind": "book",
            "lines": [{
                "id": "s1",
                "dimension": "比喻/形容的密度",
                "text": "现有反馈不足，暂不设规则。",
            }],
        }, ensure_ascii=False),
    )
    save_selection(tmp_path, "book:self")
    merged = load_merged_voiceprint(tmp_path, builtins_dir=assets)
    assert merged["active_profile_id"] == "book:self"
    assert merged["lines"] == []


@pytest.mark.asyncio
async def test_distill_runs_only_when_explicit_function_is_called(tmp_path: Path) -> None:
    from biyu.fingerprint.distillation import (
        distill_voiceprint,
        review_snapshot,
        save_group_decision,
    )

    _write(
        tmp_path / "反馈账.jsonl",
        _ledger_line(item_id="p1", action="revise", comment="节奏太齐") + "\n",
    )
    group = review_snapshot(tmp_path)["groups"][0]
    save_group_decision(tmp_path, group["id"], "common")

    class Adapter:
        calls = 0

        async def generate(self, **_kwargs):
            self.calls += 1
            return SimpleNamespace(
                text=json.dumps(
                    {"lines": [{
                        "dimension": "句子长短与节奏偏好",
                        "text": "长短句错落",
                        "why": "让情绪推进有呼吸和落点",
                    }]},
                    ensure_ascii=False,
                ),
                cost=0.01,
            )

    adapter = Adapter()
    assert adapter.calls == 0
    result = await distill_voiceprint(tmp_path, adapter, "SIGNED PROMPT")
    assert adapter.calls == 1
    assert result["profile"]["lines"][0]["text"] == "长短句错落"
    assert result["profile"]["lines"][0]["why"] == "让情绪推进有呼吸和落点"
    assert not (tmp_path / "truth_files").exists()


def test_legacy_fingerprint_still_loads(tmp_path: Path) -> None:
    from biyu.fingerprint.library import load_merged_voiceprint

    legacy = {
        "schema_version": 1,
        "extracted_at": "2026-01-01",
        "source_info": {"source_path": "fixture", "total_chars": 1, "sampled_chars": 1, "sampling_method": "fixture"},
        "style_description": "旧声纹描述" * 50,
        "exemplar_passages": [
            {"passage": f"代表段落{i}" * 100, "why_representative": "代表原因"}
            for i in range(5)
        ],
        "ai_pitfalls": [
            {"pitfall": f"雷区{i}", "why_it_happens": "原因"}
            for i in range(5)
        ],
    }
    _write(tmp_path / "legacy.json", json.dumps(legacy, ensure_ascii=False))
    _write(tmp_path / "book.json", '{"fingerprint_path":"legacy.json"}')
    merged = load_merged_voiceprint(tmp_path, builtins_dir=tmp_path / "none")
    assert "旧声纹描述" in merged["text"]
    assert merged["profiles"][0]["id"] == "legacy:fingerprint_path"
    assert sum(line["dimension"] == "代表段落" for line in merged["lines"]) == 5
    assert sum(line["dimension"] == "写作雷区" for line in merged["lines"]) == 5


def test_signed_builtin_preserves_usage_boundaries_and_reasons() -> None:
    path = Path("assets/声纹库/内置/江南文风.json")
    profile = json.loads(path.read_text(encoding="utf-8"))
    policies = "\n".join(profile["usage_policy"])
    assert profile["source_ref"] == "data/jiangnan_fingerprint.json"
    assert "参考，不是硬规则" in policies
    assert "合适的场景" in policies
    assert "不照搬原文" in policies
    assert "本书自蒸馏为准" in policies
    assert len(profile["lines"]) >= 8
    assert all(line["text"].strip() and line["why"].strip() for line in profile["lines"])
    dimensions = {line["dimension"] for line in profile["lines"]}
    assert {"情绪落点", "句子长短与节奏", "人物对白", "明确避坑"} <= dimensions


def test_voiceprint_in_layer2_not_system_tail() -> None:
    from biyu.prompts.chapter_writer import (
        LAYER2_BEGIN,
        LAYER2_END,
        build_writer_prompt_v4,
    )

    system, user = build_writer_prompt_v4(
        chapter_num=1,
        worldbook={},
        worldbook_prompt="",
        characters=[],
        truth_files_block="",
        prev_tail="",
        context_block="",
        outline="细纲",
        planning="",
        voiceprint_block="VOICEPRINT_SENTINEL",
    )
    assert "VOICEPRINT_SENTINEL" not in system
    layer2 = user.split(LAYER2_END)[0].split(LAYER2_BEGIN, 1)[1]
    assert "VOICEPRINT_SENTINEL" in layer2


def test_voiceprint_reaches_revision_writer(tmp_path: Path, monkeypatch) -> None:
    import biyu.editor.editor as editor_module
    from biyu.audit_reports.revisions import create_revision_package
    from biyu.git_helper import ensure_local_repository
    from biyu.pipeline import revise_chapter_from_package

    ensure_local_repository(tmp_path)
    _write(tmp_path / "book.json", "{}")
    _write(tmp_path / "chapters/ch1.md", "正式不得碰")
    _write(tmp_path / "chapters/_pending/ch1.md", "候选 v1")
    _write(tmp_path / "logs/ch1/planning.md", "status: 已批\n方案")
    _write(
        tmp_path / "audit_reports/ch1.json",
        json.dumps(
            {
                "chapter": 1,
                "issues": [{"id": "ch1-001", "description": "问题", "suggestion": "建议"}],
            },
            ensure_ascii=False,
        ),
    )
    import hashlib
    package = create_revision_package(
        tmp_path,
        1,
        selected_issue_ids=["ch1-001"],
        issue_comments={},
        general_comment="整体收紧",
        candidate_sha=hashlib.sha256("候选 v1".encode()).hexdigest(),
    )
    prompt = _write(tmp_path / "revision.md", "只输出修订后的完整正文")
    _self_profile(tmp_path)

    class Adapter:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def generate(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(text="候选 v2", cost=0.0)

    writer = Adapter()

    async def fake_review(**_kwargs):
        return SimpleNamespace(issues=[], cost=0.0)

    monkeypatch.setattr(editor_module, "review_chapter", fake_review)
    asyncio.run(
        revise_chapter_from_package(
            tmp_path,
            1,
            package,
            writer_adapter=writer,
            editor_adapter=object(),
            prompt_path=prompt,
        )
    )
    assert "VOICEPRINT_SENTINEL" in "\n".join(
        item["content"] for item in writer.calls[0]["messages"]
    )
    assert all(
        rule in "\n".join(item["content"] for item in writer.calls[0]["messages"])
        for rule in SYSTEM_USAGE_POLICY
    )


class _GenerationBoundary(Exception):
    pass


@pytest.mark.asyncio
async def test_voiceprint_reaches_generation_writer(tmp_path: Path) -> None:
    from biyu.pipeline import generate_chapter

    _write(tmp_path / "book.json", '{"title":"夹具","genre":"xuanhuan","chapter_target_words":1000}')
    _write(tmp_path / "worldbook.yaml", "facts:\n  - 测试设定\n")
    _write(tmp_path / "characters.yaml", "characters: []\n")
    _write(tmp_path / "outlines/ch1.md", "# 细纲\n")
    _write(tmp_path / "logs/ch1/planning.md", "status: 已批\n夹具方案")
    _self_profile(tmp_path)
    writer = MagicMock()

    async def capture(adapter, messages, **kwargs):
        if adapter is writer:
            combined = "\n".join(
                item.get("content", "") for item in kwargs.get("cacheable_prefix", []) + messages
            )
            assert "VOICEPRINT_SENTINEL" in combined
            assert all(rule in combined for rule in SYSTEM_USAGE_POLICY)
            raise _GenerationBoundary
        return SimpleNamespace(text="{}", cost=0.0)

    registry = MagicMock()
    registry.get_pipeline_config.return_value = {"writer": "v3", "planner": "r1"}
    registry.get_adapter_for_stage.side_effect = lambda stage, override=None: writer
    with (
        patch("biyu.pipeline.get_registry", return_value=registry),
        patch("biyu.pipeline._call_with_retry", side_effect=capture),
        patch("biyu.pipeline._log_cost"),
        patch("biyu.pipeline._write_long_run_csv"),
    ):
        with pytest.raises(_GenerationBoundary):
            await generate_chapter(book_dir=tmp_path, chapter_num=1, prompt_version="v4")


def test_diagnosis_has_no_voiceprint() -> None:
    source = Path("src/biyu/ui/diagnosis.py").read_text(encoding="utf-8")
    assert "load_merged_voiceprint" not in source
    assert "VOICEPRINT_SENTINEL" not in source


def test_static_voiceprint_workspace_contract() -> None:
    html = Path("src/biyu/ui/static/voiceprint.html").read_text(encoding="utf-8")
    js = Path("src/biyu/ui/static/voiceprint.js").read_text(encoding="utf-8")
    assert all(text in html + js for text in (
        "开始蒸馏", "这是通病", "就那几次", "未判定的组不会进声纹",
        "一本书同时只使用一份", "机械合并", "从零手写",
    ))
    assert "mini-md.js" in html
    assert "error-banner" in html
    assert "finally" in js and ".disabled=true" in js
    assert "setTimeout" not in js
    assert "预计不超过" in js
    assert "本次实际" in js
    assert "result.cost" in js
    assert "处理中…" in js
    assert "error-banner-icon" in js
    assert all(text in html + js for text in (
        "这些反馈从哪来",
        "章评的整章意见",
        "不是某一句，不进声纹",
        "查看全部（含已判定）",
        "上次蒸馏",
        "本次新增反馈",
        "维持原判",
        "改判",
    ))
    assert "if(line.source==='author')" in js
    assert "你改过" in js
