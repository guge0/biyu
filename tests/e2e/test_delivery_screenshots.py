from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.e2e


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_data_root_backup_delete_and_landing_delivery_screenshots(page) -> None:
    base_url = os.environ["BIYU_QA_BASE_URL"]
    config_dir = Path(os.environ["BIYU_QA_CONFIG_DIR"])
    output_dir = Path(os.environ["BIYU_QA_SCREENSHOT_DIR"])
    landing = Path(os.environ["BIYU_QA_LANDING_PAGE"])
    backup_dir = Path(os.environ["BIYU_QA_BACKUP_DIR"])
    output_dir.mkdir(parents=True, exist_ok=True)
    page.set_viewport_size({"width": 1600, "height": 1000})

    settings_path = config_dir / "backup.json"
    status_path = config_dir / "backup-status-test.json"

    def settings(enabled: bool) -> None:
        _write_json(settings_path, {
            "schema_version": 1,
            "enabled": enabled,
            "destination": str(backup_dir),
            "source_path": r"C:\stale-must-not-be-used",
            "schedule_state": "test",
            "schedule_error": None,
        })

    def status(state: str, **overrides: object) -> None:
        payload: dict[str, object] = {
            "scope": "test",
            "configured": True,
            "writable": True,
            "last_backup_at": None,
            "last_backup_path": None,
            "state": state,
            "message": "还没备过",
            "book_count": 0,
            "copied_files": 0,
            "duration_seconds": None,
            "last_attempt_at": None,
            "last_error": None,
            "running_started_at": None,
        }
        payload.update(overrides)
        _write_json(status_path, payload)

    def open_home() -> None:
        page.goto(base_url + "/")
        page.wait_for_load_state("networkidle", timeout=10_000)
        page.locator("#data-root-location").wait_for(state="visible", timeout=5_000)

    def open_backup_panel() -> None:
        page.locator("#backup-settings-button").click()
        page.locator("#backup-panel").wait_for(state="visible", timeout=5_000)
        page.wait_for_timeout(400)

    def close_backup_panel() -> None:
        page.locator("#backup-close").click()

    settings(False)
    status("never")
    open_home()
    assert "biyu-dev" not in page.locator("body").inner_text()
    assert "biyu-order-20260822-qa" in page.locator("#data-root-location").inner_text()
    assert "77251888" in page.locator("#version-label").inner_text()
    page.screenshot(path=str(output_dir / "01_书架显示数据根_1600x1000.png"), full_page=True)

    open_backup_panel()
    page.screenshot(path=str(output_dir / "03a_备份没开_1600x1000.png"), full_page=True)
    close_backup_panel()

    settings(True)
    status("never")
    open_home()
    open_backup_panel()
    page.screenshot(path=str(output_dir / "03b_备份已开未备过_1600x1000.png"), full_page=True)
    close_backup_panel()

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    success_path = backup_dir / "test" / "20260822-120000-000000"
    settings(True)
    status(
        "ok",
        message=f"备份完成：1 本 · {success_path} · 用时 0.321 秒",
        last_backup_at=now,
        last_backup_path=str(success_path),
        book_count=1,
        copied_files=2,
        duration_seconds=0.321,
        last_attempt_at=now,
    )
    open_home()
    open_backup_panel()
    assert str(success_path) in page.locator("#backup-detail").inner_text()
    page.screenshot(path=str(output_dir / "03c_备份成功_1600x1000.png"), full_page=True)
    close_backup_panel()

    status("running", message="正在备份…", running_started_at=now, last_attempt_at=now)
    open_home()
    open_backup_panel()
    assert "正在备份" in page.locator("#backup-detail").inner_text()
    page.screenshot(path=str(output_dir / "03d_正在备份_1600x1000.png"), full_page=True)
    close_backup_panel()

    status(
        "failed",
        message="备份失败：磁盘空间不足",
        last_backup_at=now,
        last_backup_path=str(success_path),
        book_count=1,
        copied_files=2,
        duration_seconds=0.321,
        last_attempt_at=now,
        last_error="磁盘空间不足",
    )
    open_home()
    open_backup_panel()
    failure_text = page.locator("#backup-detail").inner_text()
    assert "磁盘空间不足" in failure_text and str(success_path) in failure_text
    page.screenshot(path=str(output_dir / "03e_上次失败且保留成功记录_1600x1000.png"), full_page=True)
    close_backup_panel()

    status(
        "needs_attention",
        message="这次备份没有备到任何书，请检查数据位置。",
        last_attempt_at=now,
    )
    open_home()
    open_backup_panel()
    zero_text = page.locator("#backup-detail").inner_text()
    assert zero_text.startswith("这次备份没有备到任何书，请检查数据位置。")
    assert page.locator("#backup-detail").get_attribute("role") == "alert"
    page.screenshot(path=str(output_dir / "04_备到0本需要检查_1600x1000.png"), full_page=True)
    close_backup_panel()

    card = page.locator("#book-list .book-card").filter(has_text="验收空书")
    card.locator(".book-more-toggle").click()
    card.get_by_role("button", name="移到回收站").click()
    page.locator("#trash-book-overlay").wait_for(state="visible", timeout=5_000)
    page.wait_for_timeout(400)
    assert "0 章正式稿、0 格设定" in page.locator("#trash-book-counts").inner_text()
    page.screenshot(path=str(output_dir / "05a_删书确认条_1600x1000.png"), full_page=True)
    page.locator("#trash-book-confirm").click()
    page.locator("#empty-shelf").wait_for(state="visible", timeout=5_000)
    page.screenshot(path=str(output_dir / "05b_空书已移到回收站_1600x1000.png"), full_page=True)

    page.goto(base_url + "/trash.html")
    page.wait_for_load_state("networkidle", timeout=10_000)
    body = page.locator("body").inner_text()
    assert "验收空书" in body
    assert "保留 30 天" not in body and "到期" not in body
    page.screenshot(path=str(output_dir / "06_回收站无到期日_1600x1000.png"), full_page=True)

    trash_items = page.request.get(base_url + "/api/trash/books").json()
    assert len(trash_items) == 1
    restored = page.request.post(
        base_url + f"/api/trash/books/{trash_items[0]['trash_id']}/restore",
        data={"actor": "author"},
    )
    assert restored.ok

    page.goto(landing.resolve().as_uri())
    page.wait_for_load_state("domcontentloaded", timeout=10_000)
    assert page.locator("h1").inner_text() == "笔驭"
    page.locator(".hero .rise.in").first.wait_for(state="visible", timeout=5_000)
    page.wait_for_timeout(800)
    page.screenshot(path=str(output_dir / "07_仓内宣传页_1600x1000.png"), full_page=False)


