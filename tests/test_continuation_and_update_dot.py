"""2026-10 三件:截断续写兜底 / git 落后红点 / 拉取路由。

- 截断续写:句中截断(非句读结尾)自动带断点续写至收束,费用入 writer_continuation;
  完整结尾不触发;连续两轮仍截断放行。
- git 落后:git_behind_count 走缓存;fetch 失败返回 None;version 端点带 behind_commits;
  pull 路由快进并提示重启。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from biyu.pipeline import _continue_if_truncated, _is_truncated


def _resp(text: str, cost: float = 0.01) -> SimpleNamespace:
    return SimpleNamespace(text=text, cost=cost)


def test_is_truncated_detects_mid_sentence_cut() -> None:
    assert _is_truncated("他抬起手，慢慢揩掉那点黑血。一下，两下。粗麻布")
    assert not _is_truncated("他抬起手，慢慢揩掉那点黑血。")
    assert not _is_truncated("「都别走。」")
    assert not _is_truncated("")


def test_continue_appends_until_sentence_complete(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    class Adapter:
        async def generate(self, messages, **kwargs):
            calls.append(messages[0]["content"])
            return _resp("血迹。远处传来马蹄声，他握紧了刀。")

    from biyu.config import BookConfig

    book = BookConfig(tmp_path)
    text, stat = asyncio.run(_continue_if_truncated(
        "他抬起手，慢慢揩掉那点黑血。一下，两下。粗麻布", Adapter(), book, 1,
    ))
    assert stat is not None and stat[0] == 1
    assert "粗麻布" in text and "握紧了刀。" in text
    assert len(calls) == 1
    assert "结尾片段" in calls[0]  # 断点上下文已附


def test_continue_gives_up_after_two_rounds(tmp_path) -> None:
    class Adapter:
        async def generate(self, messages, **kwargs):
            return _resp("还是半句不通的")

    from biyu.config import BookConfig

    book = BookConfig(tmp_path)
    text, stat = asyncio.run(_continue_if_truncated("截断", Adapter(), book, 1))
    assert stat[0] == 2  # 两轮后放行
    assert _is_truncated(text)  # 仍不完整,交编辑按戛然而止处理


def test_complete_text_skips_continuation(tmp_path) -> None:
    class Adapter:
        async def generate(self, messages, **kwargs):
            raise AssertionError("完整结尾不应调用续写")

    from biyu.config import BookConfig

    book = BookConfig(tmp_path)
    text, stat = asyncio.run(_continue_if_truncated("本章完。", Adapter(), book, 1))
    assert stat is None and text == "本章完。"


def test_git_behind_count_caches_and_degrades(tmp_path, monkeypatch) -> None:
    import biyu.runtime_config as rc

    rc._BEHIND_CACHE.update(ts=0.0, count=None)
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        if "fetch" in args:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="3\n", stderr="")

    import subprocess as _sp

    monkeypatch.setattr(_sp, "run", fake_run)
    assert rc.git_behind_count(tmp_path, max_age_seconds=0) == 3
    # 缓存生效:第二次不再打网络
    calls.clear()
    assert rc.git_behind_count(tmp_path) == 3
    assert calls == []

    # fetch 失败(离线)→ None,不亮红点
    rc._BEHIND_CACHE.update(ts=0.0, count=None)
    monkeypatch.setattr(_sp, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr=""))
    assert rc.git_behind_count(tmp_path, max_age_seconds=0) is None


def test_pull_route_reports_and_pull_helper_ff(tmp_path, monkeypatch) -> None:
    import biyu.runtime_config as rc

    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = list(args)
        return SimpleNamespace(returncode=0, stdout="Already up to date.\n", stderr="")

    import subprocess as _sp

    monkeypatch.setattr(_sp, "run", fake_run)
    ok, message = rc.git_pull_ff(tmp_path)
    assert ok is True
    assert captured["args"][-1] == "--ff-only"
