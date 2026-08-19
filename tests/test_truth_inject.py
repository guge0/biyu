"""Tests for biyu.truth_inject — A3 实体过滤结构 + A1 实体识别/注入。

A3: 把 YAML truth 按"关键词/字符串过滤"整理(不建库,纯 dict/字符串)。
A1: 用 alias 预注册识别本章出场实体,只注入相关真值。
"""
from __future__ import annotations

import pytest

from biyu.truth_inject import (
    build_alias_registry,
    build_truth_injection_block,
    filter_truth_by_entities,
    identify_appearing_entities,
    build_filtered_truth_block,
)


# ---------------------------------------------------------------------------
# 夹具: 模拟 eval_set_v0 truth_files YAML 结构
# ---------------------------------------------------------------------------
@pytest.fixture()
def sample_truth():
    return {
        "characters": {
            "江叙白": {"status": "受委托第 9 天", "location": "临江市"},
            "苏蔓": {"status": "委托人", "location": "市一院"},
            "聂守仁": {"status": "未接触"},
        },
        "locations": {
            "回声巷": {"status": "未踩点"},
            "守拙斋": {"status": "仅档案照片"},
        },
        "clues": [
            {"id": "clue-001", "name": "苏皓最后通话基站定位回声巷", "status": "已获"},
            {"id": "clue-002", "name": "六名失踪者通报名单", "status": "已获"},
        ],
        "hooks": [
            {"id": "hook-001", "desc": "苏皓最后通话对象是谁", "status": "open", "from_chapter": "T0"},
            {"id": "hook-002", "desc": "警方结案口径", "status": "open", "from_chapter": "T0"},
        ],
    }


@pytest.fixture()
def sample_alias_registry():
    """{canonical: [aliases...]} —— 从 characters.yaml / anchors.yaml 预注册派生。"""
    return {
        "江叙白": ["江叙白", "江老师", "老江"],
        "苏蔓": ["苏蔓", "苏小姐"],
        "聂守仁": ["聂守仁", "聂老板"],
        "回声巷": ["回声巷"],
        "守拙斋": ["守拙斋"],
        "苏皓": ["苏皓"],
    }


# ---------------------------------------------------------------------------
# A3: filter_truth_by_entities
# ---------------------------------------------------------------------------
class TestFilterTruthByEntities:
    def test_keeps_character_in_appearing(self, sample_truth):
        out = filter_truth_by_entities(sample_truth, {"江叙白", "回声巷"})
        assert "江叙白" in out["characters"]
        assert "苏蔓" not in out["characters"]
        assert "聂守仁" not in out["characters"]

    def test_keeps_location_in_appearing(self, sample_truth):
        out = filter_truth_by_entities(sample_truth, {"守拙斋"})
        assert "守拙斋" in out["locations"]
        assert "回声巷" not in out["locations"]

    def test_keeps_clue_mentioning_appearing_entity(self, sample_truth):
        """clue name 含出场实体关键词 → 保留。"""
        out = filter_truth_by_entities(sample_truth, {"回声巷"})
        ids = [c["id"] for c in out["clues"]]
        assert "clue-001" in ids  # 提到回声巷
        assert "clue-002" not in ids  # 不涉及

    def test_keeps_hook_mentioning_appearing_entity(self, sample_truth):
        out = filter_truth_by_entities(sample_truth, {"苏皓"})
        ids = [h["id"] for h in out["hooks"]]
        assert "hook-001" in ids  # 提到苏皓
        assert "hook-002" not in ids

    def test_empty_appearing_drops_all_entries(self, sample_truth):
        """无出场实体 → 所有条目清空,结构保留。"""
        out = filter_truth_by_entities(sample_truth, set())
        assert out["characters"] == {}
        assert out["locations"] == {}
        assert out["clues"] == []
        assert out["hooks"] == []

    def test_preserves_structure_keys(self, sample_truth):
        """过滤后 dict 仍含全部顶层键(即便为空)。"""
        out = filter_truth_by_entities(sample_truth, {"江叙白"})
        assert set(out.keys()) == set(sample_truth.keys())

    def test_unknown_keys_passthrough_dropped(self):
        """truth 含未知顶层键(无 entity 概念)→ 该键原样保留(不过滤)。"""
        truth = {"meta": {"book": "test"}, "characters": {"江叙白": {"status": "x"}}}
        out = filter_truth_by_entities(truth, {"江叙白"})
        assert out["meta"] == {"book": "test"}
        assert "江叙白" in out["characters"]


