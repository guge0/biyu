"""S-3C · LLM 报错人话化(只做文案映射,不改任何业务/网络逻辑)。

坏 Key(401)、余额不足(402)、断网/超时等异常,原先以 "LLMError: [401] Authentication
Fails..." 之类的原始异常串直出到连接保存/向导推演/导演方案/写章/编辑审读各阶段;
本模块把它们翻成作者能懂、能行动的中文,原始信息保留在括号里供排查。
"""
from __future__ import annotations

import re

_STATUS_COPY: dict[int, str] = {
    401: "API Key 无效或已过期（服务商返回 401）。请到「设置 → 连接」检查 Key 是否复制完整、服务商是否选对",
    403: "API Key 没有权限（服务商返回 403）。请确认这个 Key 有使用所选模型的权限",
    404: "接口地址或模型名不对（服务商返回 404）。请检查接口地址与模型 ID",
    402: "账户余额不足（服务商返回 402）。请到服务商官网/控制台充值后再试",
    429: "请求太频繁或超出限额（服务商返回 429）。请等一两分钟再试",
}
for _code in range(500, 512):
    _STATUS_COPY[_code] = "服务商那边出了问题（5xx）。稍等几分钟再试；持续出现请检查服务商状态页"

_TIMEOUT_KEYS = ("timed out", "timeout", "readtimeout", "connecttimeout", "10060", "10054")
_CONNECT_KEYS = ("connect", "connection", "getaddrinfo", "name or service", "network", "10061", "连接失败")

_STATUS_RE = re.compile(r"\[(\d{3})\]")


def _trim(text: str, limit: int = 220) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def humanize_llm_error(
    exc: BaseException | None = None, *, raw: str = "", default: str = ""
) -> str:
    """把 LLM 调用异常翻成作者能行动的人话。

    - exc:异常对象(LLMError 带 status_code;其他异常取 str(exc));
    - raw:只有文本时给(如章动作子进程的末行日志),与 exc 二选一;
    - default:不命中任何已知模式时的回退文案(如调用方原有的 f"{type}: {exc}")。
    """
    text = raw if raw else (f"{exc}" if exc is not None else "")
    status = getattr(exc, "status_code", None) if exc is not None else None
    if status is None:
        match = _STATUS_RE.search(text)
        if match:
            status = int(match.group(1))
    if status is not None and status in _STATUS_COPY:
        return f"{_STATUS_COPY[status]}（原始信息：{_trim(text)}）"
    lowered = text.lower()
    if any(key in lowered for key in _TIMEOUT_KEYS):
        return f"请求超时：服务商在限定时间内没有响应。请检查网络（含代理/VPN）后重试；持续出现可稍后再试（原始信息：{_trim(text)}）"
    if any(key in lowered for key in _CONNECT_KEYS):
        return f"连不上服务商：请检查网络是否断开、接口地址是否填对（含代理/VPN 拦截）（原始信息：{_trim(text)}）"
    if not text.strip():
        return default or "生成失败，原因没有记录。"
    return default or text
