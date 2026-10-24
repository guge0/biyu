"""S-3 无 Key 体验层只读接口:耕读历统计与朱批钤印状态(纯本地,可重算)。"""
from __future__ import annotations

from fastapi import APIRouter

from biyu.config import get_data_root
from biyu.ui_seed.homestead import homestead_stats, seals_state

router = APIRouter(tags=["ui-seed"])


@router.get("/api/homestead/stats")
def homestead_stats_route() -> dict:
    return homestead_stats(get_data_root())


@router.get("/api/seals/state")
def seals_state_route() -> dict:
    return seals_state(get_data_root())
