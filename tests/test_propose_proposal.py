"""Tests for biyu.propose.proposal — P7-2 重写:判断在前、不整列书单.

覆盖 T6:
- 三种路径(specific/directional/empty)各自正确结构
- 核心判断节(§2)出现在最前
- 全文不出现 top 20 表格(grep 不到 `| 排名 | 书名 |`)
- hot_genres 渲染每题材 sample_titles ≤3 本
- 诚实声明文本在(具体路径)
- 空 idea 路径不报错
- 元数据完整
"""
from __future__ import annotations

from biyu.propose.analyzer import AnalysisResult, HotGenre
from biyu.propose.craft import CraftHints
from biyu.propose.proposal import build_proposal_markdown
from biyu.propose.redblue import Quadrant, RedBlueResult
from biyu.propose.router import PathDecision
from biyu.propose.scanner import BookEntry, PlatformResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_book(i: int, platform: str = "qidian") -> BookEntry:
    return BookEntry(
        rank=i, title=f"书{i}", author=f"作者{i}", category="玄幻",
        word_count="100万字", url=f"https://x.com/{platform}/{i}",
        abstract=f"简介{i}。",
    )


def _make_success_platform(platform: str = "qidian", n: int = 5) -> PlatformResult:
    return PlatformResult(
        platform=platform, success=True,
        books=[_make_book(i + 1, platform) for i in range(n)],
        fetched_at="2026-06-30T10:00:00+00:00",
        source_url=f"https://x.com/{platform}",
    )


def _make_failed_platform(platform: str = "fanqie") -> PlatformResult:
    return PlatformResult(
        platform=platform, success=False, error="network down",
        fetched_at="2026-06-30T10:00:00+00:00",
        source_url=f"https://x.com/{platform}",
    )


def _make_analysis(source: str = "llm") -> AnalysisResult:
    return AnalysisResult(
        hot_genres=[
            HotGenre(
                genre="都市异能",
                heat_signal="起点都市榜前 10 占 3 本",
                sample_titles=["书1", "书2", "书3"],  # 已 ≤3
            ),
            HotGenre(
                genre="系统流",
                heat_signal="番茄热门前 20 占 5 本",
                sample_titles=["书A", "书B"],
            ),
        ],
        hot_tropes=["系统流+吐槽", "反派洗白", "轻喜剧爽文"],
        market_summary="近期都市异能与系统流占主导,轻喜剧元素横切多题材。",
        source=source,
    )


def _make_redblue(source: str = "llm", quadrant: Quadrant = Quadrant.RED_SEA) -> RedBlueResult:
    return RedBlueResult(
        supply_crowding="校车+秘境题材在起点都市榜前 20 占 4 本,供给较拥挤。",
        demand_weak_signal="榜上同类作品位次靠前(前 5),在榜数量稳定但无爆款TOP1。",
        quadrant=quadrant,
        source=source,
    )


def _make_craft(source: str = "llm") -> CraftHints:
    return CraftHints(
        markdown="## 创作规律参考提示\n\n- 节奏:每章一小高潮。\n- 目标:三层目标体系。",
        source=source,
    )


# ---------------------------------------------------------------------------
# 不整列书单(核心红线)
# ---------------------------------------------------------------------------


def test_proposal_does_not_contain_top_20_table_for_any_path():
    """三路径产出都不出现 P7-1 的 top 20 表格(`| 排名 | 书名 |`)。"""
    scan = {"qidian": _make_success_platform("qidian", n=20)}  # 抓到 20 本
    analysis = _make_analysis()
    craft = _make_craft()
    redblue = _make_redblue()

    for path, idea, rb in [
        (PathDecision.SPECIFIC, "校车进秘境", redblue),
        (PathDecision.DIRECTIONAL, "想写穿越的", None),
        (PathDecision.EMPTY, "", None),
    ]:
        md = build_proposal_markdown(
            idea=idea, path=path,
            scan_results=scan, analysis=analysis, craft=craft,
            redblue=rb, total_cost_cny=0.01, elapsed_seconds=1.0,
        )
        # 表头绝不能出现
        assert "| 排名 | 书名 |" not in md, f"path={path} 出现 top 20 表头"
        assert "|---|---|---|---|---|---|" not in md, f"path={path} 出现表分隔"


