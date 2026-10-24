"""S-3 T5 · 设定/大纲格 AI 起草端点(决策3:一律草稿态+确认闸,绝不直接覆盖)。

POST /api/settings/books/{book}/cells/{cell_id}/draft
  → {ok, draft}:LLM 按既有格内容起草补充;前端以「✦ AI 起草待审稿」呈现,
    作者点「批准并合入」才走既有 PUT cells 保存链(带版本 409 保护)。

仅支持书级两格(north_star/book_outline)与世界观七格;不触碰既有保存语义。
prompt 为新功能工程延伸,不改任何既有 prompts 文件。
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/api/settings", tags=["cell-draft"])

_DRAFTABLE = {
    "north_star": "全书北极星(一句话终极命题)",
    "book_outline": "分卷大纲",
    "world_narrative_anchors": "创作锚点",
    "world_facts": "不可变硬设定",
    "world_power_system": "力量·修炼体系",
    "world_forbidden": "绝对禁止红线",
    "world_geography": "地理",
    "world_factions": "势力",
    "world_timeline": "时间线锚点",
}


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str = ""


def _build_prompt(cell_id: str, existing: str) -> list[dict[str, str]]:
    label = _DRAFTABLE[cell_id]
    return [
        {"role": "system", "content": (
            f"你是中文网文设定编辑。为「{label}」这一格起草补充内容。"
            "要求:只输出正文内容本身(不要标题不要解释),中文,不超过 200 字,"
            "与已有内容风格一致、不与已有条目重复;如果是列表类内容,每行一条。"
        )},
        {"role": "user", "content": f"这一格已有的内容:\n{existing or '(空)'}\n\n请起草补充内容。"},
    ]


@router.post("/books/{book}/cells/{cell_id}/draft")
async def draft_cell(book: str, cell_id: str, request: DraftRequest) -> dict[str, Any]:
    if cell_id not in _DRAFTABLE:
        raise HTTPException(status_code=404, detail="这一格不支持 AI 起草")
    from biyu.config import get_registry

    # 复用 settings.py 的读取口径拿当前格内容(不落任何写操作)
    from biyu.ui.settings import _book_dir, _cell

    try:
        current = _cell(_book_dir(book), cell_id)
    except HTTPException:
        raise
    existing = str(current.get("content") or "")
    instruction = request.instruction.strip()
    messages = _build_prompt(cell_id, existing)
    if instruction:
        messages.append({"role": "user", "content": "作者补充要求:" + instruction})

    adapter = get_registry().get_adapter_for_stage("writer")
    try:
        resp = await adapter.generate(messages, temperature=0.6, max_tokens=600)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    text = re.sub(r"^```.*?\n|```$", "", (resp.text or "").strip(), flags=re.M).strip()
    if not text:
        return {"ok": False, "error": "模型没有返回草稿内容,请稍后重试"}
    return {"ok": True, "draft": text, "cell_version": current.get("version")}
