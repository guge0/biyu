from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _successful_result() -> dict:
    return {
        "quality_gate": {
            "stable_enough": True,
            "reason": "多种场景里反复出现同一种处理。",
            "missing_evidence": [],
        },
        "style_description": (
            "维度：整体气质｜规则是什么：叙述克制，不替人物喊出情绪｜"
            "为什么：把判断留给读者\n"
            "维度：人物对白｜规则是什么：对白短，话外意思多｜"
            "为什么：人物关系主要靠停顿和回避显形"
        ),
        "exemplar_passages": [
            {
                "passage": "R5-3B_EXEMPLAR_SENTINEL",
                "why_representative": "只用于旧提取结果，不得进入新声纹库。",
            }
        ],
        "ai_pitfalls": [
            {
                "pitfall": "不要把沉默解释成完整的心理独白",
                "why_it_happens": "模型容易替人物把留白说尽。",
            }
        ],
    }


def _legacy_schema_result() -> dict:
    return {
        "style_description": "稳定、具体、能解释写法的旧格式风格说明。" * 30,
        "exemplar_passages": [
            {
                "passage": f"第 {index} 段" + "正文" * 300,
                "why_representative": "展示旧格式成功输出。",
            }
            for index in range(5)
        ],
        "ai_pitfalls": [
            {
                "pitfall": f"避免第 {index} 类表面模仿",
                "why_it_happens": "模型容易只学表面。",
            }
            for index in range(5)
        ],
    }


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    import biyu.ui.voiceprint_import as voiceprint_import
    from biyu.ui.app import app

    monkeypatch.setattr(voiceprint_import, "_book_dir", lambda _book: tmp_path)
    return TestClient(app)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _select_imported_profile(book_dir: Path) -> None:
    from biyu.fingerprint.profile_state import save_profile_state

    profile = {
        "schema_version": 1,
        "id": "import:writer-seam",
        "name": "自备中性样本",
        "kind": "imported",
        "created_at": "2026-07-31T12:00:00+00:00",
        "source_ref": {
            "import_id": "import:writer-seam",
            "source_name": "自备中性样本.txt",
            "source_sha256": "a" * 64,
        },
        "lines": [{
            "id": "import-rule",
            "dimension": "整体气质",
            "text": "R5_3B_RULE_SENTINEL",
            "why": "证明新导入规则到达 Writer。",
            "source": "machine",
            "source_ref": {
                "import_id": "import:writer-seam",
                "source_name": "自备中性样本.txt",
                "source_sha256": "a" * 64,
            },
        }],
    }
    _write(
        book_dir / "声纹/导入作品/writer-seam.json",
        json.dumps(profile, ensure_ascii=False),
    )
    save_profile_state(
        book_dir,
        active="import:writer-seam",
    )


