"""会话成本累计 + 软顶判定(P8-M1 T2)。

进程内单 session 累计成本,到软顶(默认 ¥2)时不静默花钱 —— 拦截 LLM 调用,
前端弹确认框,作者同意才放行。

M1 不持久化:进程重启会话归零。立项会话一般一次性,不跨日,可接受。

API:
- SessionCosts(softcap=2.0)
- .new_session() -> str                       新建 session,返 UUID
- .get_cumulative(sid) -> float               查累计
- .add_cost(sid, amount) -> float             累加,返新累计
- .check_softcap(sid, next_cost_estimate, confirm=False) -> SoftCapStatus
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass
class SoftCapStatus:
    """软顶判定结果。status ∈ {ok, softcap_reached, confirmed}。

    - ok:累计 + 估算 < softcap,正常放行。
    - softcap_reached:已到软顶且未 confirm,拦截。
    - confirmed:作者已 confirm,放行(不再拦截)。
    """

    status: str
    cumulative: float
    softcap: float
    projected: float


class SessionCosts:
    """进程内会话成本累计 + 软顶判定。

    线程安全未处理:FastAPI 默认事件循环单线程跑同步代码,UI 场景 OK;
    若未来多 worker 部署,需加锁。
    """

    def __init__(self, softcap: float = 2.0):
        self._softcap = softcap
        self._sessions: dict[str, float] = {}

    def new_session(self) -> str:
        sid = uuid.uuid4().hex
        self._sessions[sid] = 0.0
        return sid

    def get_cumulative(self, session_id: str) -> float:
        # 未知 session_id 当 0 处理(防御:不崩,但不掩盖问题)
        return self._sessions.get(session_id, 0.0)

    def add_cost(self, session_id: str, amount: float) -> float:
        cur = self._sessions.get(session_id, 0.0)
        new = cur + max(0.0, float(amount))
        self._sessions[session_id] = new
        return new

    def check_softcap(
        self,
        session_id: str,
        next_cost_estimate: float,
        confirm: bool = False,
    ) -> SoftCapStatus:
        cumulative = self.get_cumulative(session_id)
        projected = cumulative + max(0.0, float(next_cost_estimate))
        if projected >= self._softcap:
            status = "confirmed" if confirm else "softcap_reached"
        else:
            status = "ok"
        return SoftCapStatus(
            status=status,
            cumulative=cumulative,
            softcap=self._softcap,
            projected=projected,
        )
