(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  let current = null;
  let trigger = null;
  let pollTimer = null;
  let trashResolve = null;

  async function request(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || "操作没有完成，请稍后再试。");
    return body;
  }

  function localTime(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return `${date.getMonth() + 1}月${date.getDate()}日 ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  }

  function duration(value) {
    if (value == null) return "0 秒";
    if (value < 1) return "不到 1 秒";
    return `${Math.round(value)} 秒`;
  }

  function render(status) {
    current = status;
    const line = $("backup-status");
    const detail = $("backup-detail");
    const run = $("backup-run");
    const auto = $("backup-auto");
    const directory = $("backup-directory");
    const choose = $("backup-choose-directory");
    const panel = $("backup-panel");
    if (!line || !detail || !run || !auto || !directory || !choose || !panel) return;

    line.classList.remove("backup-status-failed");
    detail.classList.remove("backup-detail-failed");
    detail.removeAttribute("role");
    detail.setAttribute("role", "status");
    auto.checked = Boolean(status.enabled);
    directory.value = status.destination || "";
    const running = status.state === "running";
    panel.setAttribute("aria-busy", String(running));
    run.disabled = running;
    auto.disabled = running;
    choose.disabled = running;

    if (running) {
      line.textContent = "正在备份…";
      detail.textContent = "正在备份…";
      run.textContent = "正在备份…";
    } else if (status.state === "failed") {
      const when = localTime(status.last_attempt_at);
      line.textContent = `上次备份失败${when ? `（${when}）` : ""} · 去看看`;
      line.classList.add("backup-status-failed");
      detail.textContent = `上次备份失败：${status.last_error || "原因没有记录"}`;
      detail.classList.add("backup-detail-failed");
      detail.setAttribute("role", "alert");
      run.textContent = "再试一次";
    } else if (!status.enabled) {
      line.textContent = "备份没有开 · 打开";
      detail.textContent = status.last_backup_at
        ? `自动备份没有开。上次手动备份 ${localTime(status.last_backup_at)} · ${status.book_count || 0} 本 · 用时 ${duration(status.duration_seconds)}`
        : "备份没有开。仍然可以手动备份一次。";
      run.textContent = "现在备份一次";
    } else if (status.state === "ok" && status.last_backup_at) {
      line.textContent = `上次备份 ${localTime(status.last_backup_at)} · ${status.book_count || 0} 本 · 备份设置`;
      detail.textContent = `上次备份 ${localTime(status.last_backup_at)} · ${status.book_count || 0} 本 · 用时 ${duration(status.duration_seconds)}`;
      run.textContent = "现在备份一次";
    } else {
      line.textContent = "备份已打开，还没备过 · 现在备一次";
      detail.textContent = "还没备过。";
      run.textContent = "现在备份一次";
    }
    if (status.enabled && status.next_backup_at && !running) {
      detail.append(document.createElement("br"), document.createTextNode(`下次备份 ${localTime(status.next_backup_at)}`));
    }
  }

  async function loadStatus() {
    try {
      const status = await request("/api/backup/status");
      render(status);
      return status;
    } catch (error) {
      const line = $("backup-status");
      if (line) line.textContent = "备份状态暂时不可用 · 重试";
      const detail = $("backup-detail");
      if (detail) detail.textContent = error.message;
      return null;
    }
  }

  function openPanel(event) {
    trigger = event?.currentTarget || document.activeElement;
    $("backup-overlay").hidden = false;
    $("backup-panel").focus();
    loadStatus();
  }

  function closePanel() {
    $("backup-overlay").hidden = true;
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = null;
    trigger?.focus?.();
  }

  async function saveSettings() {
    const enabled = $("backup-auto").checked;
    const destination = $("backup-directory").value;
    try {
      render({ ...current, enabled, destination, state: "running" });
      const status = await request("/api/backup/settings", {
        method: "PUT",
        body: JSON.stringify({
          enabled,
          destination,
        }),
      });
      render(status);
    } catch (error) {
      await loadStatus();
      const detail = $("backup-detail");
      detail.textContent = error.message;
      detail.classList.add("backup-detail-failed");
      detail.setAttribute("role", "alert");
    }
  }

  async function chooseDirectory() {
    const button = $("backup-choose-directory");
    button.disabled = true;
    button.textContent = "选择中…";
    try {
      const result = await request("/api/backup/choose-directory", { method: "POST" });
      if (result.destination) {
        $("backup-directory").value = result.destination;
        await saveSettings();
      }
    } catch (error) {
      const detail = $("backup-detail");
      detail.textContent = error.message;
      detail.classList.add("backup-detail-failed");
    } finally {
      button.disabled = false;
      button.textContent = "选个位置";
    }
  }

  async function pollRun() {
    const status = await loadStatus();
    if (status?.state === "running") {
      pollTimer = setTimeout(pollRun, 500);
    } else {
      pollTimer = null;
    }
  }

  async function runNow() {
    if ($("backup-run").disabled) return;
    try {
      render({ ...current, state: "running" });
      await request("/api/backup/run", { method: "POST" });
      pollTimer = setTimeout(pollRun, 300);
    } catch (error) {
      await loadStatus();
      const detail = $("backup-detail");
      detail.textContent = error.message;
      detail.classList.add("backup-detail-failed");
    }
  }

  function finishTrash(value) {
    $("trash-book-overlay").hidden = true;
    const resolve = trashResolve;
    trashResolve = null;
    resolve?.(value);
  }

  function confirmTrash(book) {
    $("trash-book-message").textContent = `《${book.title || book.name}》会移到回收站，随时能取回来。`;
    $("trash-book-counts").textContent = `里面有 ${book.finalized_count || 0} 章正式稿、${book.settings_filled_count || 0} 格设定。`;
    $("trash-book-overlay").hidden = false;
    $("trash-book-confirm").focus();
    return new Promise((resolve) => { trashResolve = resolve; });
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("backup-settings-button")?.addEventListener("click", openPanel);
    $("backup-status")?.addEventListener("click", openPanel);
    $("backup-close")?.addEventListener("click", closePanel);
    $("backup-auto")?.addEventListener("change", saveSettings);
    $("backup-choose-directory")?.addEventListener("click", chooseDirectory);
    $("backup-run")?.addEventListener("click", runNow);
    $("trash-book-cancel")?.addEventListener("click", () => finishTrash(false));
    $("trash-book-confirm")?.addEventListener("click", () => finishTrash(true));
    $("backup-overlay")?.addEventListener("click", (event) => { if (event.target === event.currentTarget) closePanel(); });
    $("trash-book-overlay")?.addEventListener("click", (event) => { if (event.target === event.currentTarget) finishTrash(false); });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (!$("trash-book-overlay").hidden) finishTrash(false);
      else if (!$("backup-overlay").hidden) closePanel();
    });
    loadStatus();
  });

  window.BiyuBackupPanel = { confirmTrash, loadStatus };
})();
