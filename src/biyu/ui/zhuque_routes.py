"""S-6 · 朱雀体检与降分 API — /api/zhuque/*(挂在快检台页面)。

端点(全部离线可测:client/engine/rewriter 都可打桩):
- GET  /status          → {has_key, rewriter:{provider, model, verified, available}}
- POST /key, DELETE /key → 朱雀 Key 存取,沿用现有模型 Key 的安全存放
- POST /check {text}    → 整章判定 + 逐窗分数
- POST /fix {text, terms, estimate_only} → 花钱动作两步走:
                           estimate_only=true 只回预估;确认后建任务返回 job_id
- POST /fix-blind {text, terms, targets} → 网页复核模式建任务(不调朱雀,不需要 Key)
- GET  /jobs/{id}       → 轮询进度与结果(内存任务,同一时间只跑一个,重复提交 409)
- POST /report (multipart: pdf + text)   → 报告 PDF 映射后的逐窗分数

用量按现有 cost_log 方式记账;文本长度上限与现有快检一致(MAX_SCAN_CHARS)。
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from biyu.config import get_config_path
from biyu.llm import ModelRegistry
from biyu.quickcheck import MAX_SCAN_CHARS
from biyu.secure_config import delete_provider_secret, load_provider_secret, store_provider_secret
from biyu.ui.cost_log import write_cost_log
from biyu.ui.model_alias import resolve_ui_adapter
from biyu.zhuque import engine
from biyu.zhuque.client import ZhuqueClient, ZhuqueError
from biyu.zhuque.report_pdf import ReportPdfError, extract_pdf_text, map_scores_to_windows, parse_fragments

logger = logging.getLogger("biyu.ui.zhuque_routes")

router = APIRouter(prefix="/api/zhuque", tags=["zhuque"])

_PROVIDER = "zhuque"
# 朱雀自己的口径:0.5 以上疑似;引擎改写起点留缓冲取 0.45
_DISPLAY_RED = 0.5
_FIXABLE = 0.45
# 预估口径(粗估,给作者一个量级):每红窗约 6 次回译(每次 2 调)+顺稿 2 调;
# 朱雀按每次测分≈窗长 token + 整章复测若干遍估
_EST_GENERATES_PER_RED = 14
_EST_FALLBACK_PER_CALL = 0.005  # 改写模型没配单价时的保守单次调用价(元)


# ---------------------------------------------------------------------------
# 改写模型解析:优先 GLM(glm-5.2);没配 GLM 回落作者当前选的聊天模型(verified=False)
# ---------------------------------------------------------------------------

_PROVIDER_LABELS = {"glm": "GLM", "deepseek": "DeepSeek", "kimi": "Kimi", "moonshot": "Kimi",
                    "doubao": "豆包", "gemini": "Gemini", "custom": "自定义"}


def _rewriter_info() -> dict[str, Any]:
    """解析改写模型。返回 {available, provider, model, verified, adapter}。"""
    unavailable = {"available": False, "provider": None, "model": None, "verified": False, "adapter": None}
    try:
        registry = ModelRegistry(get_config_path())
    except FileNotFoundError:
        return unavailable
    models = getattr(registry, "_models", {}) or {}

    aliases: list[str] = []
    if "glm-5.2" in models:
        aliases.append("glm-5.2")
    aliases += [
        alias for alias, cfg in models.items()
        if isinstance(cfg, dict) and cfg.get("provider") == "glm"
        and cfg.get("type") != "embedding" and alias != "glm-5.2"
    ]
    for alias in aliases:
        try:
            adapter = registry.get_adapter(alias)
        except (KeyError, ValueError, FileNotFoundError):
            continue
        if getattr(adapter, "api_key", ""):
            model_id = models.get(alias, {}).get("model_id") or getattr(adapter, "model_name", alias)
            # S-6b:只有 glm-5.2(r12 直连实测过文字质量的一档)标已验证,其它 GLM 档一律未验证
            verified = "glm-5.2" in (alias, str(model_id))
            return {"available": True, "provider": "GLM", "model": str(model_id),
                    "verified": verified, "adapter": adapter}

    try:
        adapter, alias = resolve_ui_adapter(registry)
    except (FileNotFoundError, KeyError, ValueError):
        return unavailable
    cfg = models.get(alias) if isinstance(models.get(alias), dict) else {}
    provider = str(cfg.get("provider") or alias)
    model_id = cfg.get("model_id") or getattr(adapter, "model_name", alias)
    return {"available": True, "provider": _PROVIDER_LABELS.get(provider, provider),
            "model": str(model_id), "verified": False, "adapter": adapter}


def _client_or_error() -> ZhuqueClient:
    key = load_provider_secret(_PROVIDER)
    if not key:
        raise HTTPException(status_code=400, detail="还没填朱雀 Key：先在上面填一下，再开始体检。")
    try:
        return ZhuqueClient(key)
    except ZhuqueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _guard_length(text: str) -> None:
    if len(text) > MAX_SCAN_CHARS:
        raise HTTPException(status_code=413, detail=f"文本超过 {MAX_SCAN_CHARS} 字上限，请分段粘贴")


# ---------------------------------------------------------------------------
# 内存任务(同一时间只跑一个)
# ---------------------------------------------------------------------------

_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_RUNNING = False
_LAST_CHECK: dict[str, Any] = {"red": None, "fixable": None, "chars": None}


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "kind": job["kind"],
        "status": job["status"],
        "progress": dict(job["progress"]),
        "result": job["result"],
        "error": job["error"],
    }


def _spawn_job(kind: str, run, model: str = "") -> str:
    """起一个后台线程跑 async 任务;返回 job_id。已有任务在跑时抛 409。"""
    global _RUNNING
    with _JOBS_LOCK:
        if _RUNNING:
            raise HTTPException(
                status_code=409,
                detail="已有一个改写任务在跑：等它完成(下面能看到进度)，或先点「重新开始」放弃当前结果再试。",
            )
        job_id = uuid.uuid4().hex[:12]
        _RUNNING = True
        job: dict[str, Any] = {
            "job_id": job_id, "kind": kind, "status": "running", "model": model,
            "progress": {"phase": "start", "done": 0, "pass": 0, "total": 0},
            "result": None, "error": None, "created": time.time(),
        }
        _JOBS[job_id] = job

    def _on_event(event: dict) -> None:
        progress = job["progress"]
        progress.update({k: v for k, v in event.items() if k != "stage"})
        progress["phase"] = str(event.get("stage") or progress.get("phase"))
        if event.get("stage") == "window" and event.get("state") == "done":
            progress["done"] = int(progress.get("done") or 0) + 1
            if str(event.get("status") or "").startswith("已过线"):
                progress["pass"] = int(progress.get("pass") or 0) + 1

    def _worker() -> None:
        global _RUNNING
        try:
            result = asyncio.run(run(_on_event))
            job["result"] = result
            _log_cost(job_id, result, model)
            job["status"] = "done"
            job["progress"]["phase"] = "done"
        except ZhuqueError as exc:
            job["status"] = "error"
            job["error"] = str(exc)
        except Exception as exc:  # noqa: BLE001 — 任务线程兜底,人话回给作者
            logger.exception("朱雀任务失败(job=%s)", job_id)
            job["status"] = "error"
            job["error"] = f"任务失败：{type(exc).__name__}: {exc}"
        finally:
            with _JOBS_LOCK:
                _RUNNING = False

    threading.Thread(target=_worker, daemon=True, name=f"biyu-zhuque-{kind}").start()
    return job_id


def _log_cost(job_id: str, result: dict[str, Any], model: str) -> None:
    cost = float((result.get("usage") or {}).get("cost_cny") or 0.0)
    if cost <= 0:
        return
    try:
        write_cost_log(task="zhuque", book="快检台", session=job_id, cost=cost, model=model)
    except Exception:
        logger.warning("写 cost_log 失败", exc_info=True)


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


class KeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


class FixRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    terms: list[str] = Field(default_factory=list)
    estimate_only: bool = False


class FixBlindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    terms: list[str] = Field(default_factory=list)
    targets: list[int] | None = None


@router.get("/status")
def zhuque_status() -> dict[str, Any]:
    info = _rewriter_info()
    return {
        "has_key": bool(load_provider_secret(_PROVIDER)),
        "rewriter": {
            "provider": info["provider"],
            "model": info["model"],
            "verified": info["verified"],
            "available": info["available"],
        },
    }


@router.post("/key")
def save_zhuque_key(req: KeyRequest) -> dict[str, Any]:
    key = req.key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="Key 不能为空")
    storage = store_provider_secret(_PROVIDER, key)
    return {"ok": True, "storage": storage}


@router.delete("/key")
def delete_zhuque_key() -> dict[str, Any]:
    removed = delete_provider_secret(_PROVIDER)
    return {"ok": True, "removed": removed}


@router.post("/check")
async def zhuque_check(req: CheckRequest) -> dict[str, Any]:
    _guard_length(req.text)
    client = _client_or_error()
    try:
        windows = await client.windows(req.text)
        verdict = await client.verdict(req.text)
    except ZhuqueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    red = sum(1 for w in windows if w["conf"] >= _DISPLAY_RED)
    fixable = sum(1 for w in windows if w["conf"] >= _FIXABLE)
    _LAST_CHECK.update(red=red, fixable=fixable, chars=len(req.text))
    return {
        "verdict": verdict,
        "windows": windows,
        "red": red,
        "fixable": fixable,
        "used_tokens": client.used_tokens,
    }


def _estimate_fix(text: str) -> dict[str, Any]:
    """粗估一轮自动降分的分钟数、模型费用与朱雀额度(给作者一个量级)。"""
    cached = _LAST_CHECK
    if cached.get("chars") == len(text) and cached.get("fixable"):
        red = int(cached["fixable"])
    else:
        red = max(1, round(len(text) / engine.WINDOW_CHARS * 0.6))
    info = _rewriter_info()
    per_call = 0.0
    model = "改写模型"
    if info["available"]:
        adapter = info["adapter"]
        model = str(info["model"])
        try:
            per_call = float(adapter.estimate_cost(500, 700))  # type: ignore[attr-defined]
        except Exception:
            per_call = 0.0
    if per_call <= 0:
        per_call = _EST_FALLBACK_PER_CALL
    generates = red * _EST_GENERATES_PER_RED + max(1, len(text) // engine.WINDOW_CHARS) * 2
    return {
        "red_windows": red,
        "minutes": round(1 + 1.5 * red, 1),
        "cost_cny": round(generates * per_call, 2),
        "zhuque_tokens": int(red * 8 * engine.WINDOW_CHARS + 6 * len(text)),
        "model": model,
    }


@router.post("/fix")
def zhuque_fix(req: FixRequest) -> dict[str, Any]:
    _guard_length(req.text)
    if req.estimate_only:
        return {"estimate": _estimate_fix(req.text)}
    client = _client_or_error()
    info = _rewriter_info()
    if not info["available"]:
        raise HTTPException(status_code=400, detail="改写模型不可用：请先在书架页右上「换 Key / 换模型」里保存 Key。")
    text, terms = req.text, [t.strip() for t in req.terms if t.strip()]
    adapter, model = info["adapter"], str(info["model"])

    async def _run(on_event):
        return await engine.fix_chapter(text, terms, adapter=adapter, scorer=client, on_event=on_event)

    job_id = _spawn_job("fix", _run, model)
    return {"job_id": job_id}


@router.post("/fix-blind")
def zhuque_fix_blind(req: FixBlindRequest) -> dict[str, Any]:
    _guard_length(req.text)
    info = _rewriter_info()
    if not info["available"]:
        raise HTTPException(status_code=400, detail="改写模型不可用：请先在书架页右上「换 Key / 换模型」里保存 Key。")
    text = req.text
    terms = [t.strip() for t in req.terms if t.strip()]
    targets = req.targets
    adapter, model = info["adapter"], str(info["model"])

    async def _run(on_event):
        return await engine.fix_blind(text, terms, targets, adapter=adapter, on_event=on_event)

    job_id = _spawn_job("fix-blind", _run, model)
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
def get_zhuque_job(job_id: str) -> dict[str, Any]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在(可能服务重启过)：请重新开始。")
    return _public_job(job)


@router.post("/report")
async def zhuque_report(pdf: UploadFile = File(...), text: str = Form(...)) -> dict[str, Any]:
    _guard_length(text)
    data = await pdf.read()
    try:
        raw = extract_pdf_text(data)
    except ReportPdfError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fragments = parse_fragments(raw)
    if not fragments:
        raise HTTPException(
            status_code=400,
            detail="这份 PDF 里没找到「片段 AIGC值」：请确认拖进来的是朱雀检测报告单(网页版导出的 PDF)。",
        )
    windows = engine.split_windows(text)
    mapped = map_scores_to_windows(fragments, windows)
    out: list[dict[str, Any]] = []
    for w, m in zip(windows, mapped):
        score = m["score"]
        label = None if score is None else ("AI" if score >= 0.99 else "疑似" if score >= _DISPLAY_RED else "人工")
        out.append({**w, "score": score, "label": label, "fragment": m["fragment"]})
    red = sum(1 for w in out if (w["score"] or 0.0) >= _DISPLAY_RED)
    return {"windows": out, "fragments": len(fragments), "red": red}
