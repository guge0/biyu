import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path


def test_replica_script_uses_snapshots_hashes_and_never_writes_source() -> None:
    script = Path("scripts/run_data_replica.ps1").read_text(encoding="utf-8")
    assert "snapshot-" in script
    assert "Get-FileHash" not in script
    assert "SHA256" in script
    assert "Copy-Item -LiteralPath $source" in script
    assert "Remove-Item -LiteralPath $_.Directory.FullName" in script
    assert "^snapshot-(\\d{8}T\\d{6}Z)$" in script
    assert "status.json" in script


def test_replica_keeps_a_bounded_thirty_day_recovery_window() -> None:
    script = Path("scripts/run_data_replica.ps1").read_text(encoding="utf-8")
    workbench = Path("src/biyu/ui/workbench.py").read_text(encoding="utf-8")
    author_ui = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")

    assert "[ValidateRange(24, 168)][int]$HourlyRetentionHours = 72" in script
    assert "[ValidateRange(30, 90)][int]$DailyRetentionDays = 31" in script
    assert 'ToString("yyyyMMddHH")' in script
    assert 'ToString("yyyyMMdd")' in script
    assert "earliest_recovery" in script
    assert "earliest_recovery" in workbench
    assert "最早可恢复到" in author_ui


def test_replica_installer_matches_runner_parameters_and_runs_silently() -> None:
    installer = Path("scripts/install_data_replica_task.ps1").read_text(encoding="utf-8")
    runner = Path("scripts/run_data_replica.ps1").read_text(encoding="utf-8")

    for parameter in ("DestinationRoot", "HourlyRetentionHours", "DailyRetentionDays"):
        assert f"${parameter}" in runner
        assert f"${parameter}" in installer
        assert f"-{parameter}" in installer

    assert "-Retention" not in installer
    assert "-NonInteractive" in installer
    assert "-WindowStyle Hidden" in installer
    assert "New-ScheduledTaskSettingsSet" in installer
    assert "-Hidden" in installer
    assert "('-File \"{0}\"' -f $runner)" in installer
    assert "('-DestinationRoot \"{0}\"' -f $DestinationRoot)" in installer
    assert '$taskArguments = $argumentParts -join " "' in installer


def test_silent_replica_task_keeps_failure_status_visible() -> None:
    installer = Path("scripts/install_data_replica_task.ps1").read_text(encoding="utf-8")
    runner = Path("scripts/run_data_replica.ps1").read_text(encoding="utf-8")

    assert "status.json" in runner
    assert "failed = $true" in runner
    assert "last_error = $_.Exception.Message" in runner
    assert "throw" in runner
    assert "run_data_replica.ps1" in installer


def test_replica_retention_keeps_hourly_and_daily_recovery_points(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "replica"
    source.mkdir()
    destination.mkdir()
    (source / "chapter.md").write_text("fixture", encoding="utf-8")
    now = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(
        minute=30, second=0, microsecond=0,
    )
    timestamps = (
        now - timedelta(hours=2, minutes=20),
        now - timedelta(hours=2, minutes=5),
        now - timedelta(days=10, hours=2),
        now - timedelta(days=10, hours=1),
        now - timedelta(days=30),
        now - timedelta(days=32),
    )
    for timestamp in timestamps:
        (destination / f"snapshot-{timestamp:%Y%m%dT%H%M%SZ}").mkdir()

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(Path("scripts/run_data_replica.ps1").resolve()),
            "-SourcePath",
            str(source),
            "-DestinationRoot",
            str(destination),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    kept = sorted(path.name for path in destination.glob("snapshot-*"))
    assert f"snapshot-{timestamps[0]:%Y%m%dT%H%M%SZ}" not in kept
    assert f"snapshot-{timestamps[1]:%Y%m%dT%H%M%SZ}" in kept
    assert f"snapshot-{timestamps[2]:%Y%m%dT%H%M%SZ}" not in kept
    assert f"snapshot-{timestamps[3]:%Y%m%dT%H%M%SZ}" in kept
    assert f"snapshot-{timestamps[4]:%Y%m%dT%H%M%SZ}" in kept
    assert f"snapshot-{timestamps[5]:%Y%m%dT%H%M%SZ}" not in kept


def test_restore_scripts_require_a_staging_destination() -> None:
    restore = Path("scripts/restore_offsite_chapter.ps1").read_text(encoding="utf-8")
    assert "StagingDirectory" in restore
    assert "staging directory outside data" in restore


def test_author_status_uses_only_replica_language() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    script = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
    author_ui = html + script
    assert 'id="replica-status"' not in html
    assert 'id="reading-more-replica"' in html
    assert "renderReplicaStatus" in script
    for forbidden in ("备份", "已备份", "数据安全"):
        assert forbidden not in author_ui
