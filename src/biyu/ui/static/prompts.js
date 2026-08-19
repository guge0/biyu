/* P8-M2.5 T5 + T5 改造 — 提示词查看页(只读)。
 *
 * 中枢裁定:主体改读 .anchor/state/prompt_texts_<date>.md 最新导出件;
 * inventory 索引与 source 视图保留为辅(可折叠 details)。
 *
 * 流程:
 * 1. GET /api/prompts/texts → 最新 prompt_texts 全文 + 导出日期
 * 2. GET /api/prompts/inventory → 索引 markdown(辅)
 * 3. 页头渲染「导出于 <日期>·本地中枢定期刷新」
 * 4. miniMarkdown 渲染为只读 HTML
 *
 * 严禁:任何 POST / PUT 写接口。
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const envBadge = $("env-badge");
  const envLabel = $("env-label");
  const errorBanner = $("error-banner");
  const textsBody = $("texts-body");
  const invBody = $("inventory-body");
  const exportDateEl = $("texts-export-date");

  async function init() {
    try {
      const [envResp, peakResp, textsResp, invResp] = await Promise.all([
        fetch("/api/env"),
        fetch("/api/peak-hours"),
        fetch("/api/prompts/texts"),
        fetch("/api/prompts/inventory"),
      ]);
      const env = await envResp.json();
      renderEnv(env);
      const peak = await peakResp.json();
      renderPeak(peak);
      const texts = await textsResp.json();
      renderTexts(texts);
      const inv = await invResp.json();
      renderInventory(inv.markdown || "");
    } catch (e) {
      showError("加载提示词失败:" + e.message);
    }
  }

  function renderEnv(env) {
    if (!envBadge || !envLabel) return;
    envBadge.classList.remove("env-test", "env-prod");
    envBadge.classList.add(env.level === "prod" ? "env-prod" : "env-test");
    envLabel.textContent = env.label + " · " + env.level;
  }

  function renderPeak(peak) {
    const badge = $("peak-badge");
    const label = $("peak-label");
    if (!badge || !label) return;
    badge.classList.remove("peak-pending", "peak-on", "peak-off");
    if (peak.is_peak) {
      badge.classList.add("peak-on");
    } else if (peak.label && peak.label.indexOf("即将生效") >= 0) {
      badge.classList.add("peak-pending");
    } else {
      badge.classList.add("peak-off");
    }
    label.textContent = peak.label || "";
  }

  function renderTexts(texts) {
    // 页头:导出于 <日期>·本地中枢定期刷新
    if (texts.date) {
      exportDateEl.textContent = "导出于 " + texts.date + " · 本地中枢定期刷新";
    } else {
      exportDateEl.textContent = "暂未导出 · 本地技术中枢定期 dump .anchor/state/prompt_texts_<date>.md";
    }
    // 主体:prompt_texts 全文
    const md = texts.markdown || "";
    if (!md) {
      textsBody.innerHTML =
        '<p class="loading-placeholder">暂未导出 prompt_texts。' +
        '本地技术中枢运行 dump 后再来看。</p>';
      return;
    }
    textsBody.innerHTML = miniMarkdown(md);
  }

  function renderInventory(md) {
    if (!md) {
      invBody.innerHTML =
        '<p class="loading-placeholder">暂未生成 inventory。' +
        '本地技术中枢维护 .anchor/state/prompt_inventory.md 后再来看。</p>';
      return;
    }
    invBody.innerHTML = miniMarkdown(md);
  }

  function showError(msg) {
    errorBanner.textContent = msg;
    errorBanner.hidden = false;
  }

  // 极简 markdown(与 propose.js 同源,行内 + 块级)
  function miniMarkdown(md) {
    if (!md) return "";
    const lines = md.split("\n");
    let html = "";
    let inList = false;
    let inTable = false;
    let tableRows = [];
    let inQuote = false;
    let inCode = false;
    function closeList() { if (inList) { html += "</ul>"; inList = false; } }
    function closeQuote() { if (inQuote) { html += "</blockquote>"; inQuote = false; } }
    function closeTable() {
      if (inTable) {
        html += "<table>" + tableRows.join("") + "</table>";
        inTable = false;
        tableRows = [];
      }
    }
    function flushAll() { closeList(); closeQuote(); closeTable(); }

    lines.forEach((raw) => {
      const line = raw.trimEnd();
      if (line.startsWith("```")) {
        if (inCode) { html += "</pre>"; inCode = false; }
        else { flushAll(); html += "<pre>"; inCode = true; }
        return;
      }
      if (inCode) { html += esc(line) + "\n"; return; }
      if (!line.trim()) { closeList(); closeQuote(); closeTable(); return; }

      // 表格:| ... | ... |
      if (/^\|.*\|$/.test(line)) {
        closeList(); closeQuote();
        // 分割行 | --- | --- | 跳过
        if (/^\|[\s\-:|]+\|$/.test(line)) return;
        const cells = line.slice(1, -1).split("|").map((c) => c.trim());
        if (!inTable) { inTable = true; tableRows = []; }
        const tag = (tableRows.length === 0) ? "th" : "td";
        const row = "<tr>" + cells.map((c) => "<" + tag + ">" + inline(c) + "</" + tag + ">").join("") + "</tr>";
        tableRows.push(row);
        return;
      }
      closeTable();

      if (line.startsWith("### ")) {
        closeList(); closeQuote();
        html += "<h3>" + inline(line.slice(4)) + "</h3>";
      } else if (line.startsWith("## ")) {
        closeList(); closeQuote();
        html += "<h2>" + inline(line.slice(3)) + "</h2>";
      } else if (line.startsWith("# ")) {
        closeList(); closeQuote();
        html += "<h2>" + inline(line.slice(2)) + "</h2>";
      } else if (line.startsWith("> ")) {
        closeList();
        if (!inQuote) { html += "<blockquote>"; inQuote = true; }
        html += inline(line.slice(2)) + " ";
      } else if (line.startsWith("- ") || line.startsWith("* ")) {
        closeQuote();
        if (!inList) { html += "<ul>"; inList = true; }
        html += "<li>" + inline(line.slice(2)) + "</li>";
      } else if (line === "---") {
        flushAll();
        html += "<hr>";
      } else {
        closeList(); closeQuote();
        html += "<p>" + inline(line) + "</p>";
      }
    });
    if (inCode) html += "</pre>";
    flushAll();
    return html;
  }

  function inline(s) {
    return esc(s)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  function esc(s) {
    if (s === null || s === undefined) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  init();
})();
