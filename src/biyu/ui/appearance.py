"""S-1 外观系统：UI 偏好（主题/令牌覆盖/背景图）持久化与背景图上传。

- 偏好存用户级配置目录 ui.json（循 backup.json 先例），损坏时回落默认。
- 背景图存数据根 ui-backgrounds/，仅收 PNG/JPEG/WebP（魔数校验），设置里只存文件名。
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from biyu.config import get_data_root
from biyu.secure_config import user_config_dir

router = APIRouter(prefix="/api/ui", tags=["appearance"])

SAFE_TOKENS = ("--paper", "--surface", "--ink", "--mark", "--mark-bg")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_BG_PRESETS = ("xuan", "mist", "bamboo")
_BG_TYPES = ("none", "preset", "custom")
_SAVED_FILE_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|jpeg|webp)$")

_OVERLAY_MIN, _OVERLAY_MAX = 65, 98
_BLUR_MIN, _BLUR_MAX = 0, 20
# S-10 3g·工单第2条：玻璃个性化两字段（雾面浓度乘数 % / 卡片透明度），缺字段回默认值不报错
_MIST_MIN, _MIST_MAX = 0, 200
_GLASS_MIN, _GLASS_MAX = 0.20, 0.90
_MIST_DEFAULT, _GLASS_DEFAULT = 100, 0.38
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024

_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class BackgroundPrefs(BaseModel):
    type: str = "none"
    preset: str | None = None
    file: str | None = None
    overlay: float = 90
    blur: float = 0
    mist: float = _MIST_DEFAULT
    glass: float = _GLASS_DEFAULT


class UiPrefs(BaseModel):
    theme: str = "default"
    custom: dict[str, str] | None = None
    background: BackgroundPrefs = BackgroundPrefs()


class BackgroundUpload(BaseModel):
    name: str = ""
    data: str


def _prefs_path() -> Path:
    return user_config_dir() / "ui.json"


def _default_prefs() -> dict[str, Any]:
    return {
        "theme": "default",
        "custom": None,
        "background": {
            "type": "none",
            "preset": None,
            "file": None,
            "overlay": 90,
            "blur": 0,
            "mist": _MIST_DEFAULT,
            "glass": _GLASS_DEFAULT,
        },
    }


def _clamp(value: float, low: float, high: float, fallback: float) -> float:
    """夹取范围；解析不了（缺键/类型错）回落 fallback（各字段默认值）。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


def _sanitize_custom(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    cleaned = {
        token: value
        for token, value in raw.items()
        if token in SAFE_TOKENS and isinstance(value, str) and _COLOR_RE.match(value)
    }
    return cleaned or None


def _sanitize_background(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return _default_prefs()["background"]
    bg_type = raw.get("type") if raw.get("type") in _BG_TYPES else "none"
    preset = raw.get("preset") if raw.get("preset") in _BG_PRESETS else None
    file_name = raw.get("file")
    if not isinstance(file_name, str) or not _SAVED_FILE_RE.match(file_name):
        file_name = None
    if bg_type == "custom" and file_name is None:
        bg_type = "none"
    if bg_type == "preset" and preset is None:
        bg_type = "none"
    return {
        "type": bg_type,
        "preset": preset,
        "file": file_name,
        "overlay": _clamp(raw.get("overlay", 90), _OVERLAY_MIN, _OVERLAY_MAX, 90),
        "blur": _clamp(raw.get("blur", 0), _BLUR_MIN, _BLUR_MAX, 0),
        "mist": _clamp(raw.get("mist", _MIST_DEFAULT), _MIST_MIN, _MIST_MAX, _MIST_DEFAULT),
        "glass": _clamp(raw.get("glass", _GLASS_DEFAULT), _GLASS_MIN, _GLASS_MAX, _GLASS_DEFAULT),
    }


def load_ui_prefs() -> dict[str, Any]:
    try:
        raw = json.loads(_prefs_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _default_prefs()
    if not isinstance(raw, dict):
        return _default_prefs()
    background = _sanitize_background(raw.get("background"))
    if background["type"] == "custom" and background["file"]:
        if not (_background_dir() / background["file"]).is_file():
            background = _default_prefs()["background"]
    return {
        "theme": raw.get("theme") if isinstance(raw.get("theme"), str) else "default",
        "custom": _sanitize_custom(raw.get("custom")),
        "background": background,
    }


def save_ui_prefs(payload: dict[str, Any]) -> None:
    path = _prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _background_dir() -> Path:
    return get_data_root() / "ui-backgrounds"


def _sniff_image_ext(payload: bytes) -> str | None:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if payload.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return ".webp"
    return None


@router.get("/prefs")
def get_prefs() -> dict[str, Any]:
    return load_ui_prefs()


@router.put("/prefs")
def put_prefs(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = {
        "theme": payload.get("theme") if isinstance(payload.get("theme"), str) else "default",
        "custom": _sanitize_custom(payload.get("custom")),
        "background": _sanitize_background(payload.get("background")),
    }
    save_ui_prefs(sanitized)
    return sanitized


@router.post("/background")
def upload_background(payload: BackgroundUpload) -> dict[str, str]:
    import base64
    import binascii

    try:
        raw = base64.b64decode(payload.data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="背景图数据无法解码，仅支持图片")
    if not raw:
        raise HTTPException(status_code=400, detail="背景图内容为空，仅支持图片")
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="背景图过大（上限 20MB）")
    ext = _sniff_image_ext(raw)
    if ext is None:
        raise HTTPException(status_code=400, detail="仅支持图片（PNG / JPG / WebP）")
    saved_name = uuid.uuid4().hex + ext
    target = _background_dir()
    target.mkdir(parents=True, exist_ok=True)
    (target / saved_name).write_bytes(raw)
    return {"file": saved_name, "url": f"/api/ui/background-file/{saved_name}"}


@router.get("/background-file/{name}")
def get_background_file(name: str) -> Response:
    if not _SAVED_FILE_RE.match(name):
        raise HTTPException(status_code=404, detail="背景图不存在")
    path = _background_dir() / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="背景图不存在")
    media_type = _MEDIA_TYPES[path.suffix.lower()]
    return Response(content=path.read_bytes(), media_type=media_type)
