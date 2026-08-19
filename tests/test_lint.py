"""biyu lint 集成测试 — 使用模拟数据跑完整 lint 流程。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from biyu.lint_rules import run_lint
from biyu.lint_rules.base import LintContext


@pytest.fixture
def book_dir(tmp_path):
    """创建模拟书目录结构。"""
    bd = tmp_path / "test_book"
    bd.mkdir()
    (bd / "book.json").write_text('{"title": "test"}', encoding="utf-8")

    # characters.yaml
    chars = {
        "characters": [
            {"name": "张今空", "tier": "protagonist",
             "abilities": "金手指『奖励变异』",
             "aliases": {"called_by": {"周大龙": "今空"}}},
            {"name": "周大龙", "tier": "major_supporting"},
            {"name": "路人甲", "tier": "npc"},
        ],
    }
    (bd / "characters.yaml").write_text(
        yaml.dump(chars, allow_unicode=True), encoding="utf-8"
    )

    # worldbook.yaml
    wb = {
        "facts": [
            "主角姓名：张今空",
            "主角金手指：奖励变异",
        ],
        "forbidden": [
            "不得出现未在 characters.yaml 中注册的有名角色",
            "禁令-破折号：严格遵循 punctuation 规则",
        ],
        "visual_symbols": [
            {"symbol": "金色光晕", "assigned_to": "外部观察者", "chapters": "CH12-15"},
        ],
        "timeline": ["CH1-CH3：第一次秘境——三国·赤壁之战"],
        "narrative_anchors": {
            "writing_constraints": {
                "pov_consistency": ["秘境源世界中的角色（如曹操、关羽等）"],
            },
        },
    }
    (bd / "worldbook.yaml").write_text(
        yaml.dump(wb, allow_unicode=True), encoding="utf-8"
    )

    # pending_hooks
    hooks_dir = bd / "truth_files"
    hooks_dir.mkdir()
    (hooks_dir / "pending_hooks.md").write_text(
        "| hook_id | 起始章节 | 类型 | 状态 | 最近推进 | 预期回收 | 备注 |\n"
        "|---------|---------|------|------|---------|---------|------|\n"
        "| hook_01 | 1 | 设定伏笔 | closed | 已回收 | CH10 | 已回收 |\n"
        "| hook_02 | 5 | 角色伏笔 | open | 无 | CH20 | 张父渊源 |\n",
        encoding="utf-8",
    )

    # outlines dir
    (bd / "outlines").mkdir()
    (bd / "chapters").mkdir()

    return bd


def _write_outline(outlines_dir: Path, name: str, content: str) -> Path:
    """写入 outline 文件。"""
    p = outlines_dir / name
    p.write_text(content, encoding="utf-8")
    return p


class TestLintIntegration:
    def test_clean_outline(self, book_dir):
        """集成测试 1：正常 outline，已知角色，无冲突。"""
        events = "\n".join(f"- **事件{i}**: 张今空和周大龙做某事" for i in range(6))
        outline = _write_outline(
            book_dir / "outlines", "ch25.md",
            f"---\npresent_characters:\n  - 张今空\n  - 周大龙\n---\n"
            f"# 关键事件\n{events}\n",
        )

        ctx = LintContext(
            book_dir=book_dir,
            characters=yaml.safe_load(
                (book_dir / "characters.yaml").read_text(encoding="utf-8")
            ).get("characters", []),
            worldbook=yaml.safe_load(
                (book_dir / "worldbook.yaml").read_text(encoding="utf-8")
            ),
            pending_hooks=[
                {"hook_id": "hook_01", "状态": "closed", "预期回收": "CH10", "备注": "已回收"},
            ],
        )

        issues = run_lint(outline, ctx)
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0, f"不应有 error，但发现: {[i.message for i in errors]}"

    def test_collision_and_unknown_char(self, book_dir):
        """集成测试 2：含视觉符号撞色 + 未知角色。"""
        outline = _write_outline(
            book_dir / "outlines", "ch20.md",
            "---\npresent_characters:\n  - 张今空\n  - 神秘人Y\n---\n"
            "# 关键事件\n"
            "- 神秘人Y：你好\n"
            "- 金色光晕包裹了他\n",
        )

        ctx = LintContext(
            book_dir=book_dir,
            characters=yaml.safe_load(
                (book_dir / "characters.yaml").read_text(encoding="utf-8")
            ).get("characters", []),
            worldbook=yaml.safe_load(
                (book_dir / "worldbook.yaml").read_text(encoding="utf-8")
            ),
        )

        issues = run_lint(outline, ctx)
        # 应该有符号撞色 warning
        collision = [i for i in issues if "撞色" in i.message]
        assert len(collision) >= 1

        # 应该有未知角色 error
        unknown = [i for i in issues if "神秘人Y" in i.message and i.severity == "error"]
        assert len(unknown) >= 1

    def test_forbidden_violation(self, book_dir):
        """集成测试 3：含 forbidden 违反（破折号密度）。"""
        dashes = "——" * 20
        outline = _write_outline(
            book_dir / "outlines", "ch30.md",
            f"---\npresent_characters:\n  - 张今空\n---\n"
            f"# 关键事件\n{dashes} 短文本\n",
        )

        ctx = LintContext(
            book_dir=book_dir,
            characters=yaml.safe_load(
                (book_dir / "characters.yaml").read_text(encoding="utf-8")
            ).get("characters", []),
            worldbook=yaml.safe_load(
                (book_dir / "worldbook.yaml").read_text(encoding="utf-8")
            ),
        )

        issues = run_lint(outline, ctx)
        dash_issues = [i for i in issues if "破折号" in i.message]
        assert len(dash_issues) >= 1
        assert dash_issues[0].severity == "warning"
