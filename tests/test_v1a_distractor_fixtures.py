"""V1a: 验证 eval_set_v0/anchors.yaml 的 distractor 夹具端到端可用。

背景(D-56): V0 证明了 presence 维端到端有效, 但 value_mismatch 维因夹具
0/37 锚含 distractor 而一次未触发。V1a 给若干硬信息锚补 distractor 变体,
本测试用合成正文验证 checker 能抓到。

覆盖(可 string 判):
- 档案号: T1-H16, T3-H05 (A-113 → A-131 / A-311)
- 钥匙编号: T1-H09 (07号黄铜钥匙 → 08号黄铜钥匙 / 17号黄铜钥匙)
- 地点楼层: T1-H14, T3-H02 (市档案馆三楼 → 档案馆二楼 / 档案馆四楼)
- 物品颜色: T1-H05 (黑色手套 → 白手套 / 灰手套)

未覆盖(报 TL):
- 纯时间类(T1-H01 十一点二十 等)— 用户 stop-and-ask 项, 不自造规则
- 刻字 — 无现存锚
- 电话 — 无现存锚
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from biyu.anchor_check import run_check_text

EVAL_DIR = Path(__file__).resolve().parent.parent / "eval_set_v0"
ANCHORS_YAML = EVAL_DIR / "anchors.yaml"


@pytest.fixture(scope="module")
def real_anchors() -> dict:
    return yaml.safe_load(ANCHORS_YAML.read_text(encoding="utf-8"))


def _get(real_anchors: dict, chapter: str, anchor_id: str) -> dict:
    for a in real_anchors[chapter]["atomic"]:
        if a["id"] == anchor_id:
            return a
    raise KeyError(f"{chapter}/{anchor_id} not found")


def _result_for(report: dict, anchor_id: str) -> dict:
    for r in report["atomic_results"]:
        if r["id"] == anchor_id:
            return r
    raise KeyError(anchor_id)


# ---------------------------------------------------------------------------
# 夹具存在性 — anchors.yaml 已补 mismatch_aliases
# ---------------------------------------------------------------------------
class TestFixtureHasDistractors:
    """验证 anchors.yaml 已为选定硬信息锚补 mismatch_aliases(D-56 修补)。"""

    @pytest.mark.parametrize("chapter,aid", [
        ("T1", "T1-H16"),  # A-113
        ("T3", "T3-H05"),  # A-113 跨章
        ("T1", "T1-H09"),  # 07号黄铜钥匙
        ("T1", "T1-H14"),  # 市档案馆三楼
        ("T3", "T3-H02"),  # 市档案馆三楼 跨章
        ("T1", "T1-H05"),  # 黑色手套
    ])
    def test_anchor_has_mismatch_aliases(self, real_anchors, chapter, aid):
        a = _get(real_anchors, chapter, aid)
        assert "mismatch_aliases" in a, f"{aid} 应补 mismatch_aliases"
        assert isinstance(a["mismatch_aliases"], list) and len(a["mismatch_aliases"]) >= 1, (
            f"{aid} mismatch_aliases 至少 1 条"
        )


# ---------------------------------------------------------------------------
# 合成正文 → checker 抓中(每个 distractor 至少 1 个用例)
# ---------------------------------------------------------------------------
class TestDistractorCaught:
    """正文含 distractor 且不含 canonical/alias → status=value_mismatch。"""

    @pytest.mark.parametrize("chapter,aid,distractor,text_template", [
        # 档案号 A-113
        ("T1", "T1-H16", "A-131", "他翻到案卷编号{d}的那一页"),
        ("T1", "T1-H16", "A-311", "档案袋上印着{d}"),
        ("T3", "T3-H05", "A-131", "案卷编号{d}被抽出"),
        # 钥匙编号
        ("T1", "T1-H09", "08号黄铜钥匙", "他摸到了{d}"),
        ("T1", "T1-H09", "17号黄铜钥匙", "抽屉里有一把{d}"),
        # 地点楼层
        ("T1", "T1-H14", "档案馆二楼", "他上了市{d}"),
        ("T1", "T1-H14", "档案馆四楼", "电梯停在{d}"),
        ("T3", "T3-H02", "档案馆二楼", "走到{d}拐角"),
        # 物品颜色
        ("T1", "T1-H05", "白手套", "聂守仁戴着{d}"),
        ("T1", "T1-H05", "灰手套", "他注意到那双{d}"),
    ])
    def test_distractor_caught(self, chapter, aid, distractor, text_template):
        text = text_template.format(d=distractor)
        report = run_check_text(str(ANCHORS_YAML), text, chapter)
        r = _result_for(report, aid)
        assert r["status"] == "value_mismatch", (
            f"{aid}: 期望 value_mismatch 抓中 distractor={distractor}, "
            f"实际 status={r['status']}, hit_by={r.get('hit_by')}, mismatch_by={r.get('mismatch_by')}"
        )
        assert r["mismatch_by"] == distractor


# ---------------------------------------------------------------------------
# 控制变量: 不误判
# ---------------------------------------------------------------------------
class TestNoFalsePositives:
    def test_neither_canonical_nor_distractor_is_missing(self):
        """正文既无 canonical/alias 也无 distractor → missing(绝不报 value_mismatch)。"""
        report = run_check_text(str(ANCHORS_YAML), "他在街上漫无目的地走", "T1")
        for aid in ["T1-H16", "T1-H09", "T1-H14", "T1-H05"]:
            r = _result_for(report, aid)
            assert r["status"] == "missing", f"{aid}: 期望 missing, 实际 {r['status']}"
            assert r["mismatch_by"] is None

    @pytest.mark.parametrize("chapter,aid,canonical", [
        ("T1", "T1-H16", "A-113"),
        ("T1", "T1-H09", "07号黄铜钥匙"),
        ("T1", "T1-H14", "市档案馆三楼"),
        ("T1", "T1-H05", "黑色手套"),
    ])
    def test_canonical_wins_over_distractor(self, chapter, aid, canonical):
        """canonical 与 distractor 并存 → status=present(canonical 优先级最高)。"""
        # 用 A-113 + A-131 共现为例(每个锚各构造一次)
        distractor_for = {
            "T1-H16": "A-131",
            "T1-H09": "08号黄铜钥匙",
            "T1-H14": "档案馆二楼",
            "T1-H05": "白手套",
        }
        text = f"正卷是{canonical},旁边草稿误写成{distractor_for[aid]}"
        report = run_check_text(str(ANCHORS_YAML), text, chapter)
        r = _result_for(report, aid)
        assert r["status"] == "present", f"{aid}: 期望 present(canonical优先), 实际 {r['status']}"
        assert r["hit"] is True
        assert r["mismatch_by"] is None


# ---------------------------------------------------------------------------
# 基线回归: 已生成的 baseline/post_injection 不应被新 distractor 误伤
# ---------------------------------------------------------------------------
class TestBaselineRegressiveSafe:
    """新补的 distractor 不会让既有 baseline/post_injection 章节冒出假 value_mismatch。

    原因: baseline 与 post_injection 的正文里这些 distractor 字符串本就不存在
    (LLM 没写过 A-131 / 档案馆二楼 / 白手套 等)。
    """

    @pytest.mark.parametrize("cond_dir", ["baseline", "post_injection"])
    @pytest.mark.parametrize("tkey", ["T1", "T2", "T3"])
    def test_no_new_value_mismatch_in_existing_chapters(self, cond_dir, tkey):
        path = EVAL_DIR / cond_dir / f"{tkey}_clean.md"
        if not path.exists():
            pytest.skip(f"{path} 不存在")
        text = path.read_text(encoding="utf-8")
        report = run_check_text(str(ANCHORS_YAML), text, tkey)
        vm = report["stats"]["atomic"]["value_mismatch"]
        # V0 baseline 是 0; 加 distractor 后仍应保持 0(无假阳性)
        assert vm == 0, (
            f"{cond_dir}/{tkey}: 加 distractor 后冒出 {vm} 个 value_mismatch — "
            "说明 distractor 选词不当(与正文里某个无关词重了)"
        )