# ---------------------------------------------------------------------------
# A1: identify_appearing_entities(alias 预注册)
# ---------------------------------------------------------------------------
class TestIdentifyAppearingEntities:
    def test_canonical_name_in_text(self, sample_alias_registry):
        out = identify_appearing_entities("江叙白走进回声巷", sample_alias_registry)
        assert "江叙白" in out
        assert "回声巷" in out

    def test_alias_hit(self, sample_alias_registry):
        """alias 出现 → canonical 被识别。"""
        out = identify_appearing_entities("苏小姐递来材料", sample_alias_registry)
        assert "苏蔓" in out

    def test_no_match_empty(self, sample_alias_registry):
        out = identify_appearing_entities("天下雨了", sample_alias_registry)
        assert out == set()

    def test_fullwidth_normalized(self, sample_alias_registry):
        """全角写法也命中(走 normalize)。"""
        out = identify_appearing_entities("江叙白", sample_alias_registry)
        assert "江叙白" in out


# ---------------------------------------------------------------------------
# A1: build_filtered_truth_block(prompt 注入文本)
# ---------------------------------------------------------------------------
class TestBuildFilteredTruthBlock:
    def test_block_contains_appearing_character(self, sample_truth, sample_alias_registry):
        text = "江叙白来到回声巷"
        block = build_filtered_truth_block(sample_truth, text, sample_alias_registry)
        assert "江叙白" in block
        assert "回声巷" in block
        # 苏蔓未出场 → 不注入
        assert "苏蔓" not in block

    def test_block_omits_unrelated_entries(self, sample_truth, sample_alias_registry):
        text = "聂守仁坐在守拙斋"
        block = build_filtered_truth_block(sample_truth, text, sample_alias_registry)
        assert "聂守仁" in block
        assert "守拙斋" in block
        # 江叙白/苏蔓/回声巷 未出场
        assert "江叙白" not in block
        assert "回声巷" not in block


# ---------------------------------------------------------------------------
# alias_registry 构建(从 characters.yaml 原始结构)
# ---------------------------------------------------------------------------
class TestBuildAliasRegistry:
    @pytest.fixture()
    def raw_characters(self):
        """模拟 characters.yaml 解析后的原始 dict(name → {..., aliases: {...}})。"""
        return {
            "江叙白": {
                "tier": "protagonist",
                "aliases": {
                    "narrator_default": "江叙白",
                    "self_referent": "我",
                    "called_by": {"苏蔓": "江老师", "何沛": "老江"},
                },
                "forbidden_in_narrative": ["主角", "记者江"],
            },
            "苏蔓": {
                "tier": "supporting",
                "aliases": {
                    "narrator_default": "苏蔓",
                    "self_referent": "我",
                    "called_by": {"江叙白": "苏小姐"},
                },
            },
        }

    def test_includes_narrator_default_and_called_by(self, raw_characters):
        reg = build_alias_registry(raw_characters)
        assert set(reg["江叙白"]) == {"江叙白", "江老师", "老江"}

    def test_excludes_self_referent(self, raw_characters):
        """self_referent '我' 太泛(所有第一人称都用),不进识别 registry。"""
        reg = build_alias_registry(raw_characters)
        assert "我" not in reg["江叙白"]

    def test_excludes_forbidden_in_narrative(self, raw_characters):
        """forbidden 标签不是识别别名。"""
        reg = build_alias_registry(raw_characters)
        assert "主角" not in reg["江叙白"]
        assert "记者江" not in reg["江叙白"]

    def test_no_aliases_section_safe(self):
        """角色无 aliases 段 → 仅用其名做别名。"""
        reg = build_alias_registry({"老覃": {"tier": "supporting"}})
        assert reg["老覃"] == ["老覃"]

    def test_accepts_pipeline_list_format(self):
        """管线 load_characters_yaml 返回 list[{name, aliases}], 也应接受。"""
        chars_list = [
            {"name": "江叙白", "tier": "protagonist",
             "aliases": {"narrator_default": "江叙白", "called_by": {"苏蔓": "江老师"}}},
            {"name": "苏蔓", "aliases": {"narrator_default": "苏蔓"}},
        ]
        reg = build_alias_registry(chars_list)
        assert set(reg["江叙白"]) == {"江叙白", "江老师"}
        assert reg["苏蔓"] == ["苏蔓"]

    def test_end_to_end_identify_via_built_registry(self, raw_characters):
        """构建出的 registry 直接喂 identify_appearing_entities。"""
        reg = build_alias_registry(raw_characters)
        out = identify_appearing_entities("苏小姐递来材料", reg)
        assert "苏蔓" in out
        assert "江叙白" not in out

    def test_augment_locations_from_truth(self, raw_characters, sample_truth):
        """truth 提供 → locations 键补进 registry(地点无 alias 预注册)。"""
        reg = build_alias_registry(raw_characters, truth=sample_truth)
        assert "回声巷" in reg
        assert reg["回声巷"] == ["回声巷"]
        # 角色别名仍在
        assert "江叙白" in reg


