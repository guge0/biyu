"""S-7b：没配 Key 时给人话，不报「可用」。"""
from __future__ import annotations

from biyu.ui import zhuque_routes
from biyu.ui.llm_error_copy import humanize_llm_error


def test_empty_bearer_header_becomes_missing_key_copy():
    msg = humanize_llm_error(Exception("LocalProtocolError: Illegal header value b'Bearer '"), default="x")
    assert "还没配模型 Key" in msg and "Bearer" not in msg


def test_rewriter_unavailable_when_fallback_adapter_has_no_key(monkeypatch):
    class _Reg:
        _models = {"v3": {"provider": "deepseek", "model_id": "deepseek-chat"}}

        def __init__(self, *_a, **_k):
            pass

    class _Adapter:
        api_key = ""
        model_name = "deepseek-chat"

    monkeypatch.setattr(zhuque_routes, "ModelRegistry", _Reg)
    monkeypatch.setattr(zhuque_routes, "get_config_path", lambda: "x")
    monkeypatch.setattr(zhuque_routes, "resolve_ui_adapter", lambda _reg: (_Adapter(), "v3"))
    info = zhuque_routes._rewriter_info()
    assert info["available"] is False


# ---------------------------------------------------------------------------
# S-7d：生成正文 / 重写 / 读稿审读走 CLI 子进程，没配 Key 时页面上也要是人话
# ---------------------------------------------------------------------------


def test_chapter_action_error_shows_missing_key_copy(tmp_path, monkeypatch):
    """子进程尾部日志里挑线索时，要能挑中 httpx 的缺 Key 行并翻成中文。"""
    import asyncio

    import biyu.ui.cli_executor as ex

    book = tmp_path / "Book"
    book.mkdir()
    (book / "book.json").write_text('{"title":"Book","genre":"dushi"}', encoding="utf-8")
    monkeypatch.setattr(ex, "resolve_book_dir", lambda _b: book)

    # 复刻无 Key 环境里 write 子进程的尾部：英文 httpx 异常在 RuntimeError 上面几行
    tail = [
        "  [2/4] Writer (v3, prompt=v4)...",
        "Traceback (most recent call last):",
        "httpx.LocalProtocolError: Illegal header value b'Bearer '",
        "RuntimeError: writer 工具轮模型调用失败；已发生费用已记账。",
    ]

    class FakeProc:
        def __init__(self):
            self.stdout = asyncio.StreamReader()
            for line in tail:
                self.stdout.feed_data((line + "\n").encode())
            self.stdout.feed_eof()
            self.stdin = None

        async def wait(self):
            return 1

    async def fake_create(*_args, **_kwargs):
        return FakeProc()

    monkeypatch.setattr(ex.asyncio, "create_subprocess_exec", fake_create)

    async def run():
        return [
            event
            async for event in ex.execute("write", book="Book", chapter=1, confirmed=True, extra={})
        ]

    events = asyncio.run(run())
    error = next(event for event in events if event["type"] == "error")
    assert "还没配模型 Key" in error["message"], error["message"]
    assert "Bearer" not in error["message"]
    assert "Illegal" not in error["message"]
