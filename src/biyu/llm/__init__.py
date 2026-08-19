import os as _os

# P6-13-B2: VPN 系统代理旁路——国内 LLM API 不需要走代理
# httpx trust_env=True 会读 Windows 系统代理，导致 VPN 开时 TLS 握手失败。
# 在 import 时注入 NO_PROXY，让 httpx 对这些域名直连。仅动环境变量，不改请求逻辑。
_DOMESTIC_API_DOMAINS = (
    "api.deepseek.com",
    "api.moonshot.cn",
    "open.bigmodel.cn",
    "ark.cn-beijing.volces.com",
)
_existing = _os.environ.get("NO_PROXY", "")
_new_domains = [d for d in _DOMESTIC_API_DOMAINS if d not in _existing]
if _new_domains:
    _os.environ["NO_PROXY"] = (_existing + "," if _existing else "") + ",".join(_new_domains)

from .base import EmbeddingResponse, LLMAdapter, LLMResponse
from .deepseek import DeepSeekAdapter
from .doubao import DoubaoAdapter
from .glm import GLMAdapter, LLMError
from .kimi import KimiAdapter
from .registry import ModelRegistry

__all__ = [
    "LLMAdapter",
    "LLMResponse",
    "EmbeddingResponse",
    "GLMAdapter",
    "DeepSeekAdapter",
    "KimiAdapter",
    "DoubaoAdapter",
    "LLMError",
    "ModelRegistry",
]