# ---------------------------------------------------------------------------
# 实例: 用 eval_set_v0 真实夹具演示"某章注入哪几条、过滤掉哪些"(§8 A1)
# ---------------------------------------------------------------------------
class TestRealFixtureExample:
    @pytest.fixture()
    def real_truth(self):
        import yaml
        truth = {}
        tdir = __import__("pathlib").Path("eval_set_v0/truth_files")
        for name in ("current_state.yaml", "particle_ledger.yaml", "pending_hooks.yaml"):
            with open(tdir / name, encoding="utf-8") as f:
                truth.update(yaml.safe_load(f))
        return truth

    @pytest.fixture()
    def real_registry(self, real_truth):
        import yaml
        with open("eval_set_v0/characters.yaml", encoding="utf-8") as f:
            raw_chars = yaml.safe_load(f)
        return build_alias_registry(raw_chars, truth=real_truth)

    def test_T2_injects_relevant_drops_absent(self, real_truth, real_registry):
        """§8 A1 实例: T2 present=[江叙白,苏蔓] → 只注入这俩, 过滤聂守仁/何沛/回声巷/守拙斋。"""
        from pathlib import Path

        t2 = Path("eval_set_v0/sub_md/T2.md").read_text(encoding="utf-8")
        block = build_filtered_truth_block(real_truth, t2, real_registry)

        # 注入(在场相关)
        assert "江叙白" in block
        assert "苏蔓" in block
        # 过滤(T2 outline 未出场 → 不注入, 关键词级)
        assert "聂守仁" not in block
        assert "何沛" not in block
        assert "回声巷" not in block
        assert "守拙斋" not in block


