"""User-level setup settings and API secrets; secrets never touch the repository."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SERVICE = "biyu"


def user_config_dir() -> Path:
    override = os.environ.get("BIYU_USER_CONFIG_DIR")
    return Path(override) if override else Path.home() / ".biyu"


def _settings_path() -> Path:
    return user_config_dir() / "setup.json"


def load_setup() -> dict[str, Any]:
    try:
        return json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_setup(settings: dict[str, Any]) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = {key: value for key, value in settings.items() if key not in {"api_key", "key", "secret"}}
    path.write_text(json.dumps(safe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fallback_paths() -> tuple[Path, Path]:
    root = user_config_dir()
    return root / "secrets.enc", root / "secret.key"


def _store_encrypted(provider: str, secret: str) -> None:
    from cryptography.fernet import Fernet

    cipher_path, key_path = _fallback_paths()
    cipher_path.parent.mkdir(parents=True, exist_ok=True)
    key = key_path.read_bytes() if key_path.exists() else Fernet.generate_key()
    if not key_path.exists():
        key_path.write_bytes(key)
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
    values: dict[str, str] = {}
    if cipher_path.exists():
        try:
            values = json.loads(Fernet(key).decrypt(cipher_path.read_bytes()).decode("utf-8"))
        except Exception:
            values = {}
    values[provider] = secret
    cipher_path.write_bytes(Fernet(key).encrypt(json.dumps(values).encode("utf-8")))
    try:
        cipher_path.chmod(0o600)
    except OSError:
        pass


def _load_encrypted(provider: str) -> str:
    from cryptography.fernet import Fernet

    cipher_path, key_path = _fallback_paths()
    if not cipher_path.exists() or not key_path.exists():
        return ""
    try:
        values = json.loads(Fernet(key_path.read_bytes()).decrypt(cipher_path.read_bytes()).decode("utf-8"))
    except Exception:
        return ""
    return str(values.get(provider, ""))


def _keyring_enabled() -> bool:
    """测试与仿真实例不碰系统钥匙串(整改清单 #11)。

    S-3C 事故:BIYU_USER_CONFIG_DIR 只隔离了加密文件,钥匙串是全机共享的,
    测试里保存的假 Key 覆盖了作者的真 Key。BIYU_KEYRING_DISABLED=1 或
    BIYU_RUNTIME_ROLE=test 时一律只走 BIYU_USER_CONFIG_DIR 下的加密文件。
    """
    if os.environ.get("BIYU_KEYRING_DISABLED", "").strip() == "1":
        return False
    return os.environ.get("BIYU_RUNTIME_ROLE", "").strip().lower() != "test"


def store_provider_secret(provider: str, secret: str) -> str:
    if not provider or not secret.strip():
        raise ValueError("服务商和 API Key 不能为空")
    if not _keyring_enabled():
        _store_encrypted(provider, secret.strip())
        return "本地加密文件"
    try:
        import keyring

        keyring.set_password(SERVICE, provider, secret.strip())
        return "系统钥匙串"
    except Exception:
        _store_encrypted(provider, secret.strip())
        return "本地加密文件"


def load_provider_secret(provider: str) -> str:
    if not _keyring_enabled():
        return _load_encrypted(provider)
    try:
        import keyring

        value = keyring.get_password(SERVICE, provider)
        if value:
            return value
    except Exception:
        pass
    return _load_encrypted(provider)
