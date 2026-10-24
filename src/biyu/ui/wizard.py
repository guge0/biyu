"""S-3 T4 · 一句话开书向导后端(图纸屏 2)。

- POST /api/wizard/premise:LLM 推演立项方案(书名×3/北极星/世界观硬设定/主角卡/第一卷)。
- POST /api/wizard/books:作者确认后才落盘建书并填 9 格与主角卡(REQ-W1:
  premise 失败或作者中途放弃时,磁盘上不会出现残缺空书——建书只发生在本步)。

提示词说明:本模块 prompt 为「一句话开书」新功能的工程延伸(design.md 授权:
图纸未定义实现细节处按图纸视觉语言延伸并单列清单),不触碰任何既有
prompts/ 与 src/biyu/prompts/ 文件。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/api/wizard", tags=["wizard"])

_GENRES = ("末世回溯", "玄幻修仙", "都市异能", "悬疑智斗", "历史权谋", "无限流", "轻小说")

# 题材中文 → 建书代码值(genre.js 按代码映射徽章)
_GENRE_CODES = {
    "末世回溯": "kehuan", "玄幻修仙": "xuanhuan", "都市异能": "dushi",
    "悬疑智斗": "xuanyi", "历史权谋": "lishi", "无限流": "qihuan", "轻小说": "qihuan",
}


class PremiseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idea: str
    genre: str = ""
    word_tier: str = "3000"


class CreateFromPremiseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    genre: str = ""
    word_tier: str = "3000"
    summary: str = ""
    worldview: str = ""
    protagonist: str = ""
    vol1: str = ""


_PREMISE_SYSTEM = (
    "你是中文网文开书策划。根据作者的一句话想法,输出严格 JSON(不要 markdown 代码块):"
    '{"titles":["书名1","书名2","书名3"],"summary":"一句话故事(全书北极星,60字内)",'
    '"worldview":["硬设定1","硬设定2","硬设定3"],"protagonist":"主角卡一句话(姓名+定位+性格亮点)",'
    '"vol1":"第一卷方向(80字内)"}'
    "。书名要有网文钩子、避免烂大街;硬设定必须可核查、能当保真闸红线用。"
)


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"```(?:json)?|```", "", text).strip()
    match = re.search(r"\{.*\}", cleaned, re.S)
    if not match:
        raise ValueError("模型输出里找不到 JSON 立项方案")
    return json.loads(match.group(0))


async def _generate_premise(idea: str, genre: str) -> dict[str, Any]:
    from biyu.config import get_registry

    # 用 writer(chat) 档:planner 常配 deepseek-reasoner,纯 JSON 输出不稳(text 可能为空)
    adapter = get_registry().get_adapter_for_stage("writer")
    user = f"一句话想法:{idea}\n题材倾向:{genre or '不限'}"
    last_error: Exception | None = None
    for _attempt in range(2):
        resp = await adapter.generate(
            [{"role": "system", "content": _PREMISE_SYSTEM},
             {"role": "user", "content": user}],
            temperature=0.7,
            max_tokens=1600,
        )
        try:
            data = _extract_json(resp.text or "")
        except ValueError as exc:
            last_error = exc
            continue
        titles = [str(t).strip() for t in data.get("titles", []) if str(t).strip()][:3]
        if len(titles) < 3:
            last_error = ValueError("模型给出的候选书名不足 3 个")
            continue
        worldview = [str(w).strip() for w in data.get("worldview", []) if str(w).strip()][:5]
        if not worldview:
            last_error = ValueError("模型没有给出世界观硬设定")
            continue
        return {
            "titles": titles,
            "summary": str(data.get("summary", "")).strip(),
            "worldview": worldview,
            "protagonist": str(data.get("protagonist", "")).strip(),
            "vol1": str(data.get("vol1", "")).strip(),
        }
    raise last_error or ValueError("推演失败")


@router.post("/premise")
async def wizard_premise(request: PremiseRequest) -> dict[str, Any]:
    idea = request.idea.strip()
    if not idea:
        raise HTTPException(status_code=400, detail="请先写下你的一句话想法")
    try:
        result = await _generate_premise(idea, request.genre)
    except HTTPException:
        raise
    except Exception as exc:  # 连接失败/余额不足/输出不合法 → REQ-W1:不建任何书
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "result": result}


def _north_star_md(summary: str) -> str:
    return f"# 北极星\n\n## 一句话故事\n{summary.strip()}\n"


def _outline_md(vol1: str) -> str:
    return f"# 大纲\n\n## 第一卷\n{vol1 or '（待补充）'}\n"


@router.post("/books")
def wizard_create_book(request: CreateFromPremiseRequest) -> dict[str, Any]:
    """作者确认立项结果后一次性建书并填格;任何一步失败即整体失败(不建残书)。"""
    from biyu.book_service import create_book
    from biyu.config import get_data_root
    from biyu.setup_asset_versions import (
        update_book_outline_text,
        update_character_card,
        update_north_star_text,
        update_worldbook_section,
    )

    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="书名不能为空")
    if not request.summary.strip():
        raise HTTPException(status_code=400, detail="请先填一句话简介（全书北极星），再开书")
    genre_code = _GENRE_CODES.get(request.genre, "xuanyi")

    created = create_book(title, genre_code, data_root=get_data_root())
    book_dir = Path(created.book_dir)
    try:
        update_north_star_text(book_dir, _north_star_md(request.summary), actor="开书向导")
        update_book_outline_text(book_dir, _outline_md(request.vol1), actor="开书向导")
        update_worldbook_section(
            book_dir, "facts",
            [line.strip() for line in request.worldview.splitlines() if line.strip()],
            actor="开书向导",
        )
        protagonist = request.protagonist.strip()
        if protagonist:
            name_match = re.match(r"^[\u4e00-\u9fa5A-Za-z0-9·]{1,12}", protagonist)
            card = {
                "name": name_match.group(0) if name_match else "主角",
                "tier": "protagonist",
                "role": protagonist[:60],
                "background": "",
                "personality": "",
                "aliases": {"narrator_default": name_match.group(0) if name_match else "主角",
                            "self_referent": "我", "called_by": {}},
                "forbidden_in_narrative": [],
                "voice_examples": [],
            }
            update_character_card(book_dir, card, reason="wizard_create", actor="开书向导")
    except Exception:
        # 落格失败:回滚刚建的空书目录,保持「不建残书」语义
        import shutil

        shutil.rmtree(book_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="开书档案写入失败,已回滚,没有留下残书")

    return {"ok": True, "id": created.book_id, "title": title}
