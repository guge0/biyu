import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from biyu.llm import ModelRegistry
from biyu.ui.author_notice_state import (
    acknowledge_replica_warning,
    author_notice_state_path,
    load_author_notice_state,
)
from biyu.ui.app import app
from biyu.ui import workbench
from tests.support.workbench_assets import assert_workbench_js_src


def test_author_notice_state_defaults_to_unacknowledged(tmp_path: Path) -> None:
    state = load_author_notice_state(tmp_path / "author_ui_state.json")

    assert state == {
        "replica_unconfigured_acknowledged": False,
        "load_error": "",
    }


def test_author_notice_state_persists_and_preserves_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "author_ui_state.json"
    path.write_text(
        json.dumps({"future_setting": {"enabled": True}}, ensure_ascii=False),
        encoding="utf-8",
    )

    saved = acknowledge_replica_warning(path)
    reloaded = load_author_notice_state(path)

    assert saved["replica_unconfigured_acknowledged"] is True
    assert reloaded["replica_unconfigured_acknowledged"] is True
    assert json.loads(path.read_text(encoding="utf-8"))["future_setting"] == {
        "enabled": True
    }
    assert list(tmp_path.glob(".author_ui_state.json.*.tmp")) == []


def test_corrupt_author_notice_state_fails_safe_and_speaks(tmp_path: Path) -> None:
    path = tmp_path / "author_ui_state.json"
    path.write_text("{not-json", encoding="utf-8")

    state = load_author_notice_state(path)

    assert state["replica_unconfigured_acknowledged"] is False
    assert state["load_error"] == "界面状态没有读成功，未设置提醒已恢复显示。"


def test_non_boolean_acknowledgement_is_not_trusted(tmp_path: Path) -> None:
    path = tmp_path / "author_ui_state.json"
    path.write_text(
        json.dumps({"replica_unconfigured_acknowledged": "yes"}),
        encoding="utf-8",
    )

    state = load_author_notice_state(path)

    assert state["replica_unconfigured_acknowledged"] is False


def test_author_notice_state_uses_independent_user_config_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(tmp_path))

    assert author_notice_state_path() == tmp_path / "author_ui_state.json"
    assert author_notice_state_path().name != "setup.json"


def test_acknowledgement_endpoint_persists_across_clients_without_llm(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(tmp_path))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Replica acknowledgement must not call a model")

    monkeypatch.setattr(ModelRegistry, "get_adapter", fail_if_called)
    first_client = TestClient(app)
    response = first_client.post("/api/workbench/replica-notice/acknowledge")

    assert response.status_code == 200
    assert response.json()["replica_unconfigured_acknowledged"] is True
    assert (tmp_path / "author_ui_state.json").exists()
    assert not (tmp_path / "setup.json").exists()

    second_client = TestClient(app)
    persisted = second_client.get("/api/workbench/replica-notice")

    assert persisted.status_code == 200
    assert persisted.json()["replica_unconfigured_acknowledged"] is True


def test_acknowledgement_write_failure_is_author_visible(monkeypatch) -> None:
    def fail_write():
        raise OSError("fixture write failure")

    monkeypatch.setattr(workbench, "acknowledge_replica_warning", fail_write)

    response = TestClient(app).post(
        "/api/workbench/replica-notice/acknowledge"
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "没有保存成功，请稍后再试；顶部提醒仍会保留。"


def test_replica_guidance_lives_in_backup_panel_not_workbench() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")
    script = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
    shelf = Path("src/biyu/ui/static/index.html").read_text(encoding="utf-8")

    workbench_ui = html + script
    for forbidden in ("replica-warning", "reading-more-replica", "防手滑副本", "副本尚未设置", "备份"):
        assert forbidden not in workbench_ui
    assert 'id="backup-panel"' in shelf
    assert "它不是防灾措施" in shelf
    assert "机器丢失或损坏时会和原件一起丢失" in shelf


def test_shared_workbench_cache_contract_is_red_on_mismatch_and_green_on_match() -> None:
    html = Path("src/biyu/ui/static/workbench.html").read_text(encoding="utf-8")

    with pytest.raises(AssertionError):
        assert_workbench_js_src(html.replace("workbench.js?v=c2-1", "workbench.js?v=wrong"))

    assert_workbench_js_src(html)


def test_replica_status_defaults_to_sibling_of_active_data_root(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "BiyuData"
    data_root.mkdir()
    replica_root = tmp_path / "biyu-data-replica"
    replica_root.mkdir()
    (replica_root / "status.json").write_text(
        json.dumps({"last_success": "now", "snapshot_count": 2}), encoding="utf-8"
    )
    monkeypatch.setenv("BIYU_DATA_ROOT", str(data_root))
    monkeypatch.delenv("BIYU_REPLICA_ROOT", raising=False)

    status = workbench._replica_status()

    assert status["configured"] is True
    assert status["snapshot_count"] == 2
    assert status["last_success"] == "now"
