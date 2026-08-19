from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from biyu.editor.prompts import (
    EDITOR_SYSTEM_PROMPT,
    build_editor_system_prompt,
    build_editor_user_prompt,
)
from biyu.prompts.chapter_writer import build_writer_prompt_v4


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_FIXTURE = json.loads(
    (ROOT / "tests" / "fixtures" / "r2_prompt_goldens.json").read_text(encoding="utf-8")
)
GOLDENS = GOLDEN_FIXTURE["current"]


def _fingerprint(text: str) -> dict[str, int | str]:
    encoded = text.encode("utf-8")
    return {
        "chars": len(text),
        "utf8_bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _assembled_prompts() -> dict[str, str]:
    writer_system, writer_user = build_writer_prompt_v4(
        chapter_num=7,
        worldbook={"protagonist": "测试主角", "facts": ["主角姓名:旧占位", "核心事实A"]},
        worldbook_prompt="世界观样例",
        characters=[
            {
                "name": "测试主角",
                "tier": "protagonist",
                "background": "背景A",
                "voice_examples": ["语声A"],
                "personality": "性格A",
                "aliases": {
                    "narrator_default": "主角",
                    "self_referent": "我",
                    "called_by": {"同伴": "阿测"},
                },
                "forbidden_in_narrative": ["工程代号"],
            },
            {
                "name": "同伴",
                "tier": "supporting",
                "personality": "性格B",
                "status": "active",
                "current_location": "地点B",
                "current_emotional_state": "紧张",
                "current_power_level": "二阶",
            },
        ],
        truth_files_block="故事现状样例",
        prev_tail="上一章末样例",
        context_block="历史章节样例",
        outline="创作者细纲样例",
        planning="导演规划样例",
        target_words=4321,
        present_characters=["测试主角", "同伴"],
    )
    return {
        "writer_system": writer_system,
        "writer_user_full": writer_user,
        "editor_system": EDITOR_SYSTEM_PROMPT,
        "editor_system_without_planning": build_editor_system_prompt(
            has_approved_planning=False
        ),
        "editor_user_full": build_editor_user_prompt(
            7,
            "正文样例",
            characters_summary="角色速查样例",
            prev_chapter_tail="上一章末样例",
            planning="已批规划样例",
        ),
    }


def test_full_prompt_goldens_match_baseline_or_approved_differences():
    actual = {name: _fingerprint(text) for name, text in _assembled_prompts().items()}
    assert actual == GOLDENS
    changed = {
        name
        for name, baseline in GOLDEN_FIXTURE["baseline"].items()
        if baseline != GOLDEN_FIXTURE["current"][name]
    }
    assert changed == {
        "writer_user_full",
        "editor_system",
        "editor_system_without_planning",
    }
    assert len(GOLDEN_FIXTURE["approved_differences"]) == 7


def test_author_editable_prompt_files_have_one_root_home():
    expected = {
        ROOT / "prompts" / "writer" / "system.md",
        ROOT / "prompts" / "writer" / "layer3.md",
        ROOT / "prompts" / "writer" / "fragments.json",
        ROOT / "prompts" / "editor" / "system.md",
        ROOT / "prompts" / "editor" / "fragments.json",
    }
    assert all(path.is_file() for path in expected)


def test_old_long_prompt_text_is_absent_from_python_sources():
    writer_source = (ROOT / "src" / "biyu" / "prompts" / "chapter_writer.py").read_text(
        encoding="utf-8"
    )
    editor_source = (ROOT / "src" / "biyu" / "editor" / "prompts.py").read_text(
        encoding="utf-8"
    )
    assert "你是中文网文作者" not in writer_source
    assert "破折号(——)≤ 3 次/千字" not in writer_source
    assert "你是这本中文网文的责任编辑" not in editor_source
    assert "**8. 规划履约** ——" not in editor_source


def test_missing_prompt_file_fails_fresh_process_loudly():
    prompt_file = ROOT / "prompts" / "editor" / "system.md"
    displaced = prompt_file.with_suffix(".md.r2-missing")
    assert not displaced.exists()

    prompt_file.rename(displaced)
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import biyu.editor.prompts"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={
                **os.environ,
                "PYTHONPATH": str(ROOT / "src")
                + os.pathsep
                + os.environ.get("PYTHONPATH", ""),
            },
            check=False,
        )
    finally:
        displaced.rename(prompt_file)

    assert result.returncode != 0
    assert "Required prompt file could not be read" in result.stderr
    assert str(prompt_file) in result.stderr
