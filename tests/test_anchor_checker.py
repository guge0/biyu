"""Tests for tools.anchor_checker."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from tools.anchor_checker import (
    check_atomic,
    check_composite,
    compute_stats,
    generate_json_report,
    generate_md_report,
    normalize,
    run_check,
    run_check_text,
    run_two_layer_check,
)

# B1 slot-pattern 原语(P6-A2/B1):从引擎源直接 import
from biyu.anchor_check import (  # noqa: F401
    cn2num,
    normalize_number_unit,
    normalize_time_hm,
)
# B2 slot form mismatch(P6-A2/B2)
from biyu.anchor_check import _check_slot_form_mismatch


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------
class TestNormalize:
    def test_halfwidth_unchanged(self):
        assert normalize("A-113") == "A-113"

    def test_fullwidth_to_halfwidth(self):
        assert normalize("Ａ－１１３") == "A-113"

    def test_fullwidth_alpha(self):
        assert normalize("ＡＢＣ") == "ABC"

    def test_whitespace_collapse(self):
        assert normalize("回声  巷　17号") == "回声 巷 17号"

    def test_strip(self):
        assert normalize("  hello  ") == "hello"

    def test_fullwidth_number(self):
        assert normalize("０７号") == "07号"

    def test_mixed_full_half(self):
        """全半角混写场景"""
        assert normalize("Ａ-113") == "A-113"


# ---------------------------------------------------------------------------
# Atomic 命中
# ---------------------------------------------------------------------------
class TestCheckAtomic:
    @pytest.fixture()
    def sample_anchors(self):
        return [
            {"id": "T1-H01", "type": "时间", "canonical": "十一点二十", "aliases": ["23:20"]},
            {"id": "T1-H02", "type": "地点", "canonical": "回声巷17号", "aliases": ["回声巷十七号"]},
            {"id": "T1-H03", "type": "地点", "canonical": "守拙斋", "aliases": []},
        ]

    def test_canonical_hit(self, sample_anchors):
        text = "他十一点二十抵达回声巷巷口"
        results = check_atomic(sample_anchors, text)
        assert results[0]["hit"] is True
        assert results[0]["hit_by"] == "十一点二十"

    def test_alias_hit(self, sample_anchors):
        text = "他23:20抵达回声巷巷口"
        results = check_atomic(sample_anchors, text)
        assert results[0]["hit"] is True
        assert results[0]["hit_by"] == "23:20"

    def test_miss(self, sample_anchors):
        text = "他在中午十二点到了公司"
        results = check_atomic(sample_anchors, text)
        assert results[0]["hit"] is False
        assert results[0]["hit_by"] is None

    def test_chinese_number_alias_hit(self, sample_anchors):
        text = "回声巷十七号在巷尾"
        results = check_atomic(sample_anchors, text)
        assert results[1]["hit"] is True
        assert results[1]["hit_by"] == "回声巷十七号"

    def test_fullwidth_alias_normalization(self):
        anchors = [
            {"id": "T1-H09", "type": "数字", "canonical": "07号黄铜钥匙", "aliases": ["编号07", "零七号"]},
        ]
        text = "他拿到了编号０７的钥匙"
        results = check_atomic(anchors, text)
        assert results[0]["hit"] is True

    def test_cross_chapter_field_preserved(self):
        anchors = [
            {
                "id": "T3-H01", "type": "时间", "canonical": "上午十点",
                "aliases": ["早上十点", "10点"], "cross_chapter_of": "T1-H13",
            },
        ]
        text = "上午十点到了档案馆"
        results = check_atomic(anchors, text)
        assert results[0]["hit"] is True
        assert results[0]["cross_chapter_of"] == "T1-H13"


# ---------------------------------------------------------------------------
# Value-match(三态: present / missing / value_mismatch)— P6-A2
# 纯子串字符比对, distractor 来自夹具 mismatch_aliases, 不造归一化引擎。
# ---------------------------------------------------------------------------
class TestValueMatch:
    @pytest.fixture()
    def vm_anchors(self):
        return [
            {
                "id": "T1-H16", "type": "数字", "canonical": "A-113",
                "aliases": ["A113"], "mismatch_aliases": ["A-131", "A131"],
            },
            {
                "id": "T1-H14", "type": "地点", "canonical": "市档案馆三楼",
                "aliases": ["档案馆三楼"], "mismatch_aliases": ["档案馆二楼", "档案馆四楼"],
            },
            {
                "id": "T1-H05", "type": "设定", "canonical": "黑色手套",
                "aliases": ["黑手套"], "mismatch_aliases": ["白手套"],
            },
            # 无 mismatch_aliases 的锚(向后兼容)
            {
                "id": "T1-H03", "type": "地点", "canonical": "守拙斋",
                "aliases": [],
            },
        ]

    def test_value_mismatch_when_distractor_present(self, vm_anchors):
        """正文里出现错值 distractor、canonical 未出现 → value_mismatch。"""
        text = "他翻到案卷编号A-131的那一页"
        results = check_atomic(vm_anchors, text)
        assert results[0]["status"] == "value_mismatch"
        assert results[0]["hit"] is False
        assert results[0]["mismatch_by"] == "A-131"

    def test_canonical_wins_over_distractor(self, vm_anchors):
        """canonical 与 distractor 都在 → 以 canonical 为准(present)。"""
        text = "正卷是A-113,旁边草稿误写成A-131"
        results = check_atomic(vm_anchors, text)
        assert results[0]["status"] == "present"
        assert results[0]["hit"] is True
        assert results[0]["mismatch_by"] is None

    def test_missing_when_neither_present(self, vm_anchors):
        """canonical 与 distractor 都没出现 → missing。"""
        text = "他在街上漫无目的地走"
        results = check_atomic(vm_anchors, text)
        assert results[0]["status"] == "missing"
        assert results[0]["hit"] is False
        assert results[0]["mismatch_by"] is None

    def test_value_mismatch_floor(self, vm_anchors):
        text = "他上了市档案馆二楼"
        results = check_atomic(vm_anchors, text)
        assert results[1]["status"] == "value_mismatch"
        assert results[1]["mismatch_by"] == "档案馆二楼"

    def test_value_mismatch_color(self, vm_anchors):
        text = "聂守仁戴着白手套"
        results = check_atomic(vm_anchors, text)
        assert results[2]["status"] == "value_mismatch"

    def test_backward_compat_present(self, vm_anchors):
        """无 mismatch_aliases 的锚:命中=present。"""
        text = "他走进守拙斋"
        results = check_atomic(vm_anchors, text)
        assert results[3]["status"] == "present"
        assert results[3]["hit"] is True

    def test_backward_compat_missing(self, vm_anchors):
        """无 mismatch_aliases 的锚:未命中=missing,绝不报 value_mismatch。"""
        text = "他在街上走"
        results = check_atomic(vm_anchors, text)
        assert results[3]["status"] == "missing"
        assert results[3]["hit"] is False
        assert results[3]["mismatch_by"] is None

    def test_value_mismatch_distractor_normalized(self, vm_anchors):
        """distractor 全角写法也应命中(走 normalize)。"""
        text = "案卷编号Ａ-１３１"  # 全角 A-131
        results = check_atomic(vm_anchors, text)
        assert results[0]["status"] == "value_mismatch"


# ---------------------------------------------------------------------------
# Value-match 统计分桶 — P6-A2
# ---------------------------------------------------------------------------
class TestValueMatchStats:
    def test_stats_count_value_mismatch(self):
        atomic = [
            {"id": "H1", "type": "数字", "hit": True, "status": "present", "canonical": "A-113", "cross_chapter_of": None},
            {"id": "H2", "type": "地点", "hit": False, "status": "value_mismatch", "canonical": "三楼", "cross_chapter_of": None},
            {"id": "H3", "type": "时间", "hit": False, "status": "missing", "canonical": "十点", "cross_chapter_of": None},
        ]
        stats = compute_stats("T1", atomic)
        assert stats["atomic"]["hit"] == 1
        assert stats["atomic"]["value_mismatch"] == 1
        assert stats["atomic"]["miss"] == 1
        assert stats["atomic"]["total"] == 3

    def test_stats_backward_compat_no_status(self):
        """无 status 字段的旧结果: 按 hit 推导, value_mismatch=0。"""
        atomic = [
            {"id": "H1", "type": "时间", "hit": True, "canonical": "A", "cross_chapter_of": None},
            {"id": "H2", "type": "时间", "hit": False, "canonical": "B", "cross_chapter_of": None},
        ]
        stats = compute_stats("T1", atomic)
        assert stats["atomic"]["hit"] == 1
        assert stats["atomic"]["value_mismatch"] == 0
        assert stats["atomic"]["miss"] == 1


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------
class TestCheckComposite:
    def test_all_members_hit(self):
        atomic_results = [
            {"id": "T1-H13", "hit": True},
            {"id": "T1-H14", "hit": True},
            {"id": "T1-H12", "hit": True},
            {"id": "T1-H15", "hit": True},
        ]
        composite = [{"id": "T1-C01", "name": "约定·档案馆碰头", "members": ["T1-H13", "T1-H14", "T1-H12", "T1-H15"]}]
        results = check_composite(composite, atomic_results)
        assert results[0]["all_hit"] is True

    def test_one_member_miss(self):
        atomic_results = [
            {"id": "T1-H13", "hit": True},
            {"id": "T1-H14", "hit": False},
            {"id": "T1-H12", "hit": True},
            {"id": "T1-H15", "hit": True},
        ]
        composite = [{"id": "T1-C01", "name": "约定·档案馆碰头", "members": ["T1-H13", "T1-H14", "T1-H12", "T1-H15"]}]
        results = check_composite(composite, atomic_results)
        assert results[0]["all_hit"] is False

    def test_single_member_composite(self):
        atomic_results = [
            {"id": "T1-H17", "hit": True},
        ]
        composite = [{"id": "T1-C02", "name": "约定·不单独进当铺", "members": ["T1-H17"]}]
        results = check_composite(composite, atomic_results)
        assert results[0]["all_hit"] is True


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------
class TestComputeStats:
    def test_basic_stats(self):
        atomic = [
            {"id": "H1", "type": "时间", "hit": True, "canonical": "A", "cross_chapter_of": None},
            {"id": "H2", "type": "时间", "hit": False, "canonical": "B", "cross_chapter_of": None},
            {"id": "H3", "type": "地点", "hit": True, "canonical": "C", "cross_chapter_of": None},
        ]
        stats = compute_stats("T1", atomic)
        assert stats["atomic"]["total"] == 3
        assert stats["atomic"]["hit"] == 2
        assert stats["atomic"]["ratio"] == pytest.approx(2 / 3)

    def test_by_type(self):
        atomic = [
            {"id": "H1", "type": "时间", "hit": True, "canonical": "A", "cross_chapter_of": None},
            {"id": "H2", "type": "时间", "hit": False, "canonical": "B", "cross_chapter_of": None},
            {"id": "H3", "type": "地点", "hit": True, "canonical": "C", "cross_chapter_of": None},
        ]
        stats = compute_stats("T1", atomic)
        assert stats["by_type"]["时间"]["total"] == 2
        assert stats["by_type"]["时间"]["hit"] == 1
        assert stats["by_type"]["地点"]["total"] == 1
        assert stats["by_type"]["地点"]["hit"] == 1

    def test_cross_chapter_subset(self):
        atomic = [
            {"id": "H1", "type": "时间", "hit": True, "canonical": "A", "cross_chapter_of": None},
            {"id": "H2", "type": "地点", "hit": False, "canonical": "B", "cross_chapter_of": "T1-H14"},
        ]
        stats = compute_stats("T3", atomic)
        assert stats["cross_chapter"]["total"] == 1
        assert stats["cross_chapter"]["hit"] == 0

    def test_empty_cross_chapter(self):
        atomic = [
            {"id": "H1", "type": "时间", "hit": True, "canonical": "A", "cross_chapter_of": None},
        ]
        stats = compute_stats("T1", atomic)
        assert stats["cross_chapter"]["total"] == 0


# ---------------------------------------------------------------------------
# 端到端: run_check 用临时文件
# ---------------------------------------------------------------------------
class TestRunCheck:
    @pytest.fixture()
    def tmp_yaml(self, tmp_path):
        data = {
            "T1": {
                "atomic": [
                    {"id": "T1-H01", "type": "时间", "canonical": "十一点二十", "aliases": ["23:20"]},
                    {"id": "T1-H02", "type": "地点", "canonical": "回声巷17号", "aliases": ["回声巷十七号"]},
                    {"id": "T1-H03", "type": "地点", "canonical": "守拙斋", "aliases": []},
                ],
                "composite": [
                    {"id": "T1-C01", "name": "测试组合", "members": ["T1-H01", "T1-H02"]},
                ],
            }
        }
        p = tmp_path / "anchors.yaml"
        p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
        return p

    def test_full_run(self, tmp_yaml, tmp_path):
        text = "他十一点二十到了回声巷17号，走进守拙斋。"
        text_file = tmp_path / "T1_test.md"
        text_file.write_text(text, encoding="utf-8")

        report = run_check(str(tmp_yaml), str(text_file), "T1")
        assert report["chapter"] == "T1"
        assert report["stats"]["atomic"]["total"] == 3
        assert report["stats"]["atomic"]["hit"] == 3
        assert report["stats"]["atomic"]["ratio"] == 1.0
        assert report["stats"]["composite"]["hit"] == 1

    def test_partial_hit(self, tmp_yaml, tmp_path):
        text = "他去了回声巷17号，但没进守拙斋。"  # 缺十一点二十
        text_file = tmp_path / "T1_test2.md"
        text_file.write_text(text, encoding="utf-8")

        report = run_check(str(tmp_yaml), str(text_file), "T1")
        # 回声巷17号命中, 守拙斋也命中(子串), 十一点二十未命中
        assert report["stats"]["atomic"]["hit"] == 2
        assert report["stats"]["composite"]["hit"] == 0  # T1-H01缺失导致composite失败

    def test_chapter_id_inference(self, tmp_yaml, tmp_path):
        text = "十一点二十，回声巷17号，守拙斋。"
        text_file = tmp_path / "T1_clean.md"
        text_file.write_text(text, encoding="utf-8")

        report = run_check(str(tmp_yaml), str(text_file))
        assert report["chapter"] == "T1"

    def test_run_check_text_inmemory(self, tmp_yaml):
        """run_check_text 接受内存文本(细纲层 planning_text 不落盘)。"""
        text = "十一点二十，回声巷17号，守拙斋。"
        report = run_check_text(str(tmp_yaml), text, "T1")
        assert report["chapter"] == "T1"
        assert report["stats"]["atomic"]["hit"] == 3
        assert report["stats"]["atomic"]["ratio"] == 1.0


# ---------------------------------------------------------------------------
# 报告格式
# ---------------------------------------------------------------------------
class TestReportGeneration:
    @pytest.fixture()
    def sample_results(self):
        return [{
            "chapter": "T1",
            "source_file": "baseline/T1_clean.md",
            "atomic_results": [
                {"id": "T1-H01", "type": "时间", "canonical": "十一点二十", "hit": True, "hit_by": "十一点二十", "status": "present", "mismatch_by": None, "cross_chapter_of": None},
                {"id": "T1-H02", "type": "地点", "canonical": "回声巷17号", "hit": False, "hit_by": None, "status": "missing", "mismatch_by": None, "cross_chapter_of": None},
            ],
            "composite_results": [],
            "stats": {
                "atomic": {"total": 2, "hit": 1, "value_mismatch": 0, "miss": 1, "ratio": 0.5},
                "by_type": {
                    "时间": {"total": 1, "hit": 1, "value_mismatch": 0, "miss": 0, "ratio": 1.0},
                    "地点": {"total": 1, "hit": 0, "value_mismatch": 0, "miss": 1, "ratio": 0.0},
                },
                "cross_chapter": {"total": 0, "hit": 0, "ratio": None},
            },
        }]

    def test_json_report(self, sample_results, tmp_path):
        out = tmp_path / "report.json"
        generate_json_report(sample_results, out)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["chapter"] == "T1"

    def test_md_report(self, sample_results, tmp_path):
        out = tmp_path / "report.md"
        generate_md_report(sample_results, out)
        content = out.read_text(encoding="utf-8")
        assert "# Anchor Check Report" in content
        assert "T1" in content
        assert "50.0%" in content


# ---------------------------------------------------------------------------
# 两层便利函数: 细纲层(skeleton) + 正文层(body)— P6-A2 转正
# ---------------------------------------------------------------------------
class TestTwoLayerCheck:
    @pytest.fixture()
    def tmp_yaml(self, tmp_path):
        data = {
            "T1": {
                "atomic": [
                    {"id": "T1-H01", "type": "时间", "canonical": "十一点二十", "aliases": ["23:20"]},
                    {"id": "T1-H02", "type": "地点", "canonical": "回声巷17号", "aliases": ["回声巷十七号"]},
                    {"id": "T1-H03", "type": "地点", "canonical": "守拙斋", "aliases": []},
                    {
                        "id": "T1-H09", "type": "数字", "canonical": "A-113",
                        "aliases": ["A113"], "mismatch_aliases": ["A-131"],
                    },
                ],
            }
        }
        p = tmp_path / "anchors.yaml"
        p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
        return p

    def test_returns_skeleton_and_body_keys(self, tmp_yaml):
        """返回 dict 含 skeleton / body 两份独立报告。"""
        out = run_two_layer_check(
            str(tmp_yaml), "T1",
            skeleton_text="十一点二十，回声巷17号。",
            body_text="十一点二十，回声巷17号，守拙斋。",
        )
        assert "skeleton" in out
        assert "body" in out
        assert out["skeleton"]["chapter"] == "T1"
        assert out["body"]["chapter"] == "T1"

    def test_layers_independent(self, tmp_yaml):
        """细纲缺守拙斋/A-113、正文齐全 → skeleton 在场 2, body 全在场。"""
        out = run_two_layer_check(
            str(tmp_yaml), "T1",
            skeleton_text="十一点二十，回声巷17号。",
            body_text="十一点二十，回声巷17号，守拙斋，案卷编号A-113。",
        )
        assert out["skeleton"]["stats"]["atomic"]["hit"] == 2
        assert out["skeleton"]["stats"]["atomic"]["miss"] == 2
        assert out["body"]["stats"]["atomic"]["hit"] == 4
        assert out["body"]["stats"]["atomic"]["ratio"] == 1.0

    def test_value_mismatch_in_body(self, tmp_yaml):
        """正文层出现错值 distractor → body 报 value_mismatch。"""
        out = run_two_layer_check(
            str(tmp_yaml), "T1",
            skeleton_text="编号A-113待定。",
            body_text="翻到案卷编号A-131的那一页。",
        )
        assert out["body"]["stats"]["atomic"]["value_mismatch"] == 1
        # skeleton 层 canonical 在场, 无错值
        assert out["skeleton"]["stats"]["atomic"]["value_mismatch"] == 0


# ---------------------------------------------------------------------------
# B1 slot-pattern 原语 — P6-A2/B1
# 确定性结构化抽取(正则 + 中文数字解析),不破 D-43 精神(无语义同义)。
# ---------------------------------------------------------------------------
class TestCn2Num:
    """中文数字 → 阿拉伯(0-9999,覆盖时间/页数/年份用例)。"""

    def test_single_digit(self):
        assert cn2num("六") == 6
        assert cn2num("三") == 3
        assert cn2num("两") == 2

    def test_zero(self):
        assert cn2num("零") == 0

    def test_ten_alone(self):
        assert cn2num("十") == 10

    def test_teens(self):
        assert cn2num("十一") == 11
        assert cn2num("十四") == 14

    def test_tens(self):
        assert cn2num("二十") == 20
        assert cn2num("三十") == 30

    def test_tens_plus_unit(self):
        assert cn2num("三十七") == 37
        assert cn2num("四十一") == 41
        assert cn2num("二十三") == 23

    def test_positional_year(self):
        """位值连写(年份等无单位形式):一九九八 → 1998。"""
        assert cn2num("一九九八") == 1998

    def test_empty(self):
        assert cn2num("") is None

    def test_invalid_chars(self):
        assert cn2num("abc") is None
        assert cn2num("十一abc") is None


class TestNormalizeTimeHm:
    """时分表达 → 归一化 HH:MM 列表(slot-pattern)。"""

    def test_arabic_colon(self):
        assert normalize_time_hm("11:20") == ["11:20"]
        assert "23:20" in normalize_time_hm("23:20抵达")

    def test_arabic_in_text(self):
        assert "11:20" in normalize_time_hm("他11:20到达")

    def test_chinese_hm(self):
        assert "11:20" in normalize_time_hm("十一点二十")

    def test_chinese_hour_only(self):
        assert "10:00" in normalize_time_hm("十点")

    def test_arabic_dian(self):
        assert "10:00" in normalize_time_hm("10点")

    def test_arabic_dianfen(self):
        assert "11:20" in normalize_time_hm("11点20分")

    def test_morning_modifier_no_change(self):
        """上午/凌晨 不改变小时值。"""
        assert "10:00" in normalize_time_hm("上午十点")

    def test_afternoon_modifier_plus12(self):
        """下午/晚上/夜里 小时+12。"""
        assert "22:00" in normalize_time_hm("下午十点")

    def test_no_time(self):
        assert normalize_time_hm("无时间词") == []

    def test_empty(self):
        assert normalize_time_hm("") == []

    def test_multiple_times(self):
        result = normalize_time_hm("11:20 到 23:20")
        assert "11:20" in result and "23:20" in result


class TestNormalizeNumberUnit:
    """数字+单位 → 归一化数字串列表(按指定单位过滤)。"""

    def test_chinese_num_unit(self):
        assert "37" in normalize_number_unit("三十七页", "页")

    def test_arabic_num_unit(self):
        assert "37" in normalize_number_unit("37页", "页")
        assert "41" in normalize_number_unit("41分钟", "分钟")

    def test_multiple_in_text(self):
        result = normalize_number_unit("37页和41页", "页")
        assert "37" in result and "41" in result

    def test_wrong_unit_not_matched(self):
        """单位不符不命中(三十七张 ≠ 页)。"""
        assert normalize_number_unit("三十七张", "页") == []

    def test_no_match(self):
        assert normalize_number_unit("没有数字", "页") == []

    def test_empty(self):
        assert normalize_number_unit("", "页") == []

    def test_chinese_in_sentence(self):
        assert "37" in normalize_number_unit("翻到三十七页", "页")


# ---------------------------------------------------------------------------
# B1-T2 slot-pattern 集成进 check_atomic — P6-A2/B1
# 优先级: canonical/alias 子串 > slot value > mismatch_aliases > missing
# ---------------------------------------------------------------------------
class TestSlotInCheckAtomic:
    """anchor 声明 slot 后,正文用"不同形式同硬值"也能判 present。"""

    @pytest.fixture()
    def slot_anchors(self):
        return [
            {
                "id": "T1-H01", "type": "时间", "canonical": "十一点二十",
                "aliases": [],
                "slot": {"kind": "time_hm", "value": "11:20"},
            },
            {
                "id": "T2-H01", "type": "数字", "canonical": "三十七页",
                "aliases": [],
                "slot": {"kind": "number_unit", "value": "37", "unit": "页"},
            },
            # 无 slot 的锚(向后兼容)
            {
                "id": "T1-H03", "type": "地点", "canonical": "守拙斋",
                "aliases": [],
            },
        ]

    def test_slot_time_hit(self, slot_anchors):
        """正文用 11:20(canonical 非原形)→ slot 命中 present。"""
        text = "他11:20到达现场"
        results = check_atomic(slot_anchors, text)
        assert results[0]["status"] == "present"
        assert results[0]["hit"] is True
        assert "11:20" in results[0]["hit_by"]
        assert "slot" in results[0]["hit_by"]  # 标记来源

    def test_slot_number_hit(self, slot_anchors):
        """正文用 37页 → slot 命中 present。"""
        text = "翻到37页"
        results = check_atomic(slot_anchors, text)
        assert results[1]["status"] == "present"
        assert results[1]["hit"] is True

    def test_canonical_wins_over_slot(self, slot_anchors):
        """canonical 子串命中优先于 slot(原形在场 → hit_by=canonical)。"""
        text = "他十一点二十到达现场"
        results = check_atomic(slot_anchors, text)
        assert results[0]["status"] == "present"
        assert results[0]["hit_by"] == "十一点二十"

    def test_slot_miss_falls_to_missing(self, slot_anchors):
        """正文无该时间任何形式 → missing。"""
        text = "他在街上漫无目的地走"
        results = check_atomic(slot_anchors, text)
        assert results[0]["status"] == "missing"
        assert results[0]["hit"] is False

    def test_slot_wrong_value_miss(self):
        """正文时间值 ≠ slot.value → slot 不中(无 alias 兜底 → missing)。"""
        anchors = [{
            "id": "X", "type": "时间", "canonical": "十一点二十",
            "aliases": [],
            "slot": {"kind": "time_hm", "value": "11:20"},
        }]
        text = "他23:20到达"  # 23:20 ≠ slot 11:20
        results = check_atomic(anchors, text)
        assert results[0]["status"] == "missing"

    def test_slot_saves_from_mismatch(self):
        """slot 命中优先于 mismatch_aliases(硬信息确实在场 → present)。"""
        anchors = [{
            "id": "X", "type": "时间", "canonical": "十一点二十",
            "aliases": [],
            "slot": {"kind": "time_hm", "value": "11:20"},
            "mismatch_aliases": ["12:20"],
        }]
        text = "约了11:20见面,备忘录误写12:20"  # slot 11:20 中,mismatch 12:20 也在
        results = check_atomic(anchors, text)
        assert results[0]["status"] == "present"

    def test_slot_unhit_mismatch_fires(self):
        """slot 未中 + mismatch_aliases 在场 → value_mismatch。"""
        anchors = [{
            "id": "X", "type": "时间", "canonical": "十一点二十",
            "aliases": [],
            "slot": {"kind": "time_hm", "value": "11:20"},
            "mismatch_aliases": ["12:20"],
        }]
        text = "他12:20到达"  # slot 11:20 不中,mismatch 12:20 中
        results = check_atomic(anchors, text)
        assert results[0]["status"] == "value_mismatch"

    def test_no_slot_backward_compat(self, slot_anchors):
        """无 slot 字段的锚:行为逐字不变(向后兼容)。"""
        text = "他走进守拙斋"
        results = check_atomic(slot_anchors, text)
        assert results[2]["status"] == "present"
        assert results[2]["hit_by"] == "守拙斋"

    def test_slot_number_wrong_unit_miss(self):
        """number_unit:正文用错单位(三十七张 ≠ 页)→ slot 不中 → missing。"""
        anchors = [{
            "id": "X", "type": "数字", "canonical": "三十七页",
            "aliases": [],
            "slot": {"kind": "number_unit", "value": "37", "unit": "页"},
        }]
        text = "翻到三十七张"
        results = check_atomic(anchors, text)
        assert results[0]["status"] == "missing"


# ---------------------------------------------------------------------------
# P6-A2 收尾:distractor-replacement 夹具(B1 在真实章节文本上的表现)
# ---------------------------------------------------------------------------
class TestDistractorReplacementFixture:
    """P6-A2 收尾验证 — B1 slot-pattern 引擎在"纯 distractor 触发"场景的表现。

    夹具来源:`eval_set_v0/distractor_replacement/T1_distractor_replaced.md`
    由 `scripts/build_distractor_fixture.py` 把 T1_clean.md 的 5 个锚值替换产生。

    三组用例:
    - declared distractor(在 mismatch_aliases 中声明,3 条 T1-H05/H14/H16)
      → 期望 value_mismatch(B1 已支持,本测试作回归)。
    - undeclared slot distractor(同形不同值,未声明,2 条 T1-H10/H13)
      → 期望 missing(**B1 边界**:slot 是单向的,rescue present 不 auto-detect mismatch)。
    - clean 夹具:期望 value_mismatch=0(不误报)。
    """

    ANCHORS = Path("eval_set_v0/anchors.yaml")
    CLEAN = Path("eval_set_v0/baseline/T1_clean.md")
    REPLACED = Path("eval_set_v0/distractor_replacement/T1_distractor_replaced.md")

    @pytest.mark.skipif(
        not (ANCHORS.exists() and CLEAN.exists()),
        reason="eval_set_v0 不在 CWD(从仓库根跑)",
    )
    def test_clean_zero_value_mismatch(self):
        """clean 夹具:value_mismatch 应为 0(不误报)。"""
        report = run_check_text(
            str(self.ANCHORS), self.CLEAN.read_text(encoding="utf-8"), "T1"
        )
        assert report["stats"]["atomic"]["value_mismatch"] == 0

    @pytest.mark.skipif(
        not (ANCHORS.exists() and REPLACED.exists()),
        reason="eval_set_v0 / distractor 夹具不在 CWD",
    )
    def test_replaced_declared_distractors_all_value_mismatch(self):
        """declared distractor(3 条)在 replaced 夹具里应全中 value_mismatch。"""
        report = run_check_text(
            str(self.ANCHORS), self.REPLACED.read_text(encoding="utf-8"), "T1"
        )
        by_id = {r["id"]: r for r in report["atomic_results"]}
        for aid in ("T1-H05", "T1-H14", "T1-H16"):
            assert by_id[aid]["status"] == "value_mismatch", (
                f"{aid} 期望 value_mismatch, 实际 {by_id[aid]['status']}"
            )

    @pytest.mark.skipif(
        not (ANCHORS.exists() and REPLACED.exists()),
        reason="eval_set_v0 / distractor 夹具不在 CWD",
    )
    def test_replaced_opted_in_slot_now_mismatch(self):
        """B2 后:T1-H10/H13 在 anchors.yaml 已 opt-in,replaced 夹具应判 value_mismatch。

        B1 时这两锚在 replaced 夹具里落 missing(slot 单向,只 rescue present)。
        B2 + opt-in(mismatch_enabled=true)后,slot 模式抽到同形异值 → value_mismatch。
        本测试是 B1→B2 行为变化的回归锁定(避免回退)。
        """
        report = run_check_text(
            str(self.ANCHORS), self.REPLACED.read_text(encoding="utf-8"), "T1"
        )
        by_id = {r["id"]: r for r in report["atomic_results"]}
        for aid in ("T1-H10", "T1-H13"):
            assert by_id[aid]["status"] == "value_mismatch", (
                f"{aid} 期望 value_mismatch(B2 opt-in 后), "
                f"实际 {by_id[aid]['status']}"
            )
            assert by_id[aid]["mismatch_by"] is not None
            assert by_id[aid]["mismatch_by"].startswith("[slot-mismatch:")


# ---------------------------------------------------------------------------
# P6-A2/B2: slot form mismatch helper(同形异值 → value_mismatch,opt-in)
# ---------------------------------------------------------------------------
class TestSlotFormMismatchHelper:
    """B2-T1 · _check_slot_form_mismatch 单元测试(synthetic anchors)。

    helper 契约:
    - 输入:slot dict(canonical 旁声明的),已归一化文本(函数内 normalize 幂等)
    - 输出:mismatch 信号字符串(如 "[slot-mismatch:42|分钟]")或 None
    - 仅当 slot.mismatch_enabled=true 时启用;否则返回 None(B1 行为)
    - slot.value 在抽到的列表里 → None(slot-hit 走 present,不到这步)
    - slot.value 不在列表 & 列表非空 → 返回首个 ≠ value 的元素作信号
    - 列表空 → None(没抽到同形值,回到 missing)
    """

    def test_optin_time_hm_distractor_present_returns_mismatch_signal(self):
        """opt-in time_hm:text 有同形异值 → 返回 [slot-mismatch:HH:MM]。"""
        slot = {"kind": "time_hm", "value": "10:00", "mismatch_enabled": True}
        text = "明天上午十一点"  # 11:00 ≠ 10:00
        result = _check_slot_form_mismatch(slot, text)
        assert result is not None
        assert result.startswith("[slot-mismatch:")
        assert "11:00" in result

    def test_optin_number_unit_distractor_present_returns_mismatch_signal(self):
        """opt-in number_unit:text 有同单位异值 → 返回 [slot-mismatch:N|unit]。"""
        slot = {
            "kind": "number_unit", "value": "41", "unit": "分钟",
            "mismatch_enabled": True,
        }
        text = "录像覆盖了四十二分钟"  # 42 ≠ 41
        result = _check_slot_form_mismatch(slot, text)
        assert result is not None
        assert result.startswith("[slot-mismatch:")
        assert "42" in result
        assert "分钟" in result

    def test_optin_slot_no_form_value_in_text_returns_none(self):
        """opt-in slot:text 无任何 slot-form 值 → None(回到 missing)。"""
        slot = {"kind": "number_unit", "value": "41", "unit": "分钟",
                "mismatch_enabled": True}
        text = "他走进守拙斋,店堂里很暗"  # 无 X分钟
        assert _check_slot_form_mismatch(slot, text) is None

    def test_optin_slot_value_in_extracted_returns_none(self):
        """opt-in slot:slot.value 在抽到列表里 → None(slot-hit 走 present)。

        注:helper 本身不判 hit;调用方先调 _check_slot_match。
        helper 只负责 mismatch 信号;value 在列表里 → 不算 mismatch。
        """
        slot = {"kind": "number_unit", "value": "41", "unit": "分钟",
                "mismatch_enabled": True}
        text = "覆盖了四十一分钟"  # 41 在列表 → 不算 mismatch
        assert _check_slot_form_mismatch(slot, text) is None

    def test_no_mismatch_enabled_field_returns_none(self):
        """无 mismatch_enabled 字段 → None(B1 行为,默认 false)。"""
        slot = {"kind": "time_hm", "value": "10:00"}  # 无 mismatch_enabled
        text = "上午十一点"  # 即便有同形异值,也返回 None
        assert _check_slot_form_mismatch(slot, text) is None

    def test_mismatch_enabled_false_returns_none(self):
        """mismatch_enabled 显式 false → None。"""
        slot = {"kind": "time_hm", "value": "10:00", "mismatch_enabled": False}
        text = "上午十一点"
        assert _check_slot_form_mismatch(slot, text) is None

    def test_slot_missing_kind_returns_none(self):
        """slot 缺 kind → None(健壮)。"""
        slot = {"value": "10:00", "mismatch_enabled": True}
        assert _check_slot_form_mismatch(slot, "上午十点") is None

    def test_slot_missing_value_returns_none(self):
        """slot 缺 value → None(健壮)。"""
        slot = {"kind": "time_hm", "mismatch_enabled": True}
        assert _check_slot_form_mismatch(slot, "上午十点") is None

    def test_number_unit_missing_unit_returns_none(self):
        """number_unit 缺 unit → None(健壮,单位是必需字段)。"""
        slot = {"kind": "number_unit", "value": "41", "mismatch_enabled": True}
        assert _check_slot_form_mismatch(slot, "四十二分钟") is None

    def test_time_hm_first_different_value_used_as_signal(self):
        """time_hm:列表多个异值时,取首个 ≠ slot.value 的作信号。"""
        slot = {"kind": "time_hm", "value": "10:00", "mismatch_enabled": True}
        text = "下午三点四十分他到了"  # 抽到 15:40
        result = _check_slot_form_mismatch(slot, text)
        assert result is not None
        assert "15:40" in result


# ---------------------------------------------------------------------------
# P6-A2/B2: slot form mismatch 优先级(check_atomic 集成)
# ---------------------------------------------------------------------------
class TestSlotMismatchPriority:
    """B2-T2 · check_atomic 集成 slot form mismatch 后的优先级。

    最终优先级:
    1. canonical/alias 子串 → present
    2. slot.value 命中 → present(B1)
    3. slot form mismatch(仅 mismatch_enabled=true)→ value_mismatch(B2)
    4. mismatch_aliases → value_mismatch(现有)
    5. missing
    """

    def test_opted_in_slot_with_distractor_judged_value_mismatch(self):
        """opt-in slot + text 有同形异值,canonical/alias 不在 → value_mismatch。"""
        anchors = [{
            "id": "X", "type": "数字", "canonical": "四十一分钟",
            "aliases": [],
            "slot": {"kind": "number_unit", "value": "41", "unit": "分钟",
                     "mismatch_enabled": True},
        }]
        text = "覆盖了四十二分钟"
        results = check_atomic(anchors, text)
        assert results[0]["status"] == "value_mismatch"
        assert results[0]["mismatch_by"] is not None
        assert results[0]["mismatch_by"].startswith("[slot-mismatch:")

    def test_opted_in_slot_canonical_in_text_stays_present(self):
        """canonical 子串命中 → present(canonical 优先于 slot mismatch)。"""
        anchors = [{
            "id": "X", "type": "数字", "canonical": "四十一分钟",
            "aliases": [],
            "slot": {"kind": "number_unit", "value": "41", "unit": "分钟",
                     "mismatch_enabled": True},
        }]
        text = "覆盖了四十一分钟"  # canonical 命中
        results = check_atomic(anchors, text)
        assert results[0]["status"] == "present"
        assert results[0]["hit_by"] == "四十一分钟"

    def test_opted_in_slot_value_hit_stays_present(self):
        """slot.value 命中(slot hit)→ present(slot hit 优先于 mismatch)。"""
        anchors = [{
            "id": "X", "type": "时间", "canonical": "上午十点",
            "aliases": ["明天上午十点"],
            "slot": {"kind": "time_hm", "value": "10:00",
                     "mismatch_enabled": True},
        }]
        # canonical "上午十点" 在 text(slot hit 走 present)
        text = "明天上午十点碰头"
        results = check_atomic(anchors, text)
        assert results[0]["status"] == "present"

    def test_opted_in_slot_mismatch_takes_precedence_over_mismatch_aliases(self):
        """opt-in slot + mismatch_aliases 也在 text → slot mismatch 优先。

        优先级 3(slot form mismatch)在 4(mismatch_aliases)之前。
        mismatch_by 是 slot 信号(不是 distractor 名)。
        """
        anchors = [{
            "id": "X", "type": "数字", "canonical": "四十一分钟",
            "aliases": [],
            "mismatch_aliases": ["四十三分钟"],  # 不在 text(只构造场景)
            "slot": {"kind": "number_unit", "value": "41", "unit": "分钟",
                     "mismatch_enabled": True},
        }]
        text = "覆盖了四十二分钟"  # 42 ≠ 41,slot form mismatch 触发
        results = check_atomic(anchors, text)
        assert results[0]["status"] == "value_mismatch"
        # mismatch_by 是 slot 信号,不是 mismatch_aliases 的"四十三分钟"
        assert results[0]["mismatch_by"].startswith("[slot-mismatch:")
        assert "四十三分钟" not in (results[0]["mismatch_by"] or "")

    def test_not_opted_in_slot_distractor_in_text_falls_missing(self):
        """非 opt-in slot + distractor 在 text → missing(B1 行为不变)。"""
        anchors = [{
            "id": "X", "type": "数字", "canonical": "四十一分钟",
            "aliases": [],
            "slot": {"kind": "number_unit", "value": "41", "unit": "分钟"},
            # 无 mismatch_enabled(默认 false)
        }]
        text = "覆盖了四十二分钟"
        results = check_atomic(anchors, text)
        assert results[0]["status"] == "missing"

    def test_mismatch_aliases_still_work_when_no_slot(self):
        """无 slot 的锚 + mismatch_aliases → value_mismatch(回归不破)。"""
        anchors = [{
            "id": "X", "type": "设定", "canonical": "黑色手套",
            "aliases": [],
            "mismatch_aliases": ["白手套"],
        }]
        text = "戴着一只白手套"
        results = check_atomic(anchors, text)
        assert results[0]["status"] == "value_mismatch"
        assert results[0]["mismatch_by"] == "白手套"

    def test_mismatch_aliases_skipped_when_slot_mismatch_already_fired(self):
        """slot form mismatch 已触发 value_mismatch → mismatch_aliases 不再覆盖。

        避免信号被 mismatch_aliases 覆盖。guard 改 `if not hit and status != value_mismatch`。
        """
        anchors = [{
            "id": "X", "type": "数字", "canonical": "四十一分钟",
            "aliases": [],
            "mismatch_aliases": ["四十三分钟"],
            "slot": {"kind": "number_unit", "value": "41", "unit": "分钟",
                     "mismatch_enabled": True},
        }]
        # text 同时有 slot 异值(四十二)和 mismatch_aliases(四十三)
        text = "先覆盖四十二分钟,再覆盖四十三分钟"
        results = check_atomic(anchors, text)
        assert results[0]["status"] == "value_mismatch"
        # mismatch_by 是 slot 信号(优先),不是 mismatch_aliases 的"四十三分钟"
        assert results[0]["mismatch_by"].startswith("[slot-mismatch:")


# ---------------------------------------------------------------------------
# P6-A3: anchor 异名检测(未预声明的错名,相似但字面不一致)
# opt-in alias_check_enabled。override 语义:命中候选 → status=value_mismatch,
# 无论 canonical 是否在场。注册名集合 = 同章 atomic anchor 的 normalize(canonical+aliases)。
# ---------------------------------------------------------------------------
from biyu.anchor_check import _find_alias_similar  # noqa: E402


class TestAliasSimilarHelper:
    """A3 helper 单元:`_find_alias_similar` 的纯函数行为。

    契约:
    - 输入:canonical、registered_names(set[normalized])、norm_text、max_distance=2
    - 在 norm_text 中扫"首字=canonical[0]、长度=canonical、距离≤max_distance、
      非自身、非已登记"的候选,返回首个命中或 None。
    - 单字 canonical(L<2)→ None(易误报,不检)。
    """

    def test_distance_2_two_substitutions_returns_candidate(self):
        """陈云曦 vs 陈雪艷(2 处替换,距离=2)→ 返回候选。ch1.md 验证例的核心。"""
        registered = {"陈云曦"}
        text = "说话的是陈雪艷。"
        result = _find_alias_similar("陈云曦", registered, text)
        assert result == "陈雪艷"

    def test_distance_1_one_substitution_returns_candidate(self):
        """陈云曦 vs 陈云熙(1 处替换)→ 返回候选。"""
        registered = {"陈云曦"}
        text = "陈云熙走了过来"
        result = _find_alias_similar("陈云曦", registered, text)
        assert result == "陈云熙"

    def test_distance_3_not_triggered(self):
        """距离=3(>max_distance=2)→ None。

        4 字 canonical 司马相如 vs 司空不同:首字同,其余 3 位全异 → Hamming=3。
        """
        registered = {"司马相如"}
        text = "司空不同也在"
        assert _find_alias_similar("司马相如", registered, text) is None

    def test_canonical_self_in_text_not_flagged(self):
        """canonical 本身在 text 中 → 不算异名(candidate == canonical 跳过)。"""
        registered = {"陈云曦"}
        text = "陈云曦和方平一起"
        assert _find_alias_similar("陈云曦", registered, text) is None

    def test_alias_of_this_anchor_excluded(self):
        """本锚 alias 在 text 中 → 已登记,不报。"""
        registered = {"陈云曦", "小曦"}  # 小曦 是 alias
        text = "小曦走过"
        assert _find_alias_similar("陈云曦", registered, text) is None

    def test_other_anchor_canonical_excluded(self):
        """同册另一 anchor 的 canonical(陈云瑶)在 text 中 → 已登记,不报。

        验收:两个真不同角色、名字恰好相近 → 不互相误报。
        """
        registered = {"陈云曦", "陈云瑶"}  # 陈云瑶 是另一 anchor 的 canonical
        text = "陈云瑶到了"
        assert _find_alias_similar("陈云曦", registered, text) is None

    def test_different_first_char_no_candidate(self):
        """首字不同的字符串 → 无候选(canonical[0] 锚定挡住)。

        验收:字面差异大 → 不触发。
        """
        registered = {"方平"}
        text = "魔都武大的队长是韩旭"  # 无 方 字
        assert _find_alias_similar("方平", registered, text) is None

    def test_first_char_anchored_skips_distant_4char_ngram(self):
        """首字锚定 + 字数相同 + 距离 > max_distance → 不报。

        4 字 canonical 司马相如 vs 司空不同:首字同,其余 3 位全异 → 距离 3。
        (3 字名 + 同姓 + max_distance=2 时,任何同姓 3-gram 都满足距离 ≤ 2,
        无法用此构造距离 > 2 的反例 —— 见 test_known_limitation_3char_*)
        """
        registered = {"司马相如"}
        text = "司空不同也在场"
        assert _find_alias_similar("司马相如", registered, text) is None

    def test_known_limitation_3char_same_surname_ngram_also_matches(self):
        """已知局限(锁定行为,供未来 review):3 字名 + 同姓 + max_distance=2
        时,"姓+任意两字"的 3-gram 都满足距离 ≤ 2 → 会匹配,即使候选不是真名。

        陈列台 vs 陈云曦 距离 = 2(陈同,列/云、台/曦 各 1 替换)→ 返回候选。
        这是参数选择(阈值 ≥ 2,由 ch1.md 陈雪艷~陈云曦 验收例反推)的必然结果。
        误报由"提请人工确认"语义兜底(报告标疑似,不自动改名)。
        生产建议:3 字以下姓名慎开 alias_check_enabled,或搭配人工 triage。
        """
        registered = {"陈云曦"}
        text = "陈列台上"
        # 锁定实际行为(非 bug,是已知局限):会返回 陈列台
        assert _find_alias_similar("陈云曦", registered, text) == "陈列台"

    def test_single_char_canonical_returns_none(self):
        """单字 canonical(L<2)→ None(易误报,不检)。"""
        registered = {"方"}
        assert _find_alias_similar("方", registered, "方圆十里") is None

    def test_returns_first_match_when_multiple(self):
        """文本中多候选时返回首个(顺序按 norm_text 中 first 字位置)。"""
        registered = {"陈云曦"}
        text = "先是陈云熙,然后陈雪艷"
        result = _find_alias_similar("陈云曦", registered, text)
        # 两个都是合法候选(距离分别 1、2);返回首个出现的(陈云熙)
        assert result in {"陈云熙", "陈雪艷"}
        assert result == "陈云熙"  # text 中 陈云熙 先出现

    def test_max_distance_param_respected(self):
        """max_distance 参数生效:传 1 时,距离=2 的候选不报。"""
        registered = {"陈云曦"}
        text = "陈雪艷到了"  # 距离=2
        assert _find_alias_similar("陈云曦", registered, text, max_distance=1) is None


class TestAliasSimilarPriority:
    """A3 集成 · check_atomic override 优先级。

    最终优先级:
    1. canonical/alias 子串 → present
    2. slot.value → present
    3. slot form mismatch(opt-in)→ value_mismatch
    4. mismatch_aliases → value_mismatch
    5. missing
    6. **alias-similar override(仅 alias_check_enabled=true):扫到候选
       → status=value_mismatch、mismatch_by=[alias-similar:X~canonical]**

    override 语义:无论前 5 步得 present 还是 missing,只要 alias_check_enabled=true
    且扫到候选 → 强制 value_mismatch。
    """

    def _heroine_anchor(self, **extra):
        anchor = {
            "id": "heroine_chen", "type": "person", "canonical": "陈云曦",
            "alias_check_enabled": True,
        }
        anchor.update(extra)
        return anchor

    def test_canonical_present_no_variant_stays_present(self):
        """canonical 在场 + 无异名候选 → present(clean 不误报)。"""
        anchors = [self._heroine_anchor()]
        text = "陈云曦走过来"
        results = check_atomic(anchors, text)
        assert results[0]["status"] == "present"
        assert results[0]["mismatch_by"] is None

    def test_canonical_present_variant_also_present_overrides_to_mismatch(self):
        """canonical + 异名同章 → override 为 value_mismatch(ch1.md 场景)。

        陈云曦(line 509+ 主流)与 陈雪艷(line 145 孤例)并存 → 报异名。
        override 同时把 hit 降为 False(守护不变量 hit=True ↔ status=present);
        canonical 在场的诊断信息保留在 mismatch_by 字符串里(含 ~陈云曦)。
        """
        anchors = [self._heroine_anchor()]
        text = "说话的是陈雪艷。后来方平睁开眼,看到陈云曦。"
        results = check_atomic(anchors, text)
        assert results[0]["status"] == "value_mismatch"
        assert results[0]["hit"] is False  # 不变量守护
        assert results[0]["hit_by"] is None
        assert results[0]["mismatch_by"] is not None
        assert results[0]["mismatch_by"].startswith("[alias-similar:")
        assert "陈雪艷" in results[0]["mismatch_by"]
        assert "陈云曦" in results[0]["mismatch_by"]

    def test_canonical_absent_variant_present_value_mismatch(self):
        """canonical 不在场 + 异名在场 → value_mismatch。"""
        anchors = [self._heroine_anchor()]
        text = "说话的是陈雪艷"  # 无 陈云曦
        results = check_atomic(anchors, text)
        assert results[0]["status"] == "value_mismatch"
        assert results[0]["mismatch_by"].startswith("[alias-similar:")

    def test_canonical_absent_no_variant_missing(self):
        """canonical 不在场 + 无候选 → missing。"""
        anchors = [self._heroine_anchor()]
        text = "方平在街上走"  # 无 陈X曦 类候选
        results = check_atomic(anchors, text)
        assert results[0]["status"] == "missing"
        assert results[0]["mismatch_by"] is None

    def test_alias_check_disabled_no_override(self):
        """alias_check_enabled=false + 异名在场 → 不触发 override(零回归)。

        无 alias_check_enabled 字段的锚行为一致(B1 既有链)。
        """
        anchors = [{
            "id": "heroine_chen", "type": "person", "canonical": "陈云曦",
            # 无 alias_check_enabled
        }]
        text = "陈雪艷走过来"  # 异名在场,canonical 不在场
        results = check_atomic(anchors, text)
        # 无 override → 既不是 canonical 也不是 mismatch_aliases → missing
        assert results[0]["status"] == "missing"
        assert results[0]["mismatch_by"] is None

    def test_alias_check_explicit_false_no_override(self):
        """alias_check_enabled 显式 false → 同无字段(B1 行为)。"""
        anchors = [{
            "id": "heroine_chen", "type": "person", "canonical": "陈云曦",
            "alias_check_enabled": False,
        }]
        text = "陈雪艷走过来"
        results = check_atomic(anchors, text)
        assert results[0]["status"] == "missing"

    def test_two_registered_similar_chars_no_false_positive(self):
        """两真不同角色名相近、都登记、都 opt-in → 互不误报(验收硬线)。

        陈云曦(anchor A)与 陈云瑶(anchor B)距离=1;两者都在 text 中;
        注册名集合含两者 → 互相排除 → 都判 present。
        """
        anchors = [
            {"id": "heroine_a", "type": "person", "canonical": "陈云曦",
             "alias_check_enabled": True},
            {"id": "heroine_b", "type": "person", "canonical": "陈云瑶",
             "alias_check_enabled": True},
        ]
        text = "陈云曦和陈云瑶一起到了"
        results = check_atomic(anchors, text)
        by_id = {r["id"]: r for r in results}
        assert by_id["heroine_a"]["status"] == "present"
        assert by_id["heroine_b"]["status"] == "present"

    def test_signal_format_includes_candidate_and_canonical(self):
        """信号格式:[alias-similar:<候选>~<canonical>]。"""
        anchors = [self._heroine_anchor()]
        text = "陈雪艷到了"
        results = check_atomic(anchors, text)
        assert results[0]["mismatch_by"] == "[alias-similar:陈雪艷~陈云曦]"

    def test_existing_anchors_without_optin_zero_regression(self):
        """无 alias_check_enabled 的存量锚,行为逐字不变(零回归)。"""
        anchors = [
            {"id": "T1-H01", "type": "时间", "canonical": "十一点二十",
             "aliases": ["23:20"]},
            {"id": "T1-H09", "type": "数字", "canonical": "A-113",
             "aliases": ["A113"], "mismatch_aliases": ["A-131"]},
        ]
        text = "他23:20到了,案卷编号A-131"
        results = check_atomic(anchors, text)
        # H01: alias 23:20 命中 → present
        assert results[0]["status"] == "present"
        # H09: canonical A-113 不在,mismatch_aliases A-131 在 → value_mismatch
        assert results[1]["status"] == "value_mismatch"
        assert results[1]["mismatch_by"] == "A-131"

    def test_other_anchor_canonical_excluded_via_registered_set(self):
        """同章另一未 opt-in 锚的 canonical 也参与排除集(防互撞)。"""
        anchors = [
            {"id": "heroine", "type": "person", "canonical": "陈云曦",
             "alias_check_enabled": True},
            {"id": "other", "type": "person", "canonical": "陈云瑶"},
            # 陈云瑶 是另一角色,未 opt-in,但仍在注册名集合里
        ]
        text = "陈云曦和陈云瑶一起"
        results = check_atomic(anchors, text)
        by_id = {r["id"]: r for r in results}
        # heroine: canonical 陈云曦 在场;陈云瑶 在排除集 → 无候选 → present
        assert by_id["heroine"]["status"] == "present"

    def test_variant_in_mismatch_aliases_not_double_counted(self):
        """异名候选恰好也在 mismatch_aliases 里 → override 仍以 alias-similar 标。

        两机制独立,override 在后,mismatch_by 取 override 信号。
        """
        anchors = [{
            "id": "x", "type": "person", "canonical": "陈云曦",
            "mismatch_aliases": ["陈云熙"],  # 显式声明的错值
            "alias_check_enabled": True,
        }]
        text = "陈云熙走过来"  # 陈云熙 既在 mismatch_aliases 又是异名候选
        results = check_atomic(anchors, text)
        assert results[0]["status"] == "value_mismatch"
        # mismatch_by 是 alias-similar 信号(override 在后,覆盖 mismatch_aliases 信号)
        assert results[0]["mismatch_by"].startswith("[alias-similar:")
