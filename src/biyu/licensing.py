"""S-7a 内测版授权 — 付费功能的唯一授权入口。

以后接激活码/正式版,只改这个模块;调用方(路由/前端)只认 check_feature。
内测规则:2027-01-31 当天仍可用,2027-02-01 起算到期;
到期后免费功能(写作管线/本地体检/朱雀体检)照常,付费功能(一键降 AI 率/去 AI 味)拒绝。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

logger = logging.getLogger("biyu.licensing")

EDITION = "beta"
BETA_EXPIRES = date(2027, 1, 31)

FREE_FEATURES: tuple[str, ...] = ("writing_pipeline", "local_ai_scan", "zhuque_check")
PAID_FEATURES: tuple[str, ...] = ("zhuque_fix", "deai")
ALL_FEATURES: tuple[str, ...] = FREE_FEATURES + PAID_FEATURES

EXPIRED_MESSAGE = (
    "内测版已于 2027-01-31 到期，一键降 AI 率与去 AI 味需升级正式版。写作和体检仍可继续使用。"
)


@dataclass(frozen=True)
class LicenseDecision:
    """一次授权判定的结果;message 是给作者看的人话,允许时为空串。"""

    allowed: bool
    reason: str
    message: str


def _today() -> date:
    """当前日期取本机时间;测试经 check_feature/status 的 today 参数注入,不改这里。"""
    return date.today()


def is_expired(today: date | None = None) -> bool:
    """到期口径:BETA_EXPIRES 当天仍可用,次日(True)起算到期。"""
    day = today if today is not None else _today()
    return day > BETA_EXPIRES


def check_feature(name: str, *, today: date | None = None) -> LicenseDecision:
    """唯一授权入口:功能名 → {allowed, reason, message}。

    - 未知功能名:拒绝并记日志(调用方写错名字时不放行)。
    - 免费功能:任何时候都允许(内测到期也不动写作与体检)。
    - 付费功能:未到期允许;到期后拒绝,message 是人话。
    """
    if name not in ALL_FEATURES:
        logger.warning("未知授权功能名:%r(按拒绝处理)", name)
        return LicenseDecision(False, "unknown_feature", f"未知的授权功能：{name}")
    if name in FREE_FEATURES:
        return LicenseDecision(True, "free", "")
    if is_expired(today):
        return LicenseDecision(False, "beta_expired", EXPIRED_MESSAGE)
    return LicenseDecision(True, "beta_active", "")


def status(today: date | None = None) -> dict[str, object]:
    """GET /api/license/status 的载荷:版本/到期日/剩余天数/各功能可用性。"""
    day = today if today is not None else _today()
    return {
        "edition": EDITION,
        "expires": BETA_EXPIRES.isoformat(),
        "days_left": (BETA_EXPIRES - day).days,
        "expired": day > BETA_EXPIRES,
        "features": {name: check_feature(name, today=day).allowed for name in ALL_FEATURES},
    }
