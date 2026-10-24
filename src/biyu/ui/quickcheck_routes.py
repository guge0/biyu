"""S-3 T7 · 快检台路由(纯本地零成本;无 Key 可用)。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from biyu.quickcheck import MAX_SCAN_CHARS, scan_text

router = APIRouter(prefix="/api/quickcheck", tags=["quickcheck"])


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


@router.post("/scan")
def quickcheck_scan(request: ScanRequest) -> dict[str, Any]:
    if len(request.text) > MAX_SCAN_CHARS:
        raise HTTPException(status_code=413, detail=f"文本超过 {MAX_SCAN_CHARS} 字上限，请分段粘贴")
    return scan_text(request.text)