# ---------------------------------------------------------------------------
# 管线桥接: build_truth_injection_block(读 .md 内容 + 控制变量开关)
# ---------------------------------------------------------------------------
class TestBuildTruthInjectionBlock:
    """管线读 truth_files/*.md(eval 把 YAML 内容写进 .md)。
    filter_enabled=False → 原样拼接(改造前基线, D-45 控制变量钉死)。
    filter_enabled=True  → 解析 YAML + 实体过滤(改造后)。
    """

    @pytest.fixture()
    def truth_md(self):
        """模拟 read_all_truth_files 的产出: {filename: yaml_content_str}。"""
        return {
            "current_state.md": (
                "characters:\n"
                "  江叙白: {status: 受委托}\n"
                "  聂守仁: {status: 未接触}\n"
                "locations:\n"
                "  回声巷: {status: 未踩点}\n"
            ),
            "particle_ledger.md": "clues:\n  - {id: clue-001, name: 苏皓通话定位回声巷}\n",
            "pending_hooks.md": "hooks:\n  - {id: hook-001, desc: 苏皓通话对象}\n",
        }

    @pytest.fixture()
    def raw_characters(self):
        return {
            "江叙白": {"aliases": {"narrator_default": "江叙白", "self_referent": "我"}},
            "聂守仁": {"aliases": {"narrator_default": "聂守仁"}},
        }

    def test_filter_disabled_returns_all_concatenated(self, truth_md, raw_characters):
        """开关关 → 原样拼接全部 truth(D-45: 与改造前基线逐字一致)。"""
        block = build_truth_injection_block(
            truth_md, raw_characters,
            filter_text="江叙白来到回声巷",
            filter_enabled=False,
        )
        # 全部内容都在(未过滤)
        assert "江叙白" in block
        assert "聂守仁" in block
        assert "回声巷" in block
        assert "clue-001" in block

    def test_filter_enabled_drops_absent_entities(self, truth_md, raw_characters):
        """开关开 + 本章只有江叙白/回声巷 → 聂守仁被过滤。"""
        block = build_truth_injection_block(
            truth_md, raw_characters,
            filter_text="江叙白来到回声巷",
            filter_enabled=True,
        )
        assert "江叙白" in block
        assert "回声巷" in block
        assert "聂守仁" not in block

    def test_filter_disabled_is_pure_concatenation(self, truth_md, raw_characters):
        """开关关 → 输出等价于现有 pipeline 的 `=== name ===\\n{content}` 拼接。"""
        block = build_truth_injection_block(
            truth_md, raw_characters, filter_text="x", filter_enabled=False,
        )
        for name, content in truth_md.items():
            assert f"=== {name} ===" in block
            assert content.strip() in block

    # ----- A4-V0 Part 2 暴露的生产 bug: 非 YAML 容错 -----
    # 真实场景: Observer 在 T1 写入后把 current_state.md 改成 markdown 表格,
    # setup_book_dir 不清理 truth_files/, T2 读到混合内容 → 旧实现在
    # yaml.safe_load 上崩溃使整章失败。修复要求:跳过不可解析条目而非崩溃。
    @pytest.fixture()
    def markdown_table_md(self):
        """Observer-style markdown 表格(非合法 YAML)。"""
        return (
            "| 类别 | 条目 | 状态 |\n"
            "| --- | --- | --- |\n"
            "| 角色 | 江叙白 | 在场 |\n"
        )

    def test_filter_enabled_skips_unparseable_entries(
        self, raw_characters, markdown_table_md
    ):
        """开关开 + truth_md 含非 YAML(markdown 表格)→ 跳过该条目, 不崩溃。

        场景对应 A4-V0 Part 2 的 T2/T3 真实情况: Observer 在 T1 写入了
        current_state.md(表格格式), 与冻结 FT1_current_state.yaml 并存。
        修复要求: 跳过表格条目, 但 YAML 仍参与过滤。
        """
        # 模拟真实 book_dir/truth_files/ 内容(Observer 表格 + 冻结 YAML 共存)
        mixed = {
            "current_state.md": markdown_table_md,  # Observer 覆写, 非 YAML
            "FT1_current_state.md": (  # 冻结 YAML, 合法
                "characters:\n"
                "  江叙白: {status: 已夜访守拙斋}\n"
                "locations:\n"
                "  回声巷: {status: 未踩点}\n"
            ),
        }
        block = build_truth_injection_block(
            mixed, raw_characters,
            filter_text="江叙白来到回声巷",
            filter_enabled=True,
        )
        # 冻结 YAML 解析成功 + 江叙白/回声巷 出场 → 注入
        assert "江叙白" in block
        assert "回声巷" in block
        # markdown 表格被跳过(不进 prompt 块)
        assert "类别" not in block

    def test_filter_enabled_all_unparseable_returns_empty(
        self, raw_characters, markdown_table_md
    ):
        """全部条目都不可解析 → 返回空块(不注入任何 truth), 不崩溃。"""
        all_bad = {
            "current_state.md": markdown_table_md,
            "particle_ledger.md": markdown_table_md,
        }
        block = build_truth_injection_block(
            all_bad, raw_characters,
            filter_text="江叙白",
            filter_enabled=True,
        )
        assert block == ""

    def test_filter_disabled_concatenates_unparseable_too(
        self, raw_characters, markdown_table_md
    ):
        """控制变量: 开关关时 markdown 表格仍原样拼接(D-45 基线逐字不变)。"""
        truth_md = {"current_state.md": markdown_table_md}
        block = build_truth_injection_block(
            truth_md, raw_characters, filter_text="x", filter_enabled=False,
        )
        assert "类别" in block  # 表格头原样进 prompt
        assert "| 角色 | 江叙白 | 在场 |" in block
