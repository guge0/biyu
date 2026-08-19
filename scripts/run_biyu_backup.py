"""Run one scheduled Biyu backup without exposing credentials."""
from __future__ import annotations

import os
from pathlib import Path

from biyu.backup_service import run_backup
from biyu.config import get_data_root


def main() -> int:
    scope = "test" if os.environ.get("BIYU_RUNTIME_ROLE") == "test" else "production"
    source = Path(os.environ.get("BIYU_DATA_ROOT", str(get_data_root())))
    destination = Path(os.environ.get("BIYU_BACKUP_ROOT", r"D:\BiyuBackup"))
    run_backup(source, destination, scope=scope, reason="scheduled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
