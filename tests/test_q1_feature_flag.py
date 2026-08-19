from pathlib import Path

from biyu.llm import ModelRegistry


def test_controlled_example_keeps_injection_v2_off() -> None:
    example = Path("config/models.yaml.example").read_text(encoding="utf-8")

    assert "  injection_v2: false" in example


def test_registry_defaults_missing_injection_v2_to_off(tmp_path: Path) -> None:
    config = tmp_path / "models.yaml"
    config.write_text("models: {}\nfeatures: {}\n", encoding="utf-8")

    assert ModelRegistry(config).get_feature("injection_v2") is False


def test_registry_reads_injection_v2_as_one_group_switch(tmp_path: Path) -> None:
    config = tmp_path / "models.yaml"
    config.write_text(
        "models: {}\nfeatures:\n  injection_v2: true\n",
        encoding="utf-8",
    )

    assert ModelRegistry(config).get_feature("injection_v2") is True
