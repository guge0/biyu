"""T7-1 污染源修复(P8-M2.5,2026-07-04)。

背景:全套 pytest 时,tests/fingerprint/test_adapter_contract.py 的首个
`asyncio.run()`(及后续所有 asyncio.run 调用)在 finally 里调
`asyncio.set_event_loop(None)`,把默认 event loop policy 的
`_set_called=True, _loop=None` 留下来。后续 `asyncio.get_event_loop()`
因此抛 RuntimeError('There is no current event loop in thread "MainThread"')
——这是 Python 3.9 stdlib 行为,非 bug。

之前 P7-9 在 tests/test_auto.py 的 `_run` helper 加了 try/except RuntimeError
兜底治症状。本修复治污染源:每个测试开始前确保主线程有可用 loop,
`_run` 不必自带兜底也全绿(spec P8-M2.5 验收第 6 条);P7-9 兜底保留作
belt-and-suspenders。

D-83 选项比较:
- 修在每个 `asyncio.run` call site(test_adapter_contract / test_editor 等 5+ 文件)
  → 改动面大,非最小。
- **本选项(测试基础设施层 conftest)**:1 个新文件、7 行、公共 API、不动 src/。
"""
import asyncio

import pytest


@pytest.fixture(autouse=True)
def _ensure_main_thread_event_loop():
    """每个测试前:若主线程被前测试的 asyncio.run() 显式 set None,
    重设一个新 loop,让默认 policy 的 get_event_loop() 不再抛 RuntimeError。
    """
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    yield
