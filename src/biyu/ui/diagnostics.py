"""S-7b：一键导出诊断包（给内测反馈用）。

白名单收集：版本与系统信息、脱敏配置、花费账、各章运行日志尾部。
**绝不包含** Key 明文与书稿正文（章节、细纲、方案、设定、人物卡都不收）。
"""
from __future__ import annotations

import io
import json
import platform
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])

_SECRET_KEY = re.compile(r"(api_?key|token|secret|password|passwd|authorization)", re.I)
# 日志里出现的疑似 Key（sk-xxxx、长 hex/base64 串）一律打码
_SECRET_VALUE = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|[A-Za-z0-9_\-]{32,}\.[A-Za-z0-9_\-]{8,}|[A-Fa-f0-9]{32,})")
_RUN_LOG_TAIL = 200


def _redact_value(value: Any) -> str:
    return "***已配置***" if str(value or "").strip() else "未配置"


def redact_config(node: Any) -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if _SECRET_KEY.search(str(key)) and not isinstance(value, (dict, list)):
                out[key] = _redact_value(value)
            else:
                out[key] = redact_config(value)
        return out
    if isinstance(node, list):
        return [redact_config(item) for item in node]
    return node


def scrub_text(text: str) -> str:
    return _SECRET_VALUE.sub("***", text)


# 运行日志只留「阶段/状态/报错」结构行；核对行只留到冒号前（冒号后会带人名等作者内容）。
_KEEP_LINE = re.compile(
    r"^\s*(\[\d/\d\]|\[(Editor|Auditor|F-4|git|audit_report|dash_fixer|wenyan_fixer|grammar_check)\]|"
    r"argv=|run_id=|action=|started_at=|status=|returncode=|---|开始生成|Prompt版本|本章篇幅|构建上下文|"
    r"Traceback|\w*(Error|Exception)\b|.*(错误|失败|异常|超时|余额|401|402|429))"
)
_CHECK_LINE = re.compile(r"^(\s*\[(PASS|FAIL|SKIP|WARN)\]\s*[\w\-]+)")


def filter_run_log(lines: list[str]) -> list[str]:
    kept: list[str] = []
    for line in lines:
        check = _CHECK_LINE.match(line)
        if check:
            kept.append(check.group(1))
        elif _KEEP_LINE.match(line):
            kept.append(line[:300])
    return kept


def _system_info(data_root: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "data_root": str(data_root),
    }
    try:
        from biyu import __version__ as biyu_version  # type: ignore[attr-defined]

        info["biyu_version"] = biyu_version
    except Exception:
        pass
    try:
        from biyu.licensing import status as license_status

        info["license"] = license_status()
    except Exception:
        pass
    return info


def _book_dirs(data_root: Path) -> list[Path]:
    if not data_root.is_dir():
        return []
    return sorted(p for p in data_root.iterdir() if p.is_dir() and (p / "logs").is_dir())


def build_diagnostics_zip(data_root: Path, config_path: Path | None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("系统信息.json", json.dumps(_system_info(data_root), ensure_ascii=False, indent=2))
        if config_path and config_path.exists():
            try:
                import yaml

                raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                zf.writestr("配置_已脱敏.json", json.dumps(redact_config(raw), ensure_ascii=False, indent=2))
            except Exception as exc:  # 配置坏了本身也是诊断信息
                zf.writestr("配置_读取失败.txt", f"{type(exc).__name__}")
        central = data_root / "cost_log.csv"
        if central.exists():
            zf.writestr("花费/全局_cost_log.csv", central.read_text(encoding="utf-8", errors="replace"))
        for index, book_dir in enumerate(_book_dirs(data_root), 1):
            label = f"书{index:02d}"  # 不用书名做路径，书名也算作者内容
            cost = book_dir / "logs" / "cost_log.csv"
            if cost.exists():
                zf.writestr(f"花费/{label}_cost_log.csv", cost.read_text(encoding="utf-8", errors="replace"))
            for run in sorted((book_dir / "logs").glob("ch*/runs/*.log"))[-20:]:
                lines = filter_run_log(run.read_text(encoding="utf-8", errors="replace").splitlines())[-_RUN_LOG_TAIL:]
                zf.writestr(f"运行日志/{label}_{run.parent.parent.name}_{run.name}", scrub_text("\n".join(lines)))
        zf.writestr(
            "说明.txt",
            "这是笔驭诊断包：只含版本、系统、脱敏配置、花费记录和运行日志尾部；不含任何 Key 和书稿正文。\n"
            "请发到内测 Q 群 892467108。\n",
        )
    return buf.getvalue()


@router.post("/export")
def export_diagnostics() -> dict[str, Any]:
    from biyu.config import get_config_path, get_data_root

    data_root = Path(get_data_root())
    try:
        config_path = Path(get_config_path())
    except Exception:
        config_path = None
    try:
        payload = build_diagnostics_zip(data_root, config_path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"诊断包生成失败：{exc}") from exc
    out_dir = data_root / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"笔驭诊断_{datetime.now():%Y%m%d_%H%M%S}.zip"
    path = out_dir / name
    path.write_bytes(payload)
    return {"ok": True, "path": str(path), "name": name, "download": f"/api/diagnostics/download/{name}"}


@router.get("/download/{name}")
def download_diagnostics(name: str) -> FileResponse:
    from biyu.config import get_data_root

    if "/" in name or "\\" in name or not name.endswith(".zip"):
        raise HTTPException(status_code=400, detail="文件名不合法")
    path = Path(get_data_root()) / "diagnostics" / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="诊断包不存在")
    return FileResponse(path, filename=name, media_type="application/zip")
