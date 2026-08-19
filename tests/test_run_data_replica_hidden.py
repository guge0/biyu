from __future__ import annotations

import subprocess

from scripts.run_data_replica_hidden import run_hidden


def test_run_hidden_uses_create_no_window(monkeypatch):
    seen = {}

    def fake_run(argv, *, check, creationflags):
        seen.update(argv=argv, check=check, creationflags=creationflags)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert run_hidden(["powershell.exe", "-File", "replica.ps1"]) == 0
    assert seen == {
        "argv": ["powershell.exe", "-File", "replica.ps1"],
        "check": False,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


def test_run_hidden_requires_a_command():
    assert run_hidden([]) == 2


def test_run_hidden_returns_launch_failure(monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("cannot launch")

    monkeypatch.setattr(subprocess, "run", fail)

    assert run_hidden(["powershell.exe"]) == 127
