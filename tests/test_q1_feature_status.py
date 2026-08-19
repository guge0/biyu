from pathlib import Path
import subprocess
import sys


def test_feature_status_only_prints_boolean(tmp_path: Path) -> None:
    config = tmp_path / "models.yaml"
    config.write_text(
        "models: {}\nfeatures:\n  injection_v2: true\n",
        encoding="utf-8",
    )
    script = (
        "from pathlib import Path; "
        "import biyu.config as c; "
        f"c.get_config_path=lambda: Path({str(config)!r}); "
        "import biyu.cli.feature_status as f; "
        "import sys; sys.argv=['feature_status','injection_v2']; f.main()"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == "true\n"
    assert "models" not in result.stdout
