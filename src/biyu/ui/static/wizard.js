/* S-3 T4 · 一句话开书向导（图纸屏2 三步;REQ-W1 失败不建残书）。 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const GENRES = ["末世回溯", "玄幻修仙", "都市异能", "悬疑智斗", "历史权谋", "无限流", "轻小说"];
  const state = { step: 1, idea: "", genre: "", tier: "3000", titles: [], titleIdx: 0, busy: false };

  function show(step) {
    state.step = step;
    $("wizard-step1").hidden = step !== 1;
    $("wizard-step2").hidden = step !== 2;
    $("wizard-step3").hidden = step !== 3;
    $("wizard-step-num").textContent = step === 1 ? "一" : step === 2 ? "二" : "三";
    window.scrollTo(0, 0);
  }

  function error(msg) {
    const banner = $("error-banner");
    banner.textContent = "✗ " + msg;
    banner.hidden = false;
  }

  // ---------- 第一步交互 ----------
  const genreWrap = $("wizard-genres");
  GENRES.forEach((g) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "b2 bs";
    btn.textContent = g;
    btn.addEventListener("click", () => {
      state.genre = state.genre === g ? "" : g;
      [...genreWrap.children].forEach((b) => b.classList.toggle("current", b.textContent === state.genre));
    });
    genreWrap.appendChild(btn);
  });
  document.querySelectorAll(".wizard-sample").forEach((btn) => {
    btn.addEventListener("click", () => {
      $("wizard-idea").value = btn.dataset.idea;
      state.genre = btn.dataset.genre;
      [...genreWrap.children].forEach((b) => b.classList.toggle("current", b.textContent === state.genre));
    });
  });
  $("wizard-tiers").addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-tier]");
    if (!btn) return;
    state.tier = btn.dataset.tier;
    [...$("wizard-tiers").children].forEach((b) => b.classList.toggle("current", b === btn));
  });

  // ---------- 推演 ----------
  async function generate() {
    state.idea = $("wizard-idea").value.trim();
    if (!state.idea) { error("请先写下你的一句话想法。"); return; }
    if (state.busy) return;
    state.busy = true;
    show(2);
    $("wizard-running").hidden = false;
    $("wizard-error").hidden = true;
    try {
      const resp = await fetch("/api/wizard/premise", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idea: state.idea, genre: state.genre, word_tier: state.tier }),
      });
      const body = await resp.json();
      if (!resp.ok || !body.ok) throw new Error(body.detail || body.error || "推演失败");
      fillResult(body.result);
      show(3);
    } catch (exc) {
      $("wizard-error-detail").textContent = String(exc.message || exc).slice(0, 300);
      $("wizard-running").hidden = true;
      $("wizard-error").hidden = false;
    } finally {
      state.busy = false;
    }
  }

  function fillResult(r) {
    state.titles = r.titles;
    state.titleIdx = 0;
    $("wizard-result-meta").textContent = (state.genre || "不限题材") + " · 单章 " + state.tier + " 字";
    const wrap = $("wizard-titles");
    wrap.replaceChildren();
    r.titles.forEach((title, idx) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "b2 bs";
      btn.textContent = "候选 " + (idx + 1) + "：《" + title + "》";
      btn.addEventListener("click", () => {
        state.titleIdx = idx;
        $("wizard-title-input").value = title;
        [...wrap.children].forEach((b) => b.classList.toggle("current", b === btn));
      });
      wrap.appendChild(btn);
    });
    $("wizard-title-input").value = r.titles[0];
    wrap.firstElementChild.classList.add("current");
    $("wizard-summary").value = r.summary || "";
    $("wizard-worldview").value = (r.worldview || []).join("\n");
    $("wizard-protagonist").value = r.protagonist || "";
    $("wizard-vol1").value = r.vol1 || "";
  }

  // ---------- 落盘建书（作者确认后） ----------
  async function confirmCreate() {
    if (state.busy) return;
    state.busy = true;
    $("wizard-confirm").disabled = true;
    $("wizard-confirm").textContent = "正在建书落盘…";
    try {
      const resp = await fetch("/api/wizard/books", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: $("wizard-title-input").value.trim(),
          genre: state.genre,
          word_tier: state.tier,
          summary: $("wizard-summary").value,
          worldview: $("wizard-worldview").value,
          protagonist: $("wizard-protagonist").value,
          vol1: $("wizard-vol1").value,
        }),
      });
      const body = await resp.json();
      if (!resp.ok || !body.ok) throw new Error(body.detail || "建书失败");
      location.href = "/workbench.html?book=" + encodeURIComponent(body.id) + "&chapter=1";
    } catch (exc) {
      error("开书失败：" + (exc.message || exc) + "。磁盘上没有留下残书，可重试。");
      $("wizard-confirm").disabled = false;
      $("wizard-confirm").textContent = "就这样，开写第一章";
      state.busy = false;
    }
  }

  // ---------- 手动建书（决策5） ----------
  function openManual() {
    $("wizard-manual-overlay").hidden = false;
    $("wizard-manual-title").focus();
  }

  // ---------- 接线 ----------
  $("wizard-generate").addEventListener("click", generate);
  $("wizard-retry").addEventListener("click", generate);
  $("wizard-reroll").addEventListener("click", generate);
  ["wizard-back-idea", "wizard-back-idea2"].forEach((id) => $(id).addEventListener("click", () => show(1)));
  $("wizard-confirm").addEventListener("click", confirmCreate);
  ["wizard-manual", "wizard-manual-top", "wizard-error-manual"].forEach((id) => $(id).addEventListener("click", openManual));
  $("wizard-manual-cancel").addEventListener("click", () => { $("wizard-manual-overlay").hidden = true; });
  $("wizard-manual-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = $("wizard-manual-status");
    status.textContent = "正在建立书籍档案…";
    try {
      const resp = await fetch("/api/books", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: $("wizard-manual-title").value,
          genre: $("wizard-manual-genre").value,
        }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.detail || "新书没有创建成功");
      location.href = "/settings.html?book=" + encodeURIComponent(body.id);
    } catch (exc) {
      status.textContent = "创建失败：" + (exc.message || exc);
    }
  });
})();
