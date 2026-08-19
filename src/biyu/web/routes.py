"""API 路由 — 所有 REST + SSE 端点。"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from biyu import config as _config
from biyu.config import (
    BookConfig,
    find_book_dir,
    get_data_root,
    get_data_root_2,
    load_characters_yaml,
)
from biyu.truth_files import read_all_truth_files
from biyu.web.sse import make_event, sse_generator
from biyu.ui.workbench_versions import save_outline_version, sync_outline_version

logger = logging.getLogger(__name__)

router = APIRouter()


# ── 辅助 ────────────────────────────────────────────────────────────────────

def _book_dir(book: str) -> Path:
    """Resolve a book across all visible data roots (I-1 dual-root)."""
    roots = [_config.get_data_root()]
    second = _config.get_data_root_2()
    if second is not None:
        roots.append(second)
    try:
        return find_book_dir(book, roots=roots)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── 书列表 / 新建 ───────────────────────────────────────────────────────────

@router.get("/api/books")
def list_books():
    """扫描 data/ 下所有 book.json，返回书列表。

    F3 (P8-M3R-fix):响应 schema 从 list 改为 dict `{"books": [...], "count": N}`,
    与 REST 约定一致(B3 transcript §Step 1 暴露 `'list' object has no attribute 'get'`)。

    每本书对象包含:
    - name / title / genre(原 book.json 字段)
    - last_chapter / last_written_chapter：有正文的最大章号，正式稿与候选稿都算
    - finalized_count：已有正式正文的章数
    standalone Web 审读已摘除，列表不再扫描或暴露其历史字段。
    """
    data_root = _config.get_data_root()
    books = []
    roots = [data_root]
    second = _config.get_data_root_2()
    if second is not None:
        roots.append(second)

    for root in roots:
        rr = root.resolve()
        root_label = "生产根" if rr == data_root.resolve() else f"开发根·{root.name}"
        for d in sorted(rr.iterdir()):
            if d.is_dir() and (d / "book.json").exists():
                try:
                    meta = json.loads((d / "book.json").read_text(encoding="utf-8"))
                    book = {"name": d.name, **meta}
                except Exception:
                    book = {"name": d.name}

                # P8-M3-pre T0.1 + B 事实表:测试书收折叠区,book.json 无 kind 时默认 test
                book.setdefault("kind", "test")

                # P8-M3R R1 slug ID:确保 id 字段存在,无则回退目录名(过渡期兼容)
                if not book.get("id"):
                    book["id"] = d.name

                # L-1：书架把作者进度与系统定稿数分开显示。
                # L-1 统一口径：已写到 = 正式稿与候选稿并集的最大章号。
                official_nums = _chapter_nums(d / "chapters")
                pending_nums = _chapter_nums(d / "chapters" / "_pending")
                written_nums = official_nums | pending_nums
                book["last_written_chapter"] = max(written_nums) if written_nums else None
                book["last_chapter"] = book["last_written_chapter"]
                book["finalized_count"] = len(official_nums)
                from biyu.ui.settings import settings_completion

                book.update(settings_completion(d))
                # I-1 双根标注:纯文字
                book["root"] = root_label
                books.append(book)
    # F3: dict schema(返 {books, count},与 REST 约定一致)
    return {"books": books, "count": len(books)}


def _chapter_nums(dir_path: Path) -> set[int]:
    """Chapter numbers with a body in one directory; helpers ignore nested dirs."""
    if not dir_path.is_dir():
        return set()
    numbers: set[int] = set()
    for path in dir_path.glob("ch*.md"):
        try:
            numbers.add(int(path.stem.removeprefix("ch")))
        except ValueError:
            continue
    return numbers


@router.post("/api/books")
def create_book(payload: dict):
    """新建书（调用 init_command 核心逻辑）。"""
    title = payload.get("title")
    genre = payload.get("genre", "xuanhuan")
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    try:
        from biyu.book_service import create_book

        created = create_book(str(title), str(genre), data_root=get_data_root())
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "name": created.book_dir.name, "id": created.book_id}


# ── 章节列表 ────────────────────────────────────────────────────────────────

@router.get("/api/books/{book}/chapters")
def list_chapters(book: str):
    """返回章节列表（含大纲、正文状态）。"""
    bd = _book_dir(book)
    bk = BookConfig(bd)
    chapters = []

    # 扫描大纲和正文
    outline_nums = set()
    for p in sorted(bk.outlines_dir.glob("ch*.md")):
        try:
            n = int(p.stem.replace("ch", ""))
            outline_nums.add(n)
        except ValueError:
            pass

    content_nums = set()
    for p in sorted(bk.chapters_dir.glob("ch*.md")):
        try:
            n = int(p.stem.replace("ch", ""))
            content_nums.add(n)
        except ValueError:
            pass

    all_nums = sorted(outline_nums | content_nums)
    for n in all_nums:
        # 读取 meta.json
        meta_path = bk.chapter_log_dir(n) / "meta.json"
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        chapters.append({
            "chapter": n,
            "has_outline": n in outline_nums,
            "has_content": n in content_nums,
            **meta,
        })

    return chapters


# ── 大纲读写 ────────────────────────────────────────────────────────────────

@router.get("/api/books/{book}/chapters/{n}/outline")
def get_outline(book: str, n: int):
    bd = _book_dir(book)
    bk = BookConfig(bd)
    path = bk.outline_path(n)
    if not path.exists():
        raise HTTPException(status_code=404, detail="outline not found")
    return {"chapter": n, "content": path.read_text(encoding="utf-8")}


@router.put("/api/books/{book}/chapters/{n}/outline")
def put_outline(book: str, n: int, payload: dict):
    bd = _book_dir(book)
    bk = BookConfig(bd)
    bk.outlines_dir.mkdir(parents=True, exist_ok=True)
    path = bk.outline_path(n)
    sync_outline_version(bd, n)
    if path.exists():
        save_outline_version(bd, n, path.read_text(encoding="utf-8"))
    path.write_text(payload.get("content", ""), encoding="utf-8")
    save_outline_version(bd, n, path.read_text(encoding="utf-8"))
    return {"status": "ok"}


# ── 生成章节 (SSE) ─────────────────────────────────────────────────────────

@router.post("/api/books/{book}/chapters/{n}/generate")
async def generate_chapter_api(book: str, n: int):
    """生成单章，SSE 推送进度。"""
    bd = _book_dir(book)

    queue = asyncio.Queue()

    async def _run():
        from biyu.pipeline import generate_chapter

        def on_progress(stage: str, msg: str):
            queue.put_nowait(make_event("progress", chapter=n, stage=stage, message=msg))

        on_progress("start", f"开始生成第 {n} 章")
        try:
            result = await generate_chapter(bd, n)
            queue.put_nowait(make_event(
                "done", chapter=n, word_count=result.word_count,
                cost_cny=result.cost_cny, warnings=result.warnings,
            ))
        except Exception as e:
            queue.put_nowait(make_event("error", chapter=n, error=str(e)))
        finally:
            queue.put_nowait(None)

    asyncio.create_task(_run())
    return StreamingResponse(sse_generator(queue), media_type="text/event-stream")


# ── 正文 ─────────────────────────────────────────────────────────────────────

@router.get("/api/books/{book}/chapters/{n}/content")
def get_content(book: str, n: int):
    bd = _book_dir(book)
    bk = BookConfig(bd)
    path = bk.chapter_path(n)
    if not path.exists():
        raise HTTPException(status_code=404, detail="content not found")
    return {"chapter": n, "content": path.read_text(encoding="utf-8")}


# ── 一致性检查 ──────────────────────────────────────────────────────────────

@router.post("/api/books/{book}/chapters/{n}/check")
def check_chapter_api(book: str, n: int):
    bd = _book_dir(book)
    from biyu.db import init_db, sync_characters_from_yaml
    init_db(bd)
    sync_characters_from_yaml(bd)
    from biyu.consistency import check_chapter
    issues = check_chapter(bd, n)
    return {
        "chapter": n,
        "issues": [
            {"rule": i.rule, "severity": i.severity, "character": i.character,
             "location": i.location, "suggestion": i.suggestion}
            for i in issues
        ],
    }


# ── 刷新设定 ────────────────────────────────────────────────────────────────

@router.post("/api/books/{book}/chapters/{n}/refresh")
async def refresh_chapter_api(book: str, n: int):
    bd = _book_dir(book)
    from biyu.refresh import refresh_chapter
    from biyu.config import get_registry

    registry = get_registry()
    observer_alias = registry.get_pipeline_config().get("writer", "v3")
    adapter = registry.get_adapter_for_stage("writer", override=observer_alias)

    ok = refresh_chapter(bd, n, adapter)
    return {"chapter": n, "success": ok}


# ── 成本汇总 ────────────────────────────────────────────────────────────────

@router.get("/api/books/{book}/cost")
def get_cost(book: str):
    bd = _book_dir(book)
    bk = BookConfig(bd)
    cost_path = bk.cost_log_path
    if not cost_path.exists():
        return {"total": 0, "entries": []}

    import csv
    entries = []
    total = 0.0
    with open(cost_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cost = float(row.get("cost_cny", 0))
            total += cost
            entries.append(row)

    return {"total": round(total, 4), "entries": entries}


# ── 角色 yaml ───────────────────────────────────────────────────────────────

@router.get("/api/books/{book}/characters")
def get_characters(book: str):
    bd = _book_dir(book)
    chars = load_characters_yaml(bd)
    return {"characters": chars}


@router.put("/api/books/{book}/characters")
def put_characters(book: str, payload: dict):
    bd = _book_dir(book)
    from biyu.setup_asset_versions import SetupAssetYamlError, update_characters_list
    try:
        update_characters_list(bd, payload.get("characters"), reason="web_put")
    except SetupAssetYamlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 重新同步 SQLite
    from biyu.db import init_db, sync_characters_from_yaml
    init_db(bd)
    sync_characters_from_yaml(bd)
    return {"status": "ok"}


# ── 真相文件 ────────────────────────────────────────────────────────────────

@router.get("/api/books/{book}/truth_files")
def get_truth_files(book: str):
    bd = _book_dir(book)
    return read_all_truth_files(bd)


# ── 建档状态(P8-M3R R2 D-96 无档案提示)─────────────────────────────────────

@router.get("/api/books/{book}/archive-status")
def get_archive_status(book: str):
    """返回书的建档状态:has_truth_files / has_outlines / has_chapters。

    前端(编辑部顶部)据此判断是否显"本书未建档,建议先倒灌"提示。
    D-96:不静默降级。
    """
    bd = _book_dir(book)
    truth_dir = bd / "truth_files"
    outlines_dir = bd / "outlines"
    chapters_dir = bd / "chapters"
    return {
        "has_truth_files": truth_dir.exists() and any(truth_dir.glob("*.md")),
        "has_outlines": outlines_dir.exists() and any(outlines_dir.glob("*.md")),
        "has_chapters": chapters_dir.exists() and any(chapters_dir.glob("*.md")),
    }


# ── 批量生成 (SSE) ─────────────────────────────────────────────────────────

@router.post("/api/books/{book}/auto")
async def auto_generate_api(book: str, payload: dict):
    """批量生成，SSE 推送每章进度。"""
    bd = _book_dir(book)
    from_ch = payload.get("from")
    to_ch = payload.get("to")
    if from_ch is None or to_ch is None:
        raise HTTPException(status_code=400, detail="from and to are required")

    queue = asyncio.Queue()

    async def _run():
        from biyu.auto import auto_generate

        def on_progress(ch_num, done, result):
            queue.put_nowait(make_event(
                "chapter_done", chapter=ch_num, done=done,
                word_count=result.word_count, cost_cny=result.cost_cny,
            ))

        try:
            results = await auto_generate(bd, from_ch, to_ch, on_progress=on_progress)
            total_cost = sum(r.cost_cny for r in results)
            queue.put_nowait(make_event(
                "all_done", total=len(results), total_cost=total_cost,
            ))
        except Exception as e:
            queue.put_nowait(make_event("error", error=str(e)))
        finally:
            queue.put_nowait(None)

    asyncio.create_task(_run())
    return StreamingResponse(sse_generator(queue), media_type="text/event-stream")


# ── 回退 ─────────────────────────────────────────────────────────────────────

@router.post("/api/books/{book}/rollback")
def rollback_api(book: str, payload: dict):
    bd = _book_dir(book)
    to_ch = payload.get("to_chapter")
    if to_ch is None:
        raise HTTPException(status_code=400, detail="to_chapter is required")

    from biyu.refresh import rollback_to_chapter
    ok = rollback_to_chapter(bd, to_ch)
    return {"success": ok, "to_chapter": to_ch}


# ── P8-M2:Editor standalone 审读 + 建记忆估算 ──────────────────────────────

# 建记忆(刷新全章 truth_files)的成本估算常量。
# 来源:T2 ch1 实测 ¥0.0083/章;B3 盘点 ¥0.001-0.003/章是更低保守下限。
# 实际章节字数/复杂度会让成本在此区间内浮动。
_REFRESH_PER_CHAPTER_LOW = 0.005   # 实测下限(短章 / 重复内容)
_REFRESH_PER_CHAPTER_HIGH = 0.02   # 实测上限(长章 / 新增大量钩子)


@router.get("/api/books/{book}/refresh-estimate")
def get_refresh_estimate(book: str):
    """估算"建记忆"(刷新全章 truth_files)的成本。

    按章节计数 × 每章成本区间(¥0.005-0.02,来源 T2 ch1 实测 + B3 盘点)。
    前端"建记忆"按钮显示前调用,让作者看到估算再决定是否触发。
    """
    bd = _book_dir(book)
    bk = BookConfig(bd)
    chapters = list(bk.chapters_dir.glob("ch*.md"))
    # 只算文件名 chN.md 的(过滤 _pending 之类)
    chapter_count = 0
    for p in chapters:
        try:
            n = int(p.stem.replace("ch", ""))
            if n > 0:
                chapter_count += 1
        except ValueError:
            continue

    return {
        "chapter_count": chapter_count,
        "per_chapter_low": _REFRESH_PER_CHAPTER_LOW,
        "per_chapter_high": _REFRESH_PER_CHAPTER_HIGH,
        "total_low": round(chapter_count * _REFRESH_PER_CHAPTER_LOW, 4),
        "total_high": round(chapter_count * _REFRESH_PER_CHAPTER_HIGH, 4),
    }