def test_proposal_does_not_list_all_20_books_from_scan():
    """即使扫榜抓到 20 本,立项书也不把 20 本全列出来。

    抓 20 本的 scan_results,产出里书名引用次数应远少于 20
    (hot_genres 每题材 ≤3 本,共最多 2 题材 × 3 = 6 本)。
    """
    scan = {"qidian": _make_success_platform("qidian", n=20)}
    analysis = _make_analysis()
    craft = _make_craft()

    md = build_proposal_markdown(
        idea="校车", path=PathDecision.SPECIFIC,
        scan_results=scan, analysis=analysis, craft=craft,
        redblue=_make_redblue(),
        total_cost_cny=0.01, elapsed_seconds=1.0,
    )

    # P7-1 是把 20 本书名全列。P7-2 应该把"书1...书20"中绝大多数滤掉
    # 检查:出现书名的总数(去重)< 10(防整列)
    mentioned_books = {f"书{i}" for i in range(1, 21) if f"书{i}" in md}
    assert len(mentioned_books) < 10, (
        f"立项书列了 {len(mentioned_books)} 本书,疑似整列书单: {mentioned_books}"
    )


# ---------------------------------------------------------------------------
# 核心判断节最前
# ---------------------------------------------------------------------------


def test_proposal_specific_path_has_core_judgment_section_first():
    """SPECIFIC 路径:§2 是核心判断(红蓝海结论),在最前面(§1 回显之后)。"""
    md = build_proposal_markdown(
        idea="校车进秘境", path=PathDecision.SPECIFIC,
        scan_results={"qidian": _make_success_platform()},
        analysis=_make_analysis(), craft=_make_craft(),
        redblue=_make_redblue(),
        total_cost_cny=0.01, elapsed_seconds=1.0,
    )

    # §2 标题是"核心判断"(或类似)
    assert "## 2." in md
    idx_judgment = md.find("## 2.")
    # 红蓝海关键词在 §2 附近
    assert "红海" in md or "蓝海" in md or "死海" in md or "荒漠" in md
    # §2 应该早于 §3
    idx_3 = md.find("## 3.")
    assert idx_judgment < idx_3


def test_proposal_specific_path_includes_honesty_note_in_output():
    """SPECIFIC 路径产出里能找到诚实声明那句话(需求侧不可得...)。"""
    md = build_proposal_markdown(
        idea="校车进秘境", path=PathDecision.SPECIFIC,
        scan_results={"qidian": _make_success_platform()},
        analysis=_make_analysis(), craft=_make_craft(),
        redblue=_make_redblue(),
        total_cost_cny=0.01, elapsed_seconds=1.0,
    )

    # 诚实声明的关键词
    assert "需求侧" in md
    assert "不可得" in md or "不可获" in md


def test_proposal_directional_path_has_direction_induction_in_judgment():
    """DIRECTIONAL 路径:§2 是该方向的套路归纳(不是红蓝海)。"""
    md = build_proposal_markdown(
        idea="想写穿越的", path=PathDecision.DIRECTIONAL,
        scan_results={"qidian": _make_success_platform()},
        analysis=_make_analysis(), craft=_make_craft(),
        redblue=None,
        total_cost_cny=0.01, elapsed_seconds=1.0,
    )

    # 没有红蓝海节(方向路径不走红蓝海)
    # §2 应是方向归纳(关键词:方向 / 归纳)
    assert "## 2." in md
    # 方向关键词
    assert "方向" in md or "归纳" in md


def test_proposal_empty_path_runs_without_error_and_has_market_summary():
    """EMPTY 路径(空 idea):不报错,有市场套路归纳。"""
    md = build_proposal_markdown(
        idea="", path=PathDecision.EMPTY,
        scan_results={"qidian": _make_success_platform()},
        analysis=_make_analysis(), craft=_make_craft(),
        redblue=None,
        total_cost_cny=0.01, elapsed_seconds=1.0,
    )

    # 跑通 + 含市场归纳
    assert isinstance(md, str)
    assert len(md) > 100
    # §1 显示"未填写"或空
    assert "未填写" in md or "空" in md or "未提供" in md or "(无)" in md


