"""E2E 测试 fixtures:启动 uvicorn(真实 HTTP)+ mock LLM 注入。

Playwright 不可用时整个 e2e suite 跳过(pytest.importorskip)。


设计:
- `_live_server` session-scoped:启 uvicorn 在 unused port(daemon thread)+ monkeypatch
  `biyu.ui.orchestrator._get_llm_adapter` 返 mock adapter。**mock 是默认的**(本目录所有
  E2E 测试默认走 mock,要真调 LLM 见 README.md "扩展 mock" 段)。
- `base_url` session-scoped:从 `_live_server` 拿 URL,pytest-playwright 自动用。
- Playwright 的 `page` / `browser` / `context` fixture 由 pytest-playwright 标准提供。

为什么 uvicorn 在同进程 thread 跑(而非 subprocess):
- monkeypatch 在主进程应用,thread 共享进程 → patch 生效
- subprocess 隔离 → patch 失效,需要环境变量序列化 mock,复杂度上升

Windows / asyncio 兼容:
- uvicorn 使用自己的 asyncio loop(在 thread 内)
- pytest-playwright 用 sync_playwright(独立 loop)
- 两者隔离,互不污染主线程
- E2E marker 默认 deselect,跟 TestCircuitBreaker 等单测不互相干扰
"""
from __future__ import annotations

import socket
import os
import threading
import tempfile
import time

import pytest
import uvicorn

# Playwright 未安装时跳过整个 e2e suite(防 FixtureLookupError)
pytest.importorskip("playwright")


def _find_unused_port(host: str = "127.0.0.1") -> int:
    """让 OS 分配一个可用端口(socket bind 后立刻释放,有微小竞争窗口但对测试够用)。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _install_mock_llm():
    """monkeypatch `biyu.ui.orchestrator._get_llm_adapter` 返 mock adapter。

    同时强制所有占位开关为 True(不依赖 PLACEHOLDER_FLAGS 生产值),
    确保 e2e 测试不调用真 LLM、不依赖生产配置。

    复用 P8-M1 单测的 `_MockAdapter`(`tests/test_ui_orchestrator.py:65`),
    它按 prompt 内容返不同响应(router/tropes/redblue/craft 四类)。
    """
    from biyu.ui import orchestrator as orch_mod
    from tests.test_ui_orchestrator import _MockAdapter

    # 强制占位模式:编辑器/导演/起名 全部走占位,不依赖生产 PLACEHOLDER_FLAGS 值
    # 原因:2026-07-06 B 核后生产值已翻为 False(真 LLM),测试不可依赖此值
    from biyu.ui.prompts_editor import PLACEHOLDER_FLAGS
    from biyu.ui.prompts_naming import set_naming_placeholder
    PLACEHOLDER_FLAGS["editor"] = True
    PLACEHOLDER_FLAGS["director"] = True
    set_naming_placeholder(True)

    # mock propose 的 LLM adapter
    _mock = _MockAdapter(router_response="specific")
    orch_mod._get_llm_adapter = lambda alias=None: _mock
    return _mock


@pytest.fixture(scope="session")
def _live_server():
    """启动 uvicorn 在 unused port,session 级共享一个实例。

    yield (host, port);teardown 设 should_exit 关闭 server。
    """
    # mock 注入(同进程 → thread 共享)
    _install_mock_llm()

    keys = (
        "BIYU_RUNTIME_ROLE", "BIYU_ENV", "BIYU_DATA_ROOT", "BIYU_TEST_DATA_ROOT", "BIYU_DATA_ROOT_2",
        "BIYU_BACKUP_ROOT", "BIYU_AUTO_BACKUP", "BIYU_USER_CONFIG_DIR", "BIYU_TRASH_ROOT",
    )
    previous = {key: os.environ.get(key) for key in keys}
    with tempfile.TemporaryDirectory(prefix="biyu-e2e-data-") as data_root:
        os.environ["BIYU_RUNTIME_ROLE"] = "test"
        os.environ["BIYU_ENV"] = "test"
        os.environ["BIYU_DATA_ROOT"] = data_root
        os.environ["BIYU_TEST_DATA_ROOT"] = data_root
        os.environ.pop("BIYU_DATA_ROOT_2", None)
        os.environ["BIYU_AUTO_BACKUP"] = "0"
        os.environ["BIYU_BACKUP_ROOT"] = str(Path(data_root) / "backup")
        os.environ["BIYU_USER_CONFIG_DIR"] = str(Path(data_root) / "user-config")
        os.environ["BIYU_TRASH_ROOT"] = str(Path(data_root) / "trash")

        port = _find_unused_port()
        config = uvicorn.Config(
            "biyu.ui.app:app",
            host="127.0.0.1",
            port=port,
            log_level="warning",  # 减少测试日志噪音
            # Windows + asyncio 兼容:uvicorn 自己管理 loop
            loop="auto",
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        try:
            thread.start()

            # 等 uvicorn 真启起来(server.started 为 True)
            deadline = time.time() + 15.0
            while time.time() < deadline:
                if server.started:
                    break
                time.sleep(0.1)
            else:
                server.should_exit = True
                raise RuntimeError("uvicorn 启动超时(15s)")

            yield ("127.0.0.1", port)
        finally:
            server.should_exit = True
            thread.join(timeout=5.0)
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


@pytest.fixture(scope="session")
def base_url(_live_server) -> str:
    """pytest-playwright 识别 `base_url` fixture,page.goto("/") 会自动拼接。"""
    host, port = _live_server
    return f"http://{host}:{port}"
