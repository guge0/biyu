"""S6-5: 写手包工具契约——DeepSeek 前缀合并顺序锁定。

写手包工具在 adapter 边界拦截请求,并自行合并 cacheable_prefix + messages
渲染导出。此测试把「合并顺序与内容不动」钉死:工具导出 == 真实线上请求体。
若有人改动 deepseek.py 的合并逻辑,此测试必须先红。
"""
import asyncio
import json

import httpx

from biyu.llm.deepseek import DeepSeekAdapter


def test_deepseek_sends_prefix_then_messages_in_order(monkeypatch):
    seen = {}

    async def handler(request: httpx.Request):
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    adapter = DeepSeekAdapter(
        model_name="deepseek-v4-pro", api_key="k",
        base_url="https://api.deepseek.com/v1",
    )
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: original_client(
            transport=httpx.MockTransport(handler),
            **{k: v for k, v in kw.items() if k != "proxy"},
        ),
    )

    prefix = [
        {"role": "system", "content": "写手系统提示词"},
        {"role": "user", "content": "稳定层2：世界观+声纹"},
        {"role": "assistant", "content": "已加载世界观和角色卡。"},
    ]
    dynamic = [{"role": "user", "content": "Layer1+Layer3 动态段"}]
    asyncio.run(adapter.generate(dynamic, cacheable_prefix=prefix, max_tokens=100))

    sent = seen["payload"]["messages"]
    assert sent == prefix + dynamic, "线上消息必须恰为 前缀+动态 顺序拼接,不得增删改序"
    assert sent[0]["content"] == "写手系统提示词", "第一条必须是写手 system"
    assert sent[-1]["content"] == "Layer1+Layer3 动态段", "最后一条必须是动态段"