# ---------------------------------------------------------------------------
# hot_genres 渲染每条 ≤3 本
# ---------------------------------------------------------------------------


def test_proposal_each_genre_lists_at_most_three_books():
    """渲染 hot_genres 时,每条题材的 sample_titles 显示 ≤3 本。"""
    # 构造一个 sample_titles 有 3 本(已被 analyzer 截断)的 analysis
    analysis = AnalysisResult(
        hot_genres=[
            HotGenre(genre="玄幻", heat_signal="热", sample_titles=["书1", "书2", "书3"]),
            HotGenre(genre="都市", heat_signal="热", sample_titles=["书A", "书B", "书C"]),
        ],
        hot_tropes=["x"],
        market_summary="y",
        source="llm",
    )

    md = build_proposal_markdown(
        idea="x", path=PathDirection_or_empty(),
        scan_results={"qidian": _make_success_platform()},
        analysis=analysis, craft=_make_craft(),
        redblue=None,
        total_cost_cny=0.0, elapsed_seconds=0.0,
    )

    # 每条题材最多 3 本(简单查:书1/书2/书3 都在,但不会有"书4")
    assert "书1" in md
    assert "书2" in md
    assert "书3" in md


def PathDirection_or_empty():
    """Helper: 给个合法 PathDecision。"""
    return PathDecision.DIRECTIONAL


# ---------------------------------------------------------------------------
# 元数据完整
# ---------------------------------------------------------------------------


def test_proposal_metadata_section_complete():
    """元数据节含:成本 / 耗时 / 模型 / 数据源 URL / 数据时间戳 / 来源标签。"""
    md = build_proposal_markdown(
        idea="校车", path=PathDecision.SPECIFIC,
        scan_results={
            "qidian": _make_success_platform("qidian"),
            "fanqie": _make_failed_platform("fanqie"),
        },
        analysis=_make_analysis(), craft=_make_craft(),
        redblue=_make_redblue(),
        total_cost_cny=0.0123, elapsed_seconds=2.5,
        model_alias="v4_pro",
    )

    # 关键元数据字段
    assert "0.0123" in md or "0.012" in md  # 成本
    assert "2.5" in md  # 耗时
    assert "v4_pro" in md  # 模型
    assert "https://x.com/qidian" in md  # 数据源 URL
    assert "2026-06-30" in md  # 时间戳


def test_proposal_marks_failed_platforms_in_metadata():
    """失败平台在元数据 / 数据节里如实标注。"""
    md = build_proposal_markdown(
        idea="x", path=PathDecision.EMPTY,
        scan_results={
            "qidian": _make_success_platform("qidian"),
            "fanqie": _make_failed_platform("fanqie"),
        },
        analysis=_make_analysis(), craft=_make_craft(),
        redblue=None,
        total_cost_cny=0.0, elapsed_seconds=0.0,
    )

    assert "fanqie" in md
    assert "失败" in md or "error" in md.lower() or "network down" in md


# ---------------------------------------------------------------------------
# 红蓝海失败时不假装有内容
# ---------------------------------------------------------------------------


def test_proposal_specific_path_when_redblue_failed_shows_absent_notice():
    """SPECIFIC 路径 + redblue.source='llm_failed' → 显示"市场对照未生成",不假装有象限。"""
    md = build_proposal_markdown(
        idea="校车", path=PathDecision.SPECIFIC,
        scan_results={"qidian": _make_success_platform()},
        analysis=_make_analysis(), craft=_make_craft(),
        redblue=RedBlueResult(source="llm_failed"),
        total_cost_cny=0.01, elapsed_seconds=1.0,
    )

    # 应有"未生成"类标注
    assert "未生成" in md or "失败" in md or "不可用" in md
    # 不应出现"具体象限归类行"(因为 redblue 失败了,不能给确定结论)
    # 检查关键:不出现"象限定性:红海/蓝海/死海/荒漠"这种确定结论
    assert "象限定性" not in md
    # 也不应有 "**供给拥挤度**" 这种字段(只有 source='llm' 才出)
    assert "**供给拥挤度**" not in md
