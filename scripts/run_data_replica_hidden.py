"""Launch the data-replica PowerShell command without allocating a console."""

from __future__ import annotations

import subprocess
import sys


def run_hidden(argv: list[str]) -> int:
    if not argv:
        return 2
    try:
        completed = subprocess.run(
            argv,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError:
        return 127
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(run_hidden(sys.argv[1:]))
