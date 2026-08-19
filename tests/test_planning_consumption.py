"""规划件消费测试：验证已批规划件被正确注入 Writer 上下文。"""
from __future__ import annotations

import ast
import inspect
import json
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from biyu.pipeline import _read_planning_status


class TestPlanningStatus:
    """测试规划件状态读取"""

    def test_read_planning_status_approved(self, tmp_path: Path):
        """已批规划件返回 status=已批"""
        planning_file = tmp_path / "planning.md"
        planning_file.write_text(
            "status: 已批\n"
            "# 第99章 创作者细纲\n"
            "## 戏核\n"
            "这一章埋着唯一词: 规划埋词测试XYZ\n",
            encoding="utf-8",
        )

        status, content = _read_planning_status(planning_file)

        assert status == "已批"
        assert "规划埋词测试XYZ" in content

    def test_read_planning_status_draft(self, tmp_path: Path):
        """草稿规划件返回 status=未批"""
        planning_file = tmp_path / "planning.md"
        planning_file.write_text(
            "status: 未批\n"
            "# 第99章 创作者细纲\n"
            "## 戏核\n这一章存在是为了测试\n",
            encoding="utf-8",
        )

        status, content = _read_planning_status(planning_file)

        assert status == "未批"
        assert "测试" in content

    def test_read_planning_status_no_status(self, tmp_path: Path):
        """无 status 字段的规划件返回 None"""
        planning_file = tmp_path / "planning.md"
        planning_file.write_text(
            "# 第99章 创作者细纲\n"
            "## 戏核\n这一章存在是为了测试\n",
            encoding="utf-8",
        )

        status, content = _read_planning_status(planning_file)

        assert status is None
        assert "测试" in content

    def test_read_planning_status_not_exists(self, tmp_path: Path):
        """不存在的规划件返回 (None, None)"""
        planning_file = tmp_path / "nonexistent.md"

        status, content = _read_planning_status(planning_file)

        assert status is None
        assert content is None

    def test_planner_alias_bound_before_approved_planning_branch(self):
        """已批跳过 Architect 时，meta 所需 planner_alias 也必须已绑定。"""
        from biyu.pipeline import generate_chapter

        tree = ast.parse(textwrap.dedent(inspect.getsource(generate_chapter)))
        alias_assignment = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "planner_alias"
                for target in node.targets
            )
        )
        planning_branch = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.UnaryOp)
            and isinstance(node.test.op, ast.Not)
            and isinstance(node.test.operand, ast.Name)
            and node.test.operand.id == "use_existing_planning"
        )

        assert alias_assignment.lineno < planning_branch.lineno

    def test_planning_response_bound_before_approved_planning_branch(self):
        """已批跳过 Architect 时，长跑统计所需 planning_resp 必须先绑定。"""
        from biyu.pipeline import generate_chapter

        tree = ast.parse(textwrap.dedent(inspect.getsource(generate_chapter)))
        response_assignment = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "planning_resp"
                for target in node.targets
            )
        )
        planning_branch = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.UnaryOp)
            and isinstance(node.test.op, ast.Not)
            and isinstance(node.test.operand, ast.Name)
            and node.test.operand.id == "use_existing_planning"
        )

        assert response_assignment.lineno < planning_branch.lineno


