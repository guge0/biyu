/* S-3 T7 · 快检台前端(三色高亮/雷达/转存;纯本地,无 Key 可用)。 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const SAMPLE = "夜色深沉，南城旧武馆的后院里静得可怕。张今空站在石阶旁，嘴角勾起一抹三分薄凉七分讥诮的弧度，眼神微眯透出危险的气息。某种意义上来说，昨晚那场死亡回溯的阴影似乎还在他心头萦绕。院墙外传来的脚步声如同潮水般涌来，像一柄利剑刺破黑夜，让他不由得屏住了呼吸。方圆端着茶碗走过来，她的身影在月光下宛如一尊凝固的雕塑。张今空心里仿佛闪过一丝莫名的悲凉，却只是缓缓低头，轻轻擦了擦手里的短刀。巷口的灯笼缓缓熄灭，只剩巡城司暗探那双眼睛在黑暗中亮起，瞳孔一缩之间，杀意如同实质般涌来。";

  let lastResult = null;

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  function showError(msg) {
    const banner = $("error-banner");
    banner.textContent = "✗ " + msg;
    banner.hidden = false;
  }

  function updateCharCount() {
    $("qc-char-count").textContent = "字数：" + $("qc-input").value.length.toLocaleString();
  }

  // ---------- 扫描与渲染 ----------
  async function scan() {
    const text = $("qc-input").value.trim();
    if (!text) { showError("请先粘贴或载入一段文本。"); return; }
    $("qc-scan-btn").disabled = true;
    $("qc-scan-btn").textContent = "扫描中…";
    try {
      const resp = await fetch("/api/quickcheck/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.detail || "扫描失败");
      lastResult = body;
      renderHighlight(text, body.hits);
      renderRadar(body);
    } catch (exc) {
      showError(exc.message || String(exc));
    } finally {
      $("qc-scan-btn").disabled = false;
      $("qc-scan-btn").textContent = "⚡ 立即体检（本地 0 成本）";
    }
  }

  function renderHighlight(text, hits) {
    const view = $("qc-highlight-view");
    view.replaceChildren();
    let cursor = 0;
    hits.forEach((hit) => {
      if (hit.offset > cursor) view.appendChild(document.createTextNode(text.slice(cursor, hit.offset)));
      const span = document.createElement("span");
      span.className = hit.highlight_class;
      span.textContent = text.slice(hit.offset, hit.offset + hit.length);
      span.title = "点击词条定位";
      span.style.cursor = "pointer";
      span.addEventListener("click", () => {
        const input = $("qc-input");
        input.focus();
        input.setSelectionRange(hit.offset, hit.offset + hit.length);
        const lines = text.slice(0, hit.offset).split("\n").length;
        input.scrollTop = (lines - 6) * 34;
      });
      view.appendChild(span);
      cursor = hit.offset + hit.length;
    });
    if (cursor < text.length) view.appendChild(document.createTextNode(text.slice(cursor)));
    view.hidden = false;
    $("qc-input").hidden = true;
    $("qc-copy-clean").hidden = false;
  }

  function renderRadar(data) {
    $("qc-score").textContent = String(data.score);
    const rows = $("qc-radar-rows");
    rows.replaceChildren();
    const labels = {
      simile_markers: "明喻引导词（像是/仿佛/如同）",
      tic_words: "缓冲词（缓缓/微微/轻轻/嘴角）",
      cliche_expressions: "套话表情（瞳孔一缩/嘴角上扬等）",
    };
    data.families.forEach((fam) => {
      const row = document.createElement("div");
      row.className = "density-row";
      const meta = document.createElement("div");
      meta.className = "density-meta";
      const name = document.createElement("span");
      name.innerHTML = "<strong>" + labels[fam.key] + "</strong>";
      const value = document.createElement("span");
      value.style.fontWeight = "600";
      value.style.color = fam.exceeded ? "var(--mark)" : "var(--ok)";
      value.textContent = fam.per_kchar.toFixed(1) + " / 千字 (阈值 ≤" + fam.limit + (fam.exceeded ? " · 超标)" : " ✓)");
      meta.append(name, value);
      const bg = document.createElement("div");
      bg.className = "density-bar-bg";
      const fill = document.createElement("div");
      fill.className = "density-bar-fill";
      fill.style.width = Math.min(100, Math.round((fam.per_kchar / (fam.limit * 2)) * 100)) + "%";
      fill.style.background = fam.exceeded ? "var(--mark)" : "var(--ok)";
      bg.appendChild(fill);
      row.append(meta, bg);
      row.addEventListener("click", () => {
        const first = data.hits.find((h) => h.family === fam.key);
        if (first) {
          const input = $("qc-input");
          input.focus();
          input.setSelectionRange(first.offset, first.offset + first.length);
        }
      });
      rows.appendChild(row);
    });
  }

  // ---------- 转存 ----------
  async function fillBooks() {
    const select = $("qc-save-book");
    select.replaceChildren();
    try {
      const books = (await (await fetch("/api/books")).json()).books || [];
      if (!books.length) {
        const opt = document.createElement("option");
        opt.textContent = "（书架还没有书）";
        select.appendChild(opt);
        return;
      }
      books.forEach((b) => {
        const opt = document.createElement("option");
        opt.value = b.id;
        opt.textContent = b.display_name || b.title || b.name;
        select.appendChild(opt);
      });
    } catch (_e) { /* 打开弹窗时书架读取失败按空处理 */ }
  }

  async function saveAsNewBook() {
    const text = $("qc-input").value.trim();
    if (!text) { showError("先粘贴文本再转存。"); return; }
    const title = prompt("新书书名：", "快检台转存 " + new Date().toLocaleDateString("zh-CN"));
    if (!title || !title.trim()) return;
    try {
      const resp = await fetch("/api/books", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title.trim(), genre: "xuanyi" }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.detail || "建书失败");
      await importTo(body.id, 1, "候选稿已转存为书架新书《" + title.trim() + "》第 1 章，可去工作台继续审读。");
    } catch (exc) {
      showError("转存失败：" + (exc.message || exc));
    }
  }

  async function importTo(bookId, chapter, successMsg) {
    const text = $("qc-input").value.trim();
    const resp = await fetch(`/api/workbench/books/${encodeURIComponent(bookId)}/imports`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        items: [{ title: "", chapter: chapter, content: text, identity: "candidate" }],
        confirmed: true,
      }),
    });
    const body = await resp.json();
    if (!resp.ok) throw new Error(body.detail || "导入失败");
    $("qc-save-overlay").hidden = true;
    $("qc-save-status").textContent = "";
    showError(successMsg);
    const banner = $("error-banner");
    banner.style.color = "var(--ok)";
    setTimeout(() => { banner.hidden = true; banner.style.color = ""; }, 4000);
  }

  async function saveToExisting() {
    const text = $("qc-input").value.trim();
    if (!text) { showError("先粘贴文本再转存。"); return; }
    $("qc-save-overlay").hidden = false;
    await fillBooks();
  }

  async function confirmSaveExisting() {
    const book = $("qc-save-book").value;
    const chapter = Math.max(1, Number($("qc-save-chapter").value || 1));
    if (!book) { $("qc-save-status").textContent = "书架还没有书，请先用「转存为书架新书」。"; return; }
    $("qc-save-confirm").disabled = true;
    $("qc-save-status").textContent = "正在存入…";
    try {
      await importTo(book, chapter, "候选稿已存入所选书第 " + chapter + " 章。");
    } catch (exc) {
      $("qc-save-status").textContent = "存入失败：" + (exc.message || exc);
    } finally {
      $("qc-save-confirm").disabled = false;
    }
  }

  // ---------- 接线 ----------
  $("qc-scan-btn").addEventListener("click", scan);
  $("qc-sample-btn").addEventListener("click", () => {
    $("qc-input").value = SAMPLE;
    $("qc-input").hidden = false;
    $("qc-highlight-view").hidden = true;
    updateCharCount();
  });
  $("qc-paste-btn").addEventListener("click", async () => {
    $("qc-input").hidden = false;
    $("qc-highlight-view").hidden = true;
    // S-3B 走查反馈:按钮文案承诺「粘贴」,就真的读剪贴板;权限拒绝/剪贴板为空再回落聚焦。
    try {
      if (navigator.clipboard && navigator.clipboard.readText) {
        const text = await navigator.clipboard.readText();
        if (text && text.trim()) {
          $("qc-input").value = text;
          updateCharCount();
          $("qc-paste-btn").textContent = "已读入剪贴板 ✓";
          setTimeout(() => { $("qc-paste-btn").textContent = "📋 粘贴我的小说稿"; }, 1600);
          return;
        }
      }
    } catch (error) { /* 剪贴板权限被拒或不可用:按普通输入框处理 */ }
    $("qc-input").focus();
  });
  $("qc-input").addEventListener("input", updateCharCount);
  $("qc-file").addEventListener("change", async (event) => {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    $("qc-input").value = await file.text();
    $("qc-input").hidden = false;
    $("qc-highlight-view").hidden = true;
    updateCharCount();
  });
  $("qc-copy-clean").addEventListener("click", () => {
    if (navigator.clipboard) navigator.clipboard.writeText($("qc-input").value);
    $("qc-copy-clean").textContent = "已复制 ✓";
    setTimeout(() => { $("qc-copy-clean").textContent = "📋 复制纯文本"; }, 1500);
  });
  $("qc-save-new").addEventListener("click", saveAsNewBook);
  $("qc-save-existing").addEventListener("click", saveToExisting);
  $("qc-save-cancel").addEventListener("click", () => { $("qc-save-overlay").hidden = true; });
  $("qc-save-confirm").addEventListener("click", confirmSaveExisting);
  $("qc-save-overlay").addEventListener("click", (event) => {
    if (event.target === $("qc-save-overlay")) $("qc-save-overlay").hidden = true;
  });

  // S-3C 浏览器模式（便携）:与其他页一致,标签页标题注明当前模式
  fetch("/api/version").then(r => r.json()).then(info => {
    if (info.launch_mode === "browser_portable" && !document.title.includes("浏览器模式（便携）")) {
      document.title = document.title + " · 浏览器模式（便携）";
    }
  }).catch(() => {});
})();