def test_import_extract_is_explicit_only(tmp_path: Path, monkeypatch) -> None:
    """预检只算真实输入量；未点“开始提取”前不得触发模型。"""
    import biyu.fingerprint.extractor as extractor

    calls = 0

    async def forbidden_call(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("预检不得调用模型")

    monkeypatch.setattr(extractor, "generate_json", forbidden_call)
    response = _client(tmp_path, monkeypatch).post(
        "/api/voiceprint/books/fixture/imports/preflight",
        json={"source_name": "自备中性样本.txt", "text": "甲乙丙丁。" * 900},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sampled_chars"] >= 3000
    assert payload["normal_calls"] == 1
    assert payload["max_calls"] == 2
    assert payload["estimated_cost"] >= 0
    assert calls == 0


def test_thin_sample_blocked_before_call(tmp_path: Path, monkeypatch) -> None:
    import biyu.fingerprint.extractor as extractor

    calls = 0

    async def forbidden_call(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("薄样本必须在模型调用前阻断")

    monkeypatch.setattr(extractor, "generate_json", forbidden_call)
    response = _client(tmp_path, monkeypatch).post(
        "/api/voiceprint/books/fixture/imports/extract",
        json={"source_name": "太短.txt", "text": "只有一点文字。" * 100},
    )

    assert response.status_code in {400, 422}
    assert "3000" in str(response.json())
    assert calls == 0


def test_soft_gate_is_one_paid_business_result_without_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import biyu.fingerprint.extractor as extractor

    calls = 0

    def soft_gate(coro):
        nonlocal calls
        calls += 1
        coro.close()
        return (
            {
                "quality_gate": {
                    "stable_enough": False,
                    "reason": "场景过于单一。",
                    "missing_evidence": ["缺少不同情绪场景"],
                }
            },
            {
                "prompt_tokens": 100,
                "completion_tokens": 30,
                "total_tokens": 130,
                "cost": 0.001,
            },
        )

    monkeypatch.setattr(extractor, "_run_async", soft_gate)
    source = _write(tmp_path / "source.txt", "甲乙丙丁。" * 900)
    output = tmp_path / "fingerprint.json"

    with pytest.raises(extractor.InsufficientEvidenceError) as caught:
        extractor.extract_fingerprint(str(source), str(output))

    assert calls == 1
    assert caught.value.quality_gate["reason"] == "场景过于单一。"
    assert caught.value.usage["cost"] == 0.001
    assert not output.exists()


def test_legacy_cli_success_contract_still_accepts_sub_3000_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """R5-3B 的 3000 字硬闸只在新作者入口；旧 CLI 成功接口不变。"""
    import biyu.fingerprint.extractor as extractor

    def old_success(coro):
        coro.close()
        return (
            _legacy_schema_result(),
            {
                "prompt_tokens": 100,
                "completion_tokens": 200,
                "total_tokens": 300,
                "cost": 0.002,
            },
        )

    monkeypatch.setattr(extractor, "_run_async", old_success)
    source = _write(tmp_path / "source.txt", "旧接口文本。" * 400)
    output = tmp_path / "fingerprint.json"
    fingerprint, usage = extractor.extract_fingerprint(
        str(source),
        str(output),
    )

    assert fingerprint.schema_version == 1
    assert fingerprint.source_info.total_chars < 3000
    assert len(fingerprint.exemplar_passages) == 5
    assert usage["cost"] == 0.002
    assert output.exists()


def test_exemplars_never_reach_writer_for_r5_3b_imports(tmp_path: Path) -> None:
    """只约束 R5-3B 新导入路径；legacy fingerprint_path 保持原样。"""
    from biyu.fingerprint.library import load_merged_voiceprint
    from biyu.fingerprint.profile_state import save_profile_state
    from biyu.fingerprint.profile_normalizer import normalize_import_result

    profile = normalize_import_result(
        _successful_result(),
        import_id="import:abc123",
        source_name="自备中性样本.txt",
        source_sha256="a" * 64,
    )
    _write(tmp_path / "声纹/导入作品/abc123.json", json.dumps(profile, ensure_ascii=False))
    save_profile_state(tmp_path, "import:abc123")
    merged = load_merged_voiceprint(tmp_path, builtins_dir=tmp_path / "none")

    assert "exemplar_passages" not in profile
    assert all(
        "R5-3B_EXEMPLAR_SENTINEL" not in str(line)
        for line in profile["lines"]
    )
    assert "R5-3B_EXEMPLAR_SENTINEL" not in merged["text"]


def test_successful_import_persists_only_hash_metadata_and_lines(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import biyu.ui.voiceprint_import as voiceprint_import

    raw_sentinel = "RAW_IMPORTED_PROSE_MUST_NOT_PERSIST"
    text = raw_sentinel + "甲乙丙丁。" * 900

    class FingerprintResult:
        def model_dump(self):
            return _successful_result()

    monkeypatch.setattr(voiceprint_import, "_book_dir", lambda _book: tmp_path)
    monkeypatch.setattr(
        voiceprint_import,
        "production_prompt_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        voiceprint_import,
        "extract_fingerprint",
        lambda *_args, **_kwargs: (
            FingerprintResult(),
            {
                "prompt_tokens": 100,
                "completion_tokens": 200,
                "total_tokens": 300,
                "cost": 0.002,
            },
        ),
    )
    monkeypatch.setattr(
        voiceprint_import,
        "_record_cost",
        lambda *_args, **_kwargs: None,
    )

    response = _client(tmp_path, monkeypatch).post(
        "/api/voiceprint/books/fixture/imports/extract",
        json={"source_name": "../中性样本.txt", "text": text},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["source_name"] == "中性样本.txt"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    saved_path = tmp_path / "声纹/导入作品" / f"{digest}.json"
    saved_text = saved_path.read_text(encoding="utf-8")
    saved = json.loads(saved_text)
    assert raw_sentinel not in saved_text
    assert "R5-3B_EXEMPLAR_SENTINEL" not in saved_text
    assert saved["source_ref"]["source_sha256"] == digest
    assert saved["source_chars"] == len(text)
    assert all(line["source"] == "machine" for line in saved["lines"])


def test_edited_line_survives_reextract() -> None:
    from biyu.fingerprint.profile_normalizer import normalize_import_result

    existing = {
        "id": "import:abc123",
        "name": "自备中性样本.txt",
        "kind": "imported",
        "lines": [
            {
                "id": "author-line",
                "dimension": "整体气质",
                "text": "作者亲手改成：冷静，但不冷漠",
                "why": "这是作者确认过的边界。",
                "source": "author",
                "source_ref": {
                    "import_id": "import:abc123",
                    "source_name": "自备中性样本.txt",
                    "source_sha256": "a" * 64,
                },
            }
        ],
    }

    profile = normalize_import_result(
        _successful_result(),
        import_id="import:abc123",
        source_name="自备中性样本.txt",
        source_sha256="a" * 64,
        existing_profile=existing,
    )
    author_lines = [line for line in profile["lines"] if line["source"] == "author"]

    assert [line["id"] for line in author_lines] == ["author-line"]
    assert author_lines[0]["text"] == "作者亲手改成：冷静，但不冷漠"


class _WriterSeamReached(Exception):
    pass


@pytest.mark.asyncio
async def test_r5_3b_import_reaches_generation_writer_without_extract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """新章生成只读已保存声纹；不得顺手触发提取。"""
    import biyu.fingerprint.extractor as extractor
    from biyu.pipeline import generate_chapter

    def forbidden_extract(*_args, **_kwargs):
        raise AssertionError("生成路径不得触发外部文本提取")

    monkeypatch.setattr(extractor, "extract_fingerprint", forbidden_extract)
    _write(
        tmp_path / "book.json",
        '{"title":"夹具","genre":"xuanhuan","chapter_target_words":1000}',
    )
    _write(tmp_path / "worldbook.yaml", "facts:\n  - 测试设定\n")
    _write(tmp_path / "characters.yaml", "characters: []\n")
    _write(tmp_path / "outlines/ch1.md", "# 细纲\n")
    _write(tmp_path / "logs/ch1/planning.md", "status: 已批\n夹具方案")
    _select_imported_profile(tmp_path)
    writer = MagicMock()

    async def capture(adapter, messages, **kwargs):
        if adapter is writer:
            combined = "\n".join(
                item.get("content", "")
                for item in kwargs.get("cacheable_prefix", []) + messages
            )
            assert "R5_3B_RULE_SENTINEL" in combined
            assert "R5-3B_EXEMPLAR_SENTINEL" not in combined
            raise _WriterSeamReached
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
        with pytest.raises(_WriterSeamReached):
            await generate_chapter(
                book_dir=tmp_path,
                chapter_num=1,
                prompt_version="v4",
            )


def test_r5_3b_import_reaches_revision_writer_without_extract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """整章返修与新章生成读取同一份合并结果，且不触发提取。"""
    import biyu.editor.editor as editor_module
    import biyu.fingerprint.extractor as extractor
    from biyu.audit_reports.revisions import create_revision_package
    from biyu.git_helper import ensure_local_repository
    from biyu.pipeline import revise_chapter_from_package

    def forbidden_extract(*_args, **_kwargs):
        raise AssertionError("返修路径不得触发外部文本提取")

    monkeypatch.setattr(extractor, "extract_fingerprint", forbidden_extract)
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
                "issues": [{
                    "id": "ch1-001",
                    "description": "问题",
                    "suggestion": "建议",
                }],
            },
            ensure_ascii=False,
        ),
    )
    package = create_revision_package(
        tmp_path,
        1,
        selected_issue_ids=["ch1-001"],
        issue_comments={},
        general_comment="整体收紧",
        candidate_sha=hashlib.sha256("候选 v1".encode()).hexdigest(),
    )
    prompt = _write(tmp_path / "revision.md", "只输出修订后的完整正文")
    _select_imported_profile(tmp_path)

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
    combined = "\n".join(
        item["content"]
        for item in writer.calls[0]["messages"]
    )
    assert "R5_3B_RULE_SENTINEL" in combined
    assert "R5-3B_EXEMPLAR_SENTINEL" not in combined