class TestPlanningConsumption:
    """测试规划件消费与埋词穿透"""

    def test_planning_file_structure_validation(self, tmp_path: Path):
        """验证规划件结构符合预期格式"""
        planning_file = tmp_path / "planning.md"
        planning_file.write_text(
            "status: 已批\n"
            "# 第99章 创作者细纲\n"
            "## 戏核\n这一章的存在是为了...\n"
            "## 戏核如何承载\n承载方式...\n"
            "## 笔墨分配\n关键处 40%,过渡处 60%\n"
            "## 与前后章的关系\n承 CH98,启 CH100\n"
            "## 硬信息锚点块\n- 时间:第99日\n- 人物:主角;配角\n",
            encoding="utf-8",
        )

        status, content = _read_planning_status(planning_file)

        assert status == "已批"
        # 验证关键节都在
        assert "## 戏核" in content
        assert "## 戏核如何承载" in content
        assert "## 笔墨分配" in content
        assert "## 与前后章的关系" in content
        assert "## 硬信息锚点块" in content

    def test_buried_word_in_planning(self, tmp_path: Path):
        """验证埋词在规划件中可被读取"""
        buried_word = "规划埋词唯一词ABC987"
        planning_file = tmp_path / "planning.md"
        planning_file.write_text(
            f"status: 已批\n"
            "# 第99章 创作者细纲\n"
            "## 戏核\n"
            f"这一章的存在是为了完成 {buried_word} 的埋词穿透测试。\n"
            "## 戏核如何承载\n...\n"
            "## 笔墨分配\n...\n"
            "## 与前后章的关系\n...\n"
            "## 硬信息锚点块\n"
            "- 人物:主角;配角;不存在的角色名XYZ123\n",
            encoding="utf-8",
        )

        status, content = _read_planning_status(planning_file)

        assert status == "已批"
        assert buried_word in content
        assert "不存在的角色名XYZ123" in content


class TestEditorPlanningCompliance:
    """测试 Editor 规划履约检查"""

    def test_editor_planning_parameter(self):
        """验证 build_editor_user_prompt 支持 planning 参数"""
        from biyu.editor.prompts import build_editor_user_prompt

        planning_text = (
            "status: 已批\n"
            "# 第99章 创作者细纲\n"
            "## 戏核\n这一章的存在是为了...\n"
            "## 硬信息锚点块\n"
            "- 人物:主角;配角;不存在的角色名XYZ123\n"
        )

        result = build_editor_user_prompt(
            chapter_num=99,
            chapter_text="这是正文内容...",
            characters_summary="主角:测试角色",
            prev_chapter_tail="上一章末尾...",
            planning=planning_text,
        )

        # 验证规划件被拼接到 prompt 中
        assert "创作者规划件(合同)" in result
        assert planning_text in result
        assert "不存在的角色名XYZ123" in result

    def test_editor_parser_supports_planning_compliance(self):
        """验证 parser 支持「规划履约」类型"""
        from biyu.editor.parser import VALID_TYPES

        assert "规划履约" in VALID_TYPES

    def test_editor_tools_schema_supports_planning_compliance(self):
        """验证 tools.py 支持「规划履约」类型"""
        from biyu.editor.tools import SUBMIT_REVIEW_SINGLE

        type_desc = SUBMIT_REVIEW_SINGLE["function"]["parameters"]["properties"]["issues"]["items"]["properties"]["type"]["description"]
        assert "规划履约" in type_desc


