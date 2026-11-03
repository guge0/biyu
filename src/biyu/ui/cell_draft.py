"""S-3 T5 · 设定/大纲格 AI 起草端点(决策3:一律草稿态+确认闸,绝不直接覆盖)。

POST /api/settings/books/{book}/cells/{cell_id}/draft
  → {ok, draft}:LLM 按既有格内容起草补充;前端以「✦ AI 起草待审稿」呈现,
    作者点「批准并合入」才走既有 PUT cells 保存链(带版本 409 保护)。

仅支持书级两格(north_star/book_outline)与世界观七格;不触碰既有保存语义。
prompt 为新功能工程延伸,不改任何既有 prompts 文件。
S-3B 缺陷1b:提示词升级 v2(老板终审件《新提示词全文_待老板终审.md》第二节),
system 增「不得与北极星和题材冲突」,user 增本书题材+北极星两行上下文。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
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

# 与 static/genre.js 的 GENRE_MAP 同源(题材代号 → 中文)
_GENRE_LABELS = {
    "xuanhuan": "玄幻", "qihuan": "奇幻", "dushi": "都市", "xianxia": "仙侠",
    "kehuan": "科幻", "lishi": "历史", "xuanyi": "悬疑", "qingxiaoshuo": "轻小说",
    "yanqing": "言情", "wuxia": "武侠", "junshi": "军事", "youxi": "游戏",
    "jingji": "竞技", "lingyizhentan": "灵异侦探", "tongren": "同人",
}


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str = ""


def _north_star_line(content: str) -> str:
    """北极星 md → 一句话(优先「一句话故事」小节,≤60 字)。"""
    if not content:
        return ""
    lines = content.splitlines()
    picked: list[str] = []
    for index, line in enumerate(lines):
        if line.strip().startswith("##") and "一句话故事" in line:
            for follow in lines[index + 1:]:
                if follow.strip().startswith("#"):
                    break
                if follow.strip():
                    picked = [follow.strip()]
                    break
            break
    if not picked:
        picked = [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    return re.sub(r"\s+", " ", " ".join(picked))[:60]


def _book_context(book_dir: Path) -> tuple[str, str]:
    """(题材中文, 北极星一句话):v2 user 模板的本书上下文两行。"""
    genre = ""
    try:
        meta = json.loads((book_dir / "book.json").read_text(encoding="utf-8"))
        genre = str(meta.get("genre", "")).strip()
    except (OSError, ValueError):
        genre = ""
    star = ""
    try:
        from biyu.ui.settings import _cell

        star = _north_star_line(str(_cell(book_dir, "north_star").get("content") or ""))
    except Exception:
        star = ""
    return _GENRE_LABELS.get(genre, genre or "不限"), star


def _build_prompt(cell_id: str, existing: str, *, genre_label: str, north_star: str) -> list[dict[str, str]]:
    label = _DRAFTABLE[cell_id]
    return [
        {"role": "system", "content": (
            f"你是中文网文设定编辑。为「{label}」这一格起草补充内容。"
            "要求：只输出正文内容本身（不要标题不要解释），中文，不超过 200 字，"
            "与已有内容风格一致、不与已有条目重复；如果是列表类内容，每行一条；"
            "补充内容不得与本书北极星和题材冲突。"
        )},
        {"role": "user", "content": (
            f"本书题材：{genre_label}\n"
            f"全书北极星：{north_star or '（暂无）'}\n"
            f"这一格已有的内容：\n{existing or '(空)'}\n\n请起草补充内容。"
        )},
    ]


@router.post("/books/{book}/cells/{cell_id}/draft")
async def draft_cell(book: str, cell_id: str, request: DraftRequest) -> dict[str, Any]:
    if cell_id not in _DRAFTABLE:
        raise HTTPException(status_code=404, detail="这一格不支持 AI 起草")
    # S-3B 走查修复(与缺陷1同根因,按老板 premise→v4_flash 同一裁定逻辑):
    # writer 档(v4_pro)思考模式会把 600 max_tokens 全部耗在 reasoning 上,
    # content 恒空 → 草稿闸永远「模型没有返回草稿内容」。改用 v4_flash 非思考档。
    from biyu.config import get_config_path
    from biyu.llm import ModelRegistry

    from .model_alias import resolve_ui_adapter

    try:
        adapter, _alias = resolve_ui_adapter(ModelRegistry(get_config_path()))
    except (FileNotFoundError, KeyError, ValueError) as exc:
        return {"ok": False, "error": f"起草模型不可用：请先在连接设置保存 Key（{exc}）"}

    # 复用 settings.py 的读取口径拿当前格内容(不落任何写操作)
    from biyu.ui.settings import _book_dir, _cell

    try:
        current = _cell(_book_dir(book), cell_id)
    except HTTPException:
        raise
    existing = str(current.get("content") or "")
    instruction = request.instruction.strip()
    genre_label, north_star = _book_context(_book_dir(book))
    messages = _build_prompt(cell_id, existing, genre_label=genre_label, north_star=north_star)
    if instruction:
        messages.append({"role": "user", "content": "作者补充要求:" + instruction})

    try:
        resp = await adapter.generate(messages, temperature=0.6, max_tokens=600)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    text = re.sub(r"^```.*?\n|```$", "", (resp.text or "").strip(), flags=re.M).strip()
    if not text:
        return {"ok": False, "error": "模型没有返回草稿内容,请稍后重试"}
    return {"ok": True, "draft": text, "cell_version": current.get("version")}