def test_about_entry_keeps_shelf_home_and_responsive_product_navigation(page, base_url) -> None:
    base_url = os.environ.get("BIYU_QA_BASE_URL", base_url)
    output_dir = Path(os.environ["BIYU_QA_SCREENSHOT_DIR"])
    output_dir.mkdir(parents=True, exist_ok=True)

    page.set_viewport_size({"width": 1600, "height": 1000})
    page.goto(base_url + "/")
    page.wait_for_load_state("networkidle", timeout=10_000)
    assert page.locator("h1").inner_text() == "书架"
    page.screenshot(path=str(output_dir / "08_启动后仍是书架_1600x1000.png"), full_page=True)

    page.get_by_role("link", name="介绍").click()
    page.wait_for_url(base_url + "/about.html")
    assert page.locator('[aria-current="page"]').inner_text() == "介绍"
    frame = page.frame_locator('iframe[title="笔驭介绍"]')
    frame.locator("h1").wait_for(state="visible", timeout=5_000)
    frame.locator(".hero .rise.in").first.wait_for(state="visible", timeout=5_000)
    page.wait_for_timeout(900)
    page.screenshot(path=str(output_dir / "09_产品内介绍页_1600x1000.png"), full_page=True)

    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(200)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    assert frame.locator("body").evaluate("el => el.scrollWidth <= el.clientWidth")
