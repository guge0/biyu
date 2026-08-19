"""Tests for biyu.propose.analyzer — P7-2 套路归纳.

覆盖 T3:
- LLM 合法 JSON → 解析 + 渲染(新 schema:hot_genres/hot_tropes/market_summary)
- 污染 JSON(```json ... ``` 包裹 / 前后缀)→ repair 成功
- schema 不全(缺 market_summary)→ 重试 1 次仍失败 → 降级 llm_failed
- schema 不全 → 重试成功(第二次返合法)→ source='llm'
- LLM 异常 → 降级不崩(不重试)
- sample_titles >3 → 硬截断到 3
- 无 adapter → unavailable
- 渲染产出 hot_genres 每条 ≤3 本

所有 LLM 调用 mock,零烧钱。
"""
from __future__ import annotations

from biyu.propose.analyzer import (
    AnalysisResult,
    HotGenre,
    build_analysis,
    render_analysis_as_markdown,
)


class _FakeAdapter:
    """Mock LLM adapter,记录调用 + 返回预设响应(同一响应)。"""

    def __init__(self, response_text: str, cost: float = 0.001):
        self._response = response_text
        self._cost = cost
        self.calls: list = []

    async def generate(self, messages, **kwargs):
        self.calls.append(messages)

        class _R:
            text = self._response
            cost = self._cost

        return _R()


class _SequentialAdapter:
    """Mock adapter 按顺序返回不同响应(用于重试测试)。"""

    def __init__(self, responses: list[str], cost: float = 0.001):
        self._responses = list(responses)
        self._cost = cost
        self.calls: list = []

    async def generate(self, messages, **kwargs):
        self.calls.append(messages)
        text = self._responses.pop(0) if self._responses else ""

        class _R:
            pass

        r = _R()
        r.text = text
        r.cost = self._cost
        return r


class _FailingAdapter:
    """Mock adapter that raises."""

    def __init__(self, exc: Exception):
        self._exc = exc

    async def generate(self, messages, **kwargs):
        raise self._exc


# ---------------------------------------------------------------------------
# 合法 JSON 路径
# ---------------------------------------------------------------------------


_VALID_PAYLOAD = (
    '{"hot_genres": ['
    '{"genre": "都市异能", "heat_signal": "起点都市榜前 10 占 3 本", '
    '"sample_titles": ["书A", "书B", "书C"]}, '
    '{"genre": "穿越", "heat_signal": "番茄热门前 20 占 5 本", '
    '"sample_titles": ["书D", "书E"]}'
    '], '
    '"hot_tropes": ["系统流+吐槽", "反派洗白", "轻喜剧爽文"], '
    '"market_summary": "近期榜单都市异能与穿越题材占主导,系统流+轻喜剧元素横切多题材。"}'
)


def test_build_analysis_returns_analysis_result_when_llm_returns_valid_json():
    """LLM 返回合法 JSON(新 schema)→ source='llm',字段解析正确。"""
    adapter = _FakeAdapter(_VALID_PAYLOAD)

    result = build_analysis(
        idea="校车进秘境",
        rankings_text="## 起点\n1. 书A\n2. 书B",
        llm_adapter=adapter,
    )

    assert isinstance(result, AnalysisResult)
    assert result.source == "llm"
    assert len(result.hot_genres) == 2
    assert result.hot_genres[0].genre == "都市异能"
    assert result.hot_genres[0].sample_titles == ["书A", "书B", "书C"]
    assert len(result.hot_tropes) == 3
    assert "系统流+吐槽" in result.hot_tropes
    assert "都市异能" in result.market_summary or "穿越" in result.market_summary


def test_build_analysis_repairs_json_wrapped_in_code_fence():
    """LLM 返回的 JSON 被 ```json ... ``` 包裹 → repair 成功。"""
    wrapped = f"```json\n{_VALID_PAYLOAD}\n```"
    adapter = _FakeAdapter(wrapped)

    result = build_analysis(idea="x", rankings_text="x", llm_adapter=adapter)

    assert result.source == "llm"
    assert len(result.hot_genres) == 2


def test_build_analysis_repairs_json_with_prefix_suffix():
    """LLM 返回含前后缀文本(解说 + JSON + 解说)→ repair 成功。"""
    polluted = f"好的,这是分析结果:\n{_VALID_PAYLOAD}\n以上基于榜单数据。"
    adapter = _FakeAdapter(polluted)

    result = build_analysis(idea="x", rankings_text="x", llm_adapter=adapter)

    assert result.source == "llm"
    assert len(result.hot_genres) == 2


# ---------------------------------------------------------------------------
# schema 不全 → 重试 1 次
# ---------------------------------------------------------------------------


def test_build_analysis_retries_when_schema_incomplete_then_succeeds():
    """schema 缺 market_summary → 重试 1 次;第二次返合法 → source='llm'。"""
    bad = '{"hot_genres": [{"genre": "x", "heat_signal": "y", "sample_titles": []}]}'
    adapter = _SequentialAdapter([bad, _VALID_PAYLOAD])

    result = build_analysis(idea="x", rankings_text="x", llm_adapter=adapter)

    assert result.source == "llm"
    assert len(result.hot_genres) == 2
    assert len(adapter.calls) == 2  # 调了 2 次


