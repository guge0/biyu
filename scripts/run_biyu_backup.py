"""Run one scheduled Biyu backup without exposing credentials."""
from __future__ import annotations

from pathlib import Path

from biyu.backup_service import load_backup_settings, run_backup
from biyu.config import get_data_root
from biyu.secure_config import user_config_dir


def main() -> int:
    settings = load_backup_settings()
    if not settings.enabled:
        return 0
    source = get_data_root()
    destination = Path(settings.destination)
    run_backup(source, destination, scope="production", reason="scheduled", status_dir=user_config_dir())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
