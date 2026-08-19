# E2E 测试基建(P8-M2.5-T6)

> 状态:基建完成(2026-07-03)。冒烟集(立项 EMPTY / 书架 / 审读 / 提示词页 / SSE)留 T1-T5 完成后写。

## 怎么开 E2E(首次)

```bash
# 1. 装 playwright python 包(已加进 dev deps,`pip install -e ".[dev]"` 自带)
pip install -e ".[dev]"

# 2. 装 chromium 浏览器(~300MB,首次必装)
python -m playwright install chromium
```

## 怎么跑

```bash
# 默认全套(不含 e2e):E2E marker 默认 deselect
pytest

# 显式跑 E2E
pytest -m e2e

# 跑单个文件
pytest tests/e2e/test_smoke.py -m e2e

# 看浏览器(调试时)
pytest -m e2e --headed

# 慢动作(每步暂停)
pytest -m e2e --slowmo 500
```

## mock LLM 注入原理

`tests/e2e/conftest.py::_install_mock_llm()` 在 session 级 fixture 里替换
`biyu.ui.orchestrator._get_llm_adapter` 为返 mock adapter 的 lambda。

**mock adapter 复用** P8-M1 单测的 `_MockAdapter`(`tests/test_ui_orchestrator.py:65`),
按 prompt 内容返不同响应:

| Prompt 关键词 | Mock 响应 |
|---|---|
| "思路分类器" / "specific / directional / empty" | 路径(specific / directional / empty) |
| "套路归纳器" | hot_genres / hot_tropes / market_summary |
| "红蓝海对照分析师" | supply_crowding / demand_weak_signal / quadrant |
| "创作规律顾问" | rhythm / goals / cool_points / opening / dimensions |
| 其他 | `{}` |

**所有 E2E 测试默认走 mock**——任何 propose 调用不会真烧 LLM。

## 扩展 mock 响应

如要加新场景(如测试 SPECIFIC/DIRECTIONAL/EMPTY 三路径分别):

```python
# 在测试内显式覆盖 mock
def test_specific_path(page, base_url, _live_server):
    from biyu.ui import orchestrator as orch_mod
    from tests.test_ui_orchestrator import _MockAdapter
    orch_mod._get_llm_adapter = lambda alias=None: _MockAdapter(router_response="specific")
    # ... 测试逻辑
```

或在 `_install_mock_llm` 加 fixture 参数化。

## 怎么加新测试

1. 在 `tests/e2e/test_<feature>.py` 新建文件
2. 文件顶部加 `pytestmark = pytest.mark.e2e`(或单测试标 `@pytest.mark.e2e`)
3. 用 pytest-playwright 标准 fixture:
   - `page`:浏览器页面(每个测试新建,自动 close)
   - `browser`:浏览器实例(session 级共享)
   - `context`:浏览器上下文(测试级隔离)
4. `page.goto("/")` 自动拼 `base_url`
5. `page.request.get("/api/...")` 测 API 端点(不经浏览器)

## uvicorn 启动机制

- session 级共享一个 uvicorn 实例(daemon thread)
- unused port(OS 分配,避免冲突)
- 同进程 thread → monkeypatch 生效
- Windows + asyncio 兼容:uvicorn 用自己 loop,Playwright 用 sync_playwright,隔离

## CI 处理

E2E **不在 CI 跑**(老板预答:E2E 在 CI 跑不动 → 本地跑为准)。
pyproject.toml `addopts = "-m 'not manual and not e2e'"` 默认 deselect,
单测套件零影响。

## 已知限制

1. **chromium 二进制不进 git**:每台开发机首次 `python -m playwright install chromium`
2. **mock 完整性依赖**:`_MockAdapter` 覆盖 propose 四类(router/tropes/redblue/craft);
   如果 propose 后续加新 LLM 调用,mock 要同步扩展
3. **session 共享 uvicorn**:多测试并发可能干扰(当前测试串行,无问题;若加并发需独立 server)
4. **不做截图比对**:D-79 自走查证据包是手动截图,本框架不提供自动比对

## 关联 spec

- `specs/P8-M2.5-T6.md`(本子任务 spec)
- 父 spec:M2.5(未落盘,见 session start hook / 中枢更新页 v10 引用)
