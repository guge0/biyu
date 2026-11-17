"""朱雀检测客户端(EdgeOne Makers 官方网关)。

产品化自 _s6_ref/zhuque.py(已验证原型):
- windows(text):  is_merge=false → 逐窗 [{order, start, end, text, conf, label}]
- verdict(text):  is_merge=true  → {labels_ratio("0"人工/"1"AI/"2"疑似), softmax_confidence}
- used_tokens:    makers_models_usage.total_tokens 累计
- 失败抛 ZhuqueError,message 是给作者看的人话;Key 永不进异常文本、永不进日志。

transport 可注入:async (url, headers, payload) -> (status_code, body)。
测试注入假 transport 即可全离线;默认实现走 httpx。
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

ZHUQUE_URL = "https://ai-gateway.edgeone.link/v1/providers/zhuque-text/classify"

Transport = Callable[[str, dict, dict], Awaitable["tuple[int, Any]"]]


class ZhuqueError(Exception):
    """朱雀调用失败。message 面向作者(人话),绝不包含 Key。"""


async def _http_transport(url: str, headers: dict, payload: dict) -> "tuple[int, Any]":
    import httpx

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        try:
            body: Any = resp.json()
        except ValueError:
            body = resp.text
        return resp.status_code, body


def _body_text(body: Any) -> str:
    if isinstance(body, dict):
        for key in ("msg", "message", "error"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, dict) and value.get("message"):
                return str(value["message"])
        return ""
    return str(body) if body is not None else ""


def _author_message(status: int, body: Any) -> str:
    """把 HTTP/网关错误翻成作者能懂的一句话。"""
    text = _body_text(body)
    if status in (401, 403):
        return "朱雀 Key 无效：检查 Key 是否复制全，重新粘贴一份再试。"
    if status == 402 or "quota" in text.lower() or "额度" in text or "balance" in text.lower():
        return "朱雀额度用完了：去 EdgeOne 控制台看看额度，或换一个 Key。"
    if status == 429:
        return "朱雀那边限流了：稍等一两分钟再点一次。"
    if status >= 500:
        return "朱雀服务暂时不可用：稍等一两分钟再点一次。"
    detail = text[:120].strip() or f"朱雀返回了异常状态({status})"
    return f"朱雀体检失败：{detail}"


def _gateway_message(body: dict) -> str:
    text = _body_text(body)[:120].strip()
    return f"朱雀体检失败：{text or '网关没有说明原因'}"


class ZhuqueClient:
    """朱雀文本检测客户端。"""

    def __init__(
        self,
        key: str,
        transport: Transport | None = None,
        *,
        retries: int = 2,
        retry_delay: float = 1.5,
    ) -> None:
        if not key or not str(key).strip():
            raise ZhuqueError("还没填朱雀 Key：先在右侧卡片里填一下。")
        self._key = str(key).strip()
        self._transport = transport or _http_transport
        self._retries = retries
        self._retry_delay = retry_delay
        self.used_tokens = 0

    async def _classify(self, text: str, is_merge: bool) -> dict:
        """POST 一次分类。5xx/429/网络错误重试;Key/额度类错误立刻停。"""
        payload = {"text": text, "is_merge": is_merge}
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        last: ZhuqueError | None = None
        for attempt in range(self._retries + 1):
            try:
                status, body = await self._transport(ZHUQUE_URL, headers, payload)
            except Exception:
                last = ZhuqueError("网络不通：检查一下网络(或代理)再点一次。")
            else:
                if status == 200 and isinstance(body, dict) and body.get("status") == "success":
                    self._add_usage(body)
                    return body
                if status == 200 and isinstance(body, dict):
                    raise ZhuqueError(_gateway_message(body))
                if status != 429 and status < 500:
                    # 401/402 等确定性失败,重试无益
                    raise ZhuqueError(_author_message(status, body))
                last = ZhuqueError(_author_message(status, body))
            if attempt < self._retries:
                await asyncio.sleep(self._retry_delay)
        assert last is not None
        raise last

    def _add_usage(self, body: dict) -> None:
        usage = body.get("makers_models_usage") or {}
        try:
            self.used_tokens += int(usage.get("total_tokens") or 0)
        except (TypeError, ValueError):
            pass

    async def windows(self, text: str) -> list[dict[str, Any]]:
        """逐窗检测(is_merge=false):每窗 order/start/end/text/conf/label。"""
        data = await self._classify(text, is_merge=False)
        out: list[dict[str, Any]] = []
        cursor = 0
        for index, seg in enumerate(data.get("segment_labels") or [], 1):
            piece = seg.get("text")
            if not isinstance(piece, str):
                position = seg.get("position") or []
                piece = ""
                if len(position) == 2 and all(isinstance(v, int) for v in position):
                    piece = text[position[0]:position[1]]
            start = text.find(piece, cursor) if piece else cursor
            if start < 0:
                start = cursor
            cursor = start + len(piece)
            out.append({
                "order": index,
                "start": start,
                "end": start + len(piece),
                "text": piece,
                "conf": float(seg.get("conf") or 0.0),
                "label": seg.get("label"),
            })
        return out

    async def verdict(self, text: str) -> dict[str, Any]:
        """整章判定(is_merge=true):labels_ratio + softmax_confidence。"""
        data = await self._classify(text, is_merge=True)
        labels_ratio = data.get("labels_ratio") or {}
        return {
            "labels_ratio": {str(k): float(v) for k, v in labels_ratio.items() if isinstance(v, (int, float))},
            "softmax_confidence": float(data.get("softmax_confidence") or 0.0),
        }