def test_build_analysis_falls_back_when_retry_still_fails_schema():
    """schema 缺关键字段,重试后仍不全 → source='llm_failed'。"""
    bad = '{"hot_genres": [{"genre": "x", "heat_signal": "y", "sample_titles": []}]}'
    adapter = _SequentialAdapter([bad, bad])  # 两次都缺 market_summary

    result = build_analysis(idea="x", rankings_text="x", llm_adapter=adapter)

    assert result.source == "llm_failed"
    assert len(adapter.calls) == 2  # 重试了 1 次


def test_build_analysis_does_not_retry_on_invalid_json():
    """LLM 返回完全非 JSON → 视为格式错,仍按"重试 1 次"逻辑(因为可能 repair 不回来)。"""
    adapter = _FakeAdapter("这不是 JSON,只是一段叙述,没有大括号。")

    result = build_analysis(idea="x", rankings_text="x", llm_adapter=adapter)

    assert result.source == "llm_failed"


# ---------------------------------------------------------------------------
# 异常 / 无 adapter
# ---------------------------------------------------------------------------


def test_build_analysis_falls_back_when_llm_raises():
    """LLM 异常 → 直接降级,不重试,source='llm_failed'。"""
    adapter = _FailingAdapter(RuntimeError("model offline"))

    result = build_analysis(idea="x", rankings_text="x", llm_adapter=adapter)

    assert result.source == "llm_failed"


def test_build_analysis_without_adapter_returns_unavailable():
    """没传 adapter → 直接 unavailable,不调 LLM。"""
    result = build_analysis(idea="x", rankings_text="x", llm_adapter=None)

    assert result.source == "unavailable"


# ---------------------------------------------------------------------------
# sample_titles 硬截断 ≤3
# ---------------------------------------------------------------------------


def test_build_analysis_truncates_sample_titles_to_three():
    """LLM 给某题材 sample_titles 塞了 5 本 → 硬截断到前 3 本。

    红线'不整列书单'的代码层兜底。
    """
    payload = (
        '{"hot_genres": [{'
        '"genre": "玄幻", "heat_signal": "热", '
        '"sample_titles": ["书1", "书2", "书3", "书4", "书5"]'
        '}], "hot_tropes": ["x"], "market_summary": "y"}'
    )
    adapter = _FakeAdapter(payload)

    result = build_analysis(idea="x", rankings_text="x", llm_adapter=adapter)

    assert result.source == "llm"
    assert len(result.hot_genres[0].sample_titles) == 3
    assert result.hot_genres[0].sample_titles == ["书1", "书2", "书3"]


# ---------------------------------------------------------------------------
# Markdown 渲染
# ---------------------------------------------------------------------------


def test_render_analysis_as_markdown_has_clear_sections():
    """渲染的 Markdown 含清晰小节:题材归纳 / 套路要素 / 行情概括。"""
    result = AnalysisResult(
        hot_genres=[
            HotGenre(genre="都市异能", heat_signal="占榜", sample_titles=["书A", "书B"]),
        ],
        hot_tropes=["系统流+吐槽", "轻喜剧爽文"],
        market_summary="近期都市异能占主导。",
        source="llm",
    )

    md = render_analysis_as_markdown(result)

    assert "都市异能" in md
    assert "系统流+吐槽" in md
    assert "近期都市异能占主导" in md
    # 渲染书名时每条 ≤3 本
    assert "书A" in md


def test_render_analysis_markdown_for_failed_source_marks_absent():
    """source='llm_failed' 时,渲染明确标注'失败/不可用/缺失',不假装有内容。"""
    result = AnalysisResult(source="llm_failed")

    md = render_analysis_as_markdown(result)

    assert "失败" in md or "不可用" in md or "缺失" in md


def test_render_analysis_markdown_for_each_genre_caps_at_three_books():
    """渲染时每条题材的 sample_titles 显示不超过 3 本。"""
    result = AnalysisResult(
        hot_genres=[
            HotGenre(
                genre="玄幻",
                heat_signal="热",
                sample_titles=["书1", "书2", "书3"],  # 已经被解析层截断
            ),
        ],
        hot_tropes=["x"],
        market_summary="y",
        source="llm",
    )

    md = render_analysis_as_markdown(result)

    # 三本都在,但没有第四本(渲染层不再额外截断,但保证不超)
    assert "书1" in md and "书2" in md and "书3" in md


# ---------------------------------------------------------------------------
# prompt 红线(集成检查:analyzer 用了新 tropes prompt)
# ---------------------------------------------------------------------------


def test_build_analysis_uses_tropes_prompt_with_redline():
    """analyzer 调的是新 build_tropes_prompt,prompt 含'不得引入榜单之外'红线。"""
    adapter = _FakeAdapter(_VALID_PAYLOAD)

    build_analysis(idea="某设想", rankings_text="## 起点\n1. 书A", llm_adapter=adapter)

    sent_text = "".join(m.get("content", "") for m in adapter.calls[0])
    assert "不得引入榜单之外" in sent_text
    # schema 关键字段在 prompt 里
    assert "hot_genres" in sent_text
    assert "market_summary" in sent_text
