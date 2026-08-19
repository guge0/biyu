"""环境标记模块(P8-M1 T1)。

读 BIYU_ENV 环境变量,返环境章信息(测试=灰 / 真书=红)。

默认 test(灰):开发期作者误以为在测真书时,灰章+banner 双重提示降低风险。
设 BIYU_ENV=prod 才显红:进入真书数据流时强制显眼。

选环境变量不选 config 文件:
1. 不碰 config/ Key 红线区;
2. 进程级天然隔离(CI/容器化好控);
3. 改环境无需改 git 跟踪的配置。

非法值 fallback test + logging.warning(D-70:不沉默)。
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("biyu.ui.env")

# 视觉 token 同步自 styles.css(spec T-D):prod 用红 seal,test 用灰
_COLOR_PROD = "#a83232"
_COLOR_TEST = "#a8a8a8"

_LABEL_PROD = "真书"
_LABEL_TEST = "测试"


def read_env() -> dict[str, str]:
    """读 BIYU_ENV 环境变量,返环境章字典。

    Returns:
        {"level": "test"|"prod", "label": "测试"|"真书", "color": "#rrggbb"}
    """
    raw = (os.environ.get("BIYU_ENV") or "").strip().lower()
    if raw == "prod":
        return {"level": "prod", "label": _LABEL_PROD, "color": _COLOR_PROD}
    if raw in ("", "test"):
        return {"level": "test", "label": _LABEL_TEST, "color": _COLOR_TEST}
    # 非法值:fallback 到安全的 test,但出声(D-70 不沉默)
    logger.warning(
        "BIYU_ENV=%r 非法(只接受 'test' 或 'prod'),已 fallback 到 test。", raw
    )
    return {"level": "test", "label": _LABEL_TEST, "color": _COLOR_TEST}