class TestPlanningComplianceDeterminism:
    """无合同跳过路径保持零 LLM 调用。"""

    _DIM8_TITLE = "**8. 规划履约**"
    _DIM8_BOUNDARY = '边界：没有规划件或规划件未标注"已批"时，输出"无合同，跳过"'

    def test_no_contract_physically_omits_dimension_8(self):
        from biyu.editor.prompts import build_editor_system_prompt

        prompt = build_editor_system_prompt(has_approved_planning=False)

        assert self._DIM8_TITLE not in prompt
        assert self._DIM8_BOUNDARY not in prompt
        assert "戏核位置" not in prompt
        assert "锚点人物在场" not in prompt

    def test_approved_contract_keeps_dimension_8_unchanged(self):
        from biyu.editor.prompts import EDITOR_SYSTEM_PROMPT, build_editor_system_prompt

        prompt = build_editor_system_prompt(has_approved_planning=True)

        assert prompt == EDITOR_SYSTEM_PROMPT
        assert self._DIM8_TITLE in prompt
        assert self._DIM8_BOUNDARY in prompt
        assert "戏核位置" in prompt
        assert "锚点人物在场" in prompt

    @staticmethod
    def _editor_response(issue_type: str) -> str:
        return json.dumps(
            {
                "issues": [
                    {
                        "line": 1,
                        "quote": "测试正文",
                        "quoted_text": "测试正文用于验证共享解析层的确定性过滤行为",
                        "type": issue_type,
                        "subtype": None,
                        "explanation": "测试说明",
                        "fix_suggestion": "这是一个足够具体且长度合规的测试修改建议",
                        "auto_fixable": False,
                        "severity": "medium",
                    }
                ],
                "queries_used": [],
                "confidence": "high",
            },
            ensure_ascii=False,
        )

    def test_no_contract_filters_fabricated_planning_issue_and_warns(self, capsys):
        from biyu.editor.parser import parse_editor_response

        result = parse_editor_response(
            self._editor_response("规划履约"),
            "测试正文用于验证共享解析层的确定性过滤行为",
            has_approved_planning=False,
        )

        captured = capsys.readouterr()
        assert result.issues == []
        assert "WARNING" in captured.out or "WARNING" in captured.err
        assert any("规划履约" in error for error in result.parse_errors)

    def test_approved_contract_preserves_planning_issue(self):
        from biyu.editor.parser import parse_editor_response

        result = parse_editor_response(
            self._editor_response("规划履约"),
            "测试正文用于验证共享解析层的确定性过滤行为",
            has_approved_planning=True,
        )

        assert [issue.type for issue in result.issues] == ["规划履约"]

    def test_planning_issue_quote_may_come_from_approved_contract(self):
        """规划履约的证据可引用合同；不能按“正文中不存在”误杀。"""
        from biyu.editor.parser import parse_editor_response

        payload = json.loads(self._editor_response("规划履约"))
        payload["issues"][0]["quote"] = "不存在的角色名XYZ123"
        result = parse_editor_response(
            json.dumps(payload, ensure_ascii=False),
            "测试正文没有该角色名",
            has_approved_planning=True,
            approved_planning_text="人物：主角；不存在的角色名XYZ123",
        )

        assert [issue.type for issue in result.issues] == ["规划履约"]

    def test_planning_issue_invented_contract_quote_is_filtered(self):
        """放行合同引用不能放松为任意捏造。"""
        from biyu.editor.parser import parse_editor_response

        payload = json.loads(self._editor_response("规划履约"))
        payload["issues"][0]["quote"] = "合同里并不存在的句子"
        result = parse_editor_response(
            json.dumps(payload, ensure_ascii=False),
            "测试正文也没有该句子",
            has_approved_planning=True,
            approved_planning_text="人物：主角；不存在的角色名XYZ123",
        )

        assert result.issues == []
        assert any("幻觉过滤" in error for error in result.parse_errors)

    def test_no_contract_preserves_non_planning_issue(self):
        from biyu.editor.parser import parse_editor_response

        result = parse_editor_response(
            self._editor_response("章内自洽"),
            "测试正文用于验证共享解析层的确定性过滤行为",
            has_approved_planning=False,
        )

        assert [issue.type for issue in result.issues] == ["章内自洽"]

    def test_parser_default_is_no_approved_contract(self):
        from biyu.editor.parser import parse_editor_response

        result = parse_editor_response(
            self._editor_response("规划履约"),
            "测试正文用于验证共享解析层的确定性过滤行为",
        )

        assert result.issues == []

    @pytest.mark.asyncio
    async def test_no_contract_skip_line_enters_single_agent_editor_section(self, tmp_path: Path):
        from biyu.editor.parser import EditorResult
        from biyu.pipeline import _editor_revision_loop

        with patch(
            "biyu.editor.editor.review_chapter",
            new_callable=AsyncMock,
            return_value=EditorResult(),
        ) as review_mock:
            _, editor_section, _ = await _editor_revision_loop(
                chapter_num=1,
                text="测试正文",
                book_dir=tmp_path,
                editor_adapter=MagicMock(),
                writer_adapter=MagicMock(),
                book=MagicMock(),
                _log_cost_fn=MagicMock(),
                planning="这是未批规划内容",
                has_approved_planning=False,
                max_revisions=1,
            )

        assert "规划履约:无合同,跳过" in editor_section
        assert review_mock.await_args.kwargs["has_approved_planning"] is False

    @pytest.mark.asyncio
    async def test_approved_contract_has_no_skip_line(self, tmp_path: Path):
        from biyu.editor.parser import EditorResult
        from biyu.pipeline import _editor_revision_loop

        with patch(
            "biyu.editor.editor.review_chapter",
            new_callable=AsyncMock,
            return_value=EditorResult(),
        ) as review_mock:
            _, editor_section, _ = await _editor_revision_loop(
                chapter_num=1,
                text="测试正文",
                book_dir=tmp_path,
                editor_adapter=MagicMock(),
                writer_adapter=MagicMock(),
                book=MagicMock(),
                _log_cost_fn=MagicMock(),
                planning="status: 已批\n这是已批规划内容",
                has_approved_planning=True,
                max_revisions=1,
            )

        assert "规划履约:无合同,跳过" not in editor_section
        assert review_mock.await_args.kwargs["has_approved_planning"] is True

    @pytest.mark.asyncio
    async def test_approved_contract_zero_deviation_has_visible_summary(self, tmp_path: Path):
        """雷6绿态：已批合同即使零偏离，报告也必须有确定性小结。"""
        from biyu.editor.parser import EditorResult
        from biyu.pipeline import _editor_revision_loop

        with patch(
            "biyu.editor.editor.review_chapter",
            new_callable=AsyncMock,
            return_value=EditorResult(),
        ):
            _, editor_section, _ = await _editor_revision_loop(
                chapter_num=1, text="测试正文", book_dir=tmp_path,
                editor_adapter=MagicMock(), writer_adapter=MagicMock(),
                book=MagicMock(), _log_cost_fn=MagicMock(),
                planning="status: 已批\n合同正文", has_approved_planning=True,
                max_revisions=1,
            )

        assert "规划履约:偏离 0" in editor_section

    @pytest.mark.asyncio
    async def test_approved_contract_summary_counts_only_parsed_planning_issues(self, tmp_path: Path):
        """雷6绿态：小结计数只数解析后的「规划履约」issue。"""
        from biyu.editor.parser import EditorIssue, EditorResult
        from biyu.pipeline import _editor_revision_loop

        issues = [
            EditorIssue(1, "a", "规划履约", None, "e", "f", True),
            EditorIssue(2, "b", "章内自洽", None, "e", "f", True),
            EditorIssue(3, "c", "规划履约", None, "e", "f", True),
        ]
        with patch(
            "biyu.editor.editor.review_chapter",
            new_callable=AsyncMock,
            return_value=EditorResult(issues=issues),
        ):
            _, editor_section, _ = await _editor_revision_loop(
                chapter_num=1, text="测试正文", book_dir=tmp_path,
                editor_adapter=MagicMock(), writer_adapter=MagicMock(),
                book=MagicMock(), _log_cost_fn=MagicMock(),
                planning="status: 已批\n合同正文", has_approved_planning=True,
                max_revisions=1,
            )

        assert "规划履约:偏离 2" in editor_section

    @pytest.mark.asyncio
    async def test_no_contract_skip_line_is_byte_for_byte_unchanged(self, tmp_path: Path):
        """雷6绿态：无合同分支保留既有小结的精确字节。"""
        from biyu.editor.parser import EditorResult
        from biyu.pipeline import _editor_revision_loop

        with patch(
            "biyu.editor.editor.review_chapter",
            new_callable=AsyncMock,
            return_value=EditorResult(),
        ):
            _, editor_section, _ = await _editor_revision_loop(
                chapter_num=1, text="测试正文", book_dir=tmp_path,
                editor_adapter=MagicMock(), writer_adapter=MagicMock(),
                book=MagicMock(), _log_cost_fn=MagicMock(),
                planning="未批合同", has_approved_planning=False,
                max_revisions=1,
            )

        assert editor_section.encode("utf-8") == (
            "规划履约:无合同,跳过\n\n"
            "### 第 1 轮审稿\n\n"
            "| # | 类型 | 严重度 | 行号 | 问题描述 | 建议 |\n"
            "|---|------|--------|------|----------|------|"
        ).encode("utf-8")
