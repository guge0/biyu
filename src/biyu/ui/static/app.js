/* P8-M2.5 T2 首页 — 书架 + 立项快捷 + 成本小卡 + 峰谷徽标。
 *
 * 流程:
 * 1. init:并行拉 /api/env / /api/peak-hours / /api/session / /api/books
 * 2. 渲染 env / peak 徽标
 * 3. 渲染书架(书卡):name / last_chapter
 * 4. 渲染"继续：<最近的书>"快捷(用书的 last_chapter)
 * 5. 空书架:显 empty-shelf 邀请文案
 *
 * 不依赖 propose.js(独立子屏的脚本)。
 */
(function () {
  "use strict";

  let sessionId = null;
  let cumulativeCost = 0;

  const $ = (id) => document.getElementById(id);

  function closeBookMoreMenus(except = null) {
    document.querySelectorAll(".book-more-menu").forEach((menu) => {
      if (menu === except) return;
      menu.hidden = true;
      menu.closest(".book-more")?.querySelector(".book-more-toggle")
        ?.setAttribute("aria-expanded", "false");
    });
  }

  document.addEventListener("click", () => closeBookMoreMenus());

  // ---------- 初始化 ----------
  async function init() {
    fetch("/api/version")
      .then(response => {
        if (!response.ok) throw new Error("版本接口不可用");
        return response.json();
      })
      .then(renderVersion)
      .catch(() => {
        const label = $("version-label");
        if (label) label.textContent = "版本无法确认";
      });
    try {
      const [sessResp, booksResp] = await Promise.all([
        fetch("/api/session"),
        fetch("/api/books"),
      ]);
      const sess = await sessResp.json();
      sessionId = sess.session_id;
      // F3 (P8-M3R-fix):/api/books 返 dict schema {books, count}
      const books = (await booksResp.json()).books;
      renderBooks(books);
    } catch (e) {
      showError("首页加载失败:" + e.message + "。请刷新或检查服务。");
    }
  }

  // ---------- 渲染 ----------
  function renderVersion(info) {
    const label = $("version-label");
    if (!label) return;
    label.textContent = `笔驭 ${info.version} · ${info.sha}`;
    label.title = `笔驭 ${info.version}`;
    const location = $("data-root-location");
    if (location) {
      const temporary = info.data_root_temporary ? "（这次是临时指定的位置）" : "";
      location.textContent = `你的书存在：${info.data_root}${temporary}`;
      location.classList.toggle("temporary", Boolean(info.data_root_temporary));
    }
  }



  function renderBooks(books) {
    const listEl = $("book-list");
    const emptyEl = $("empty-shelf");
    if (!listEl) return;

    // 清空"加载中"占位 + 折叠区书列表
    listEl.innerHTML = "";
    const archList = $("archived-book-list");
    if (archList) archList.innerHTML = "";

    if (!books || books.length === 0) {
      // 空态(P8-M3-pre T0.2):empty-shelf 已含「立项第一本」邀请入口,
      // 不再显示 quick-actions-empty(否则两个「立项」入口并列即为重复)
      if (emptyEl) emptyEl.hidden = false;
      const wrap = $("quick-actions");
      const wrapEmpty = $("quick-actions-empty");
      if (wrap) wrap.hidden = true;
      if (wrapEmpty) wrapEmpty.hidden = false;
      const archSection = $("archived-section");
      if (archSection) archSection.hidden = true;
      return;
    }

    // 按已写章节排序；相同进度保持接口返回的稳定顺序。
    const sorted = books.slice().sort((a, b) => {
      return (b.last_chapter || 0) - (a.last_chapter || 0);
    });

    // P8-M3-pre T0.1:按 kind 分组,真书(real)在主网格,测试/归档(非 real)在折叠区
    const realBooks = sorted.filter(b => b.kind === "real" || !b.kind);
    const otherBooks = sorted.filter(b => b.kind && b.kind !== "real");

    realBooks.forEach((book) => {
      listEl.appendChild(renderBookCard(book));
    });

    // S-1 留白栏：本数（中文数字）
    const countEl = $("shelf-count");
    if (countEl) {
      countEl.textContent = String(realBooks.length);
    }

    // 折叠区:测试/归档书
    const archSection = $("archived-section");
    const archCount = $("archived-count");
    if (otherBooks.length > 0 && archSection && archList) {
      if (archCount) archCount.textContent = otherBooks.length;
      otherBooks.forEach((book) => archList.appendChild(renderBookCard(book)));
      archSection.hidden = false;
    } else if (archSection) {
      archSection.hidden = true;
    }

    renderContinue(sorted[0]);
  }

  // ---------- T7 改名弹窗 ----------
  let renameModal = null;
  let renameBookName = null;

  function showRenameModal(book) {
    // R1 slug ID:用 book.id 作标识(无 id 时 /api/books 回退目录名)
    renameBookName = book.id || book.name;
    // 创建或获取弹窗
    if (!renameModal) {
      renameModal = document.createElement("div");
      renameModal.className = "modal-overlay";
      renameModal.id = "rename-modal";
      renameModal.innerHTML =
        '<div class="modal">' +
        '<h3>改名</h3>' +
        '<p>为新书名输入名称:</p>' +
        '<input id="rename-input" class="rename-input" type="text" placeholder="输入新书名…" />' +
        '<div class="modal-actions">' +
        '<button id="rename-cancel" class="btn-secondary" type="button">取消</button>' +
        '<button id="rename-confirm" class="btn-primary" type="button">确认</button>' +
        "</div>" +
        "</div>";
      document.body.appendChild(renameModal);

      document.getElementById("rename-cancel").addEventListener("click", closeRenameModal);
      document.getElementById("rename-confirm").addEventListener("click", confirmRename);
    }
    document.getElementById("rename-input").value = book.display_name || book.title || book.name;
    renameModal.hidden = false;
  }

  function closeRenameModal() {
    if (renameModal) renameModal.hidden = true;
  }

  async function confirmRename() {
    const input = document.getElementById("rename-input");
    const newTitle = input.value.trim();
    if (!newTitle) { alert("书名不能为空"); return; }
    if (!renameBookName) return;

    try {
      const resp = await fetch("/api/naming/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ book: renameBookName, title: newTitle }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        alert("改名失败: " + (err.detail || resp.statusText));
        return;
      }
      alert("书名已更新为: " + newTitle);
      closeRenameModal();
      // 刷新书架
      const booksResp = await fetch("/api/books");
      // F3 (P8-M3R-fix):/api/books 返 dict schema {books, count}
      const books = (await booksResp.json()).books;
      renderBooks(books);
    } catch (e) {
      alert("改名失败: " + e.message);
    }
  }

  function renderBookCard(book) {
    const card = document.createElement("div");
    card.className = "book-card";
    // R1 slug ID:data 属性 + URL 用 book.id(无 id 时 /api/books 回退目录名)
    card.dataset.bookId = book.id || book.name;

    // Keep real books on their established detail route. Test and archived
    // books are still existing books: resume them in the workbench instead
    // of mistaking them for a new proposal.
    const link = document.createElement("a");
    link.className = "book-card-link";
    link.href = book.kind === "real"
      ? "/book.html?book=" + encodeURIComponent(book.id || book.name)
      : "/workbench.html?book=" + encodeURIComponent(book.id || book.name);
    link.style.textDecoration = "none";
    link.style.color = "inherit";
    card.appendChild(link);

    const title = document.createElement("h3");
    title.className = "book-title";
    title.textContent = book.display_name || book.title || book.name;
    link.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "book-meta";
    const progress = book.last_chapter != null
      ? `已写到第 ${book.last_chapter} 章 · 其中 ${book.finalized_count || 0} 章已定稿`
      : "立项完成，未开写";
    const genreLabel = window.genreLabel ? window.genreLabel(book.genre) : book.genre;
    meta.textContent = genreLabel ? `${progress} · ${genreLabel}` : progress;
    link.appendChild(meta);

    const more = document.createElement("div");
    more.className = "book-more reading-more";
    const moreToggle = document.createElement("button");
    moreToggle.type = "button";
    moreToggle.textContent = "更多";
    moreToggle.className = "book-more-toggle b3";
    moreToggle.setAttribute("aria-expanded", "false");
    const moreMenu = document.createElement("div");
    moreMenu.className = "book-more-menu";
    moreMenu.hidden = true;
    moreToggle.addEventListener("click", (event) => {
      event.stopPropagation();
      const opening = moreMenu.hidden;
      closeBookMoreMenus(opening ? moreMenu : null);
      moreMenu.hidden = !opening;
      moreToggle.setAttribute("aria-expanded", String(opening));
    });
    moreMenu.addEventListener("click", (event) => event.stopPropagation());
    more.append(moreToggle, moreMenu);

    const renameBtn = document.createElement("button");
    renameBtn.className = "b3";
    renameBtn.type = "button";
    renameBtn.textContent = "改名";
    renameBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      closeBookMoreMenus();
      showRenameModal(book);
    });
    moreMenu.appendChild(renameBtn);

    const trashBtn = document.createElement("button");
    trashBtn.className = "b3";
    trashBtn.type = "button";
    trashBtn.appendChild(document.createTextNode("移到回收站"));
    trashBtn.addEventListener("click", async (event) => {
      event.stopPropagation();
      if (trashBtn.disabled) return;
      const chapters = book.finalized_count || 0;
      const settings = book.settings_filled_count || 0;
      if (!await window.BiyuBackupPanel.confirmTrash(book)) return;
      trashBtn.disabled = true;
      trashBtn.textContent = "移到回收站…";
      try {
        const response = await fetch(`/api/books/${encodeURIComponent(book.id || book.name)}/trash`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ actor: "author" }),
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || "整本书没有移入回收站");
        const booksResponse = await fetch("/api/books");
        renderBooks((await booksResponse.json()).books);
      } catch (error) {
        trashBtn.disabled = false;
        trashBtn.replaceChildren(document.createTextNode("移到回收站"));
        showError("移入回收站失败：" + error.message);
      }
    });
    moreMenu.appendChild(trashBtn);
    card.appendChild(more);

    // S-1 规范：卡片唯一实心主动作
    const nextBtn = document.createElement("a");
    nextBtn.className = "btn-primary continue-book-btn";
    if (book.last_chapter != null) {
      nextBtn.href = "/workbench.html?book=" + encodeURIComponent(book.id || book.name) +
        "&chapter=" + encodeURIComponent(book.last_chapter);
      nextBtn.textContent = "接着写";
    } else if (book.settings_ready) {
      nextBtn.href = "/workbench.html?book=" + encodeURIComponent(book.id || book.name) +
        "&chapter=1";
      nextBtn.textContent = "开始第 1 章";
    } else {
      nextBtn.href = "/settings.html?book=" + encodeURIComponent(book.id || book.name);
      nextBtn.textContent = "去填设定";
    }
    nextBtn.style.textDecoration = "none";
    card.appendChild(nextBtn);

    return card;
  }

  function renderContinue(book) {
    if (!book) return renderContinueNull();

    const chapter = book.last_chapter;

    if (chapter != null) {
      fillContinue(book, chapter);
    } else {
      renderContinueNull();
    }
  }

  function fillContinue(book, num) {
    const wrap = $("quick-actions");
    const wrapEmpty = $("quick-actions-empty");
    const link = $("continue-link");
    const bookEl = $("continue-book");
    const chEl = $("continue-chapter");
    if (!wrap || !link || !bookEl || !chEl) return;
    bookEl.textContent = book.title || book.name;
    chEl.textContent = num;
    // 继续入口只描述现役工作台的写作进度。
    link.innerHTML =
      '继续：<span id="continue-book">' + escapeHtml(book.title || book.name) +
      '</span> · 上次写到第 <span id="continue-chapter">' + num + '</span> 章';
    link.href = "/workbench.html?book=" + encodeURIComponent(book.id || book.name);
    wrap.hidden = false;
    if (wrapEmpty) wrapEmpty.hidden = true;
  }

  function renderContinueNull() {
    const wrap = $("quick-actions");
    const wrapEmpty = $("quick-actions-empty");
    if (wrap) wrap.hidden = true;
    if (wrapEmpty) wrapEmpty.hidden = false;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]
    ));
  }

  function showError(msg) {
    const banner = $("error-banner");
    if (!banner) {
      console.error(msg);
      return;
    }
    banner.replaceChildren();
    const message = document.createElement("span");
    message.textContent = "✗ " + msg;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "error-banner-close";
    close.textContent = "×";
    close.addEventListener("click", () => { banner.hidden = true; });
    banner.append(message, close);
    banner.hidden = false;
  }

  function wireCreateBook() {
    const overlay = $("create-book-overlay");
    const form = $("create-book-form");
    const submit = $("create-book-submit");
    const status = $("create-book-status");
    if (!overlay || !form || !submit || !status) return;
    const open = () => { status.textContent = ""; overlay.hidden = false; $("create-book-title").focus(); };
    [$("create-book-button"), $("create-book-empty-button")].forEach(button => {
      if (button) button.addEventListener("click", open);
    });
    $("create-book-cancel").addEventListener("click", () => { overlay.hidden = true; });
    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (submit.disabled) return;
      submit.disabled = true;
      submit.textContent = "创建中…";
      status.textContent = "正在建立书籍档案…";
      status.className = "";
      try {
        const response = await fetch("/api/books", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({title: $("create-book-title").value, genre: $("create-book-genre").value}),
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || "新书没有创建成功");
        status.textContent = "创建成功，正在打开书籍…";
        location.href = "/book.html?book=" + encodeURIComponent(body.id);
      } catch (error) {
        status.textContent = "创建失败：" + error.message;
        status.className = "setup-error";
        showError("新建书失败：" + error.message);
      } finally {
        submit.disabled = false;
        submit.textContent = "创建";
      }
    });
  }

  // ---------- 启动 ----------
  document.addEventListener("DOMContentLoaded", () => { wireCreateBook(); init(); });
})();
