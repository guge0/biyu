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
    label.textContent = `笔驭 ${info.version}`; label.title = `构建 ${info.build} · ${info.sha}`;
    // S-3C 浏览器模式（便携）:无 Electron 环境的便携包启动时,书架页标注模式
    if (info.launch_mode === "browser_portable") {
      label.textContent = `笔驭 ${info.version} · 浏览器模式（便携）`;
      if (!document.title.includes("浏览器模式（便携）")) document.title = `${document.title} · 浏览器模式（便携）`;
    }
    label.title = `构建 ${info.build} · ${info.sha}`;
    const update = info.update || {};
    const updateDot = $("update-dot");
    const hasUpdate = Boolean(update.available || info.update_available);
    if (updateDot) {
      updateDot.hidden = !hasUpdate;
      updateDot.title = hasUpdate ? `有新版本：${update.published || info.latest_version || "可用更新"}` : "暂无更新";
    }
    // 2026-10 老板要求:落后 origin/main 标红点,点击拉取最新
    const behind = Number(info.behind_commits || 0);
    let behindDot = $("behind-dot");
    if (behind > 0) {
      if (!behindDot) {
        behindDot = document.createElement("button");
        behindDot.id = "behind-dot";
        behindDot.className = "update-dot update-dot-behind";
        behindDot.onclick = async () => {
          behindDot.disabled = true;
          behindDot.title = "正在拉取…";
          try {
            const result = await (await fetch("/api/update/pull", { method: "POST" })).json();
            behindDot.title = result.ok ? result.hint : `拉取失败：${result.message}`;
            if (result.ok) behindDot.classList.add("pulled");
          } catch (_e) {
            behindDot.title = "拉取失败：服务未响应";
          } finally { behindDot.disabled = false; }
        };
        (updateDot && updateDot.parentElement ? updateDot.parentElement : label.parentElement).append(behindDot);
      }
      behindDot.hidden = false;
      behindDot.setAttribute("aria-label", `落后 ${behind} 个提交`);
      behindDot.title = `落后最新版本 ${behind} 个提交，点击拉取（拉取后重启笔驭生效）`;
    } else if (behindDot) {
      behindDot.hidden = true;
    }
    const badge = $("version-badge");
    if (badge) badge.classList.toggle("has-update", hasUpdate);
    const current = $("version-current");
    const latest = $("version-latest");
    if (current) current.textContent = `当前版本：${info.version} · ${info.sha}`;
    if (latest) {
      latest.hidden = !hasUpdate;
      latest.textContent = hasUpdate ? `最新版本：${update.published || info.latest_version}${update.published_build ? ` · ${update.published_build}` : ""}` : "暂无可用更新";
    }
    const link = $("version-update-link");
    if (link) {
      link.hidden = !hasUpdate;
      link.href = update.url || "#";
    }
    const location = $("data-root-location");
    if (location) {
      const temporary = info.data_root_temporary ? "（这次是临时指定的位置）" : "";
      location.textContent = `你的书存在：${info.data_root}${temporary}`;
      location.classList.toggle("temporary", Boolean(info.data_root_temporary));
    }
  }

  const versionBadge = $("version-badge");
  const versionDetails = $("version-details");
  if (versionBadge && versionDetails) {
    versionBadge.addEventListener("click", event => {
      event.stopPropagation();
      const expanded = versionBadge.getAttribute("aria-expanded") === "true";
      versionBadge.setAttribute("aria-expanded", String(!expanded));
      versionDetails.hidden = expanded;
    });
    versionDetails.addEventListener("click", event => event.stopPropagation());
    document.addEventListener("click", () => {
      versionBadge.setAttribute("aria-expanded", "false");
      versionDetails.hidden = true;
    });
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

    realBooks.forEach((book, index) => {
      listEl.appendChild(renderBookCard(book, index === 0));
    });

    // S-1 留白栏：本数（中文数字）
    const countEl = $("shelf-count");
    if (countEl) {
      countEl.textContent = window.cnNum ? cnNum(realBooks.length) : String(realBooks.length);
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

  function renderBookCard(book, isLead) {
    const card = document.createElement("div");
    card.className = "card book-card" + (isLead ? " lead" : "");
    // R1 slug ID:data 属性 + URL 用 book.id(无 id 时 /api/books 回退目录名)
    card.dataset.bookId = book.id || book.name;

    const title = book.display_name || book.title || book.name;

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

    const top = document.createElement("div");
    top.className = "book-card-top";
    const head = document.createElement("div");
    const titleEl = document.createElement("p");
    titleEl.className = "card-title";
    titleEl.textContent = title;
    const meta = document.createElement("p");
    meta.className = "card-meta";
    meta.style.marginBottom = "10px";
    meta.textContent = book.last_chapter != null
      ? `写到第 ${book.last_chapter} 章 · 其中 ${book.finalized_count || 0} 章已定稿`
      : "立项完成，未开写";
    head.appendChild(titleEl);
    head.appendChild(meta);
    const coverChar = document.createElement("div");
    coverChar.className = "book-cover-char";
    coverChar.textContent = String(title || "书").trim().charAt(0) || "书";
    top.appendChild(head);
    top.appendChild(coverChar);
    link.appendChild(top);

    // V2 书卡徽章行：只展示接口真实存在的字段；字数/花费/更新时间暂缺，整体隐藏
    const badges = document.createElement("div");
    badges.className = "row";
    badges.style.gap = "6px";
    badges.style.marginBottom = "16px";
    const genreLabel = window.genreLabel ? window.genreLabel(book.genre) : book.genre;
    if (genreLabel) {
      const genreBadge = document.createElement("span");
      genreBadge.className = "badge";
      genreBadge.textContent = genreLabel;
      badges.appendChild(genreBadge);
    }
    const settingBadge = document.createElement("span");
    settingBadge.className = book.settings_ready ? "badge ok" : "badge need";
    settingBadge.textContent = book.settings_ready ? "设定就绪" : "设定待填";
    badges.appendChild(settingBadge);
    if (book.is_sample) {
      const sampleBadge = document.createElement("span");
      sampleBadge.className = "badge ok";
      sampleBadge.textContent = "★ 预载示例书 · 免Key可玩";
      badges.appendChild(sampleBadge);
    }
    card.appendChild(badges);

    const footRow = document.createElement("div");
    footRow.className = "row";
    footRow.style.gap = "8px";

    // S-1 规范：卡片主按钮（沿用 continue-book-btn 契约类，V2 描边强调形态）
    const nextBtn = document.createElement("a");
    nextBtn.className = "b2 bs continue-book-btn";
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
    footRow.appendChild(nextBtn);

    const overviewBtn = document.createElement("a");
    overviewBtn.className = "b3 bs";
    overviewBtn.href = "/overview.html?book=" + encodeURIComponent(book.id || book.name);
    overviewBtn.textContent = "全书概览";
    overviewBtn.style.textDecoration = "none";
    footRow.appendChild(overviewBtn);

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
      if (opening) {
        // S-3B 走查修复:书卡贴近视口底部时菜单向下展开会整条掉到视口外,
        // 而应用壳页面不可滚动——放不下就向上翻。
        moreMenu.style.top = "";
        moreMenu.style.bottom = "";
        const rect = moreMenu.getBoundingClientRect();
        if (rect.bottom > window.innerHeight - 8) {
          moreMenu.style.top = "auto";
          moreMenu.style.bottom = "calc(100% + 6px)";
        }
      }
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

    const settingsLink = document.createElement("a");
    settingsLink.className = "b3";
    settingsLink.href = "/settings.html?book=" + encodeURIComponent(book.id || book.name);
    settingsLink.style.textDecoration = "none";
    settingsLink.textContent = "设定集 (" + (book.settings_filled_count || 0) + "/9格)";
    settingsLink.addEventListener("click", (e) => e.stopPropagation());
    moreMenu.appendChild(settingsLink);

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
    footRow.appendChild(more);

    card.appendChild(footRow);
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
    // S-3 T4:「+ 新建作品 / + 新建第一本书」进入 AI 开书向导页(图纸屏2);
    // 手动建书按钮(T3 体验层)仍开本弹窗。
    [$("create-book-button"), $("create-book-empty-button")].forEach((button) => {
      if (button) button.addEventListener("click", () => { location.href = "/wizard.html"; });
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

/* ==================== S-3 T3 · 无 Key 体验层（图纸 P0-2A/B/C/D 搬运） ====================
 * 迎宾笺条（随 setup ready 两态）+ 书斋耕读历（热力格/拦截统计/印章入口）
 * + 领 Key 锦囊（三渠道图文，保存走既有 setup 向导）+ 朱批钤印（真实达成态）。
 * 独立拉取数据,不改上方现役书架流程。
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const KEY_GUIDE_STEPS = {
    deepseek: [
      ["第 1 步", "浏览器打开 platform.deepseek.com，手机号验证码 5 秒登录", "https://platform.deepseek.com"],
      ["第 2 步", "点左侧「充值」充 ¥10（约可写 80 章 / 25 万字网文，几乎用不完）", ""],
      ["第 3 步", "点左侧「API Keys → 创建 API Key」，复制以 sk- 开头的密钥粘贴到下方即可！", ""],
    ],
    silicon: [
      ["第 1 步", "打开硅基流动 cloud.siliconflow.cn 注册账号（新用户直接送 14 元免费 Token 额度）", "https://cloud.siliconflow.cn"],
      ["第 2 步", "在左侧「API 密钥」新建一条 sk- 密钥，在笔驭服务商选「硅基流动 DeepSeek-V3」即可白嫖开写！", ""],
    ],
    kimi: [
      ["Kimi", "前往 platform.moonshot.cn 创建 API Key，适合长上下文设定集读取", "https://platform.moonshot.cn"],
      ["Claude", "也可在服务商选「Claude」，填 Anthropic 官方 Key（claude-3-7-sonnet）", ""],
    ],
  };

  function renderWelcome(ready) {
    const strip = $("welcome-strip");
    if (!strip) return;
    const badge = $("welcome-mode-badge");
    const text = $("welcome-text");
    if (!ready) {
      badge.textContent = "✦ 免 Key 零门槛畅玩模式";
      badge.className = "badge ws-badge amber";
      text.innerHTML = "还没申请 API Key？完全不影响！你现在可直接<strong>畅读并体检《死亡回溯》预载示例书</strong>、使用<strong>⚡独立快检台免费查 AI 味</strong>、手动建书或批量导入旧作。";
    } else {
      badge.textContent = "✓ 已配 Key 直连";
      badge.className = "badge ws-badge ok";
      text.textContent = "当前已连接官方 API Key，五步写作管线与独立快检台均可全速运行。";
    }
    strip.hidden = false;
  }

  function renderKeyGuideSteps(tab) {
    const box = $("key-guide-steps");
    if (!box) return;
    box.replaceChildren();
    KEY_GUIDE_STEPS[tab].forEach((step) => {
      const item = document.createElement("div");
      item.className = "list-item m-done";
      const num = document.createElement("span");
      num.className = "ch";
      num.style.color = "var(--ok)";
      num.textContent = step[0];
      const body = document.createElement("span");
      body.style.flex = "1";
      body.textContent = step[1];
      item.append(num, body);
      if (step[2]) {
        const copy = document.createElement("button");
        copy.type = "button";
        copy.className = "b2 bs";
        copy.textContent = "复制网址";
        copy.addEventListener("click", () => {
          navigator.clipboard?.writeText(step[2]);
          copy.textContent = "已复制";
          setTimeout(() => (copy.textContent = "复制网址"), 1500);
        });
        item.appendChild(copy);
      }
      box.appendChild(item);
    });
  }

  function openKeyGuide() {
    const overlay = $("key-guide-overlay");
    if (!overlay) return;
    overlay.hidden = false;
    renderKeyGuideSteps("deepseek");
    document.querySelectorAll(".key-guide-tab").forEach((btn) => {
      btn.classList.toggle("current", btn.dataset.tab === "deepseek");
    });
  }

  function wireKeyGuide() {
    const overlay = $("key-guide-overlay");
    if (!overlay) return;
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) overlay.hidden = true;
    });
    $("key-guide-close").addEventListener("click", () => { overlay.hidden = true; });
    document.querySelectorAll(".key-guide-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".key-guide-tab").forEach((b) => b.classList.toggle("current", b === btn));
        renderKeyGuideSteps(btn.dataset.tab);
      });
    });
    $("key-guide-save").addEventListener("click", () => {
      const key = $("key-guide-input").value.trim();
      overlay.hidden = true;
      const setupKey = document.getElementById("setup-key");
      if (key && setupKey) setupKey.value = key;
      const setupOverlay = document.getElementById("setup-overlay");
      if (setupOverlay) setupOverlay.hidden = false;
      if (setupKey) setupKey.focus();
    });
  }

  // ---------- 朱批钤印 ----------
  let sealState = null;
  let activeSealKey = null;

  const SEAL_CHARS = {
    first_chapter: "初啼定稿",
    ten_k: "落纸万言",
    hundred_k: "云烟十万",
    first_contract: "言出法随",
  };
  const SEAL_QUOTES = {
    first_chapter: "第一份正文由你亲手拍板落定——从这一章起，你是一名作者。",
    ten_k: "一万字是最陡的坡。你已经翻过去了。",
    hundred_k: "机器起草、作者钦定。十万晨光与铜鞘清响，皆由你亲手拍板落定。",
    first_contract: "每一条细纲要点皆有正文原句佐证，绝不让 AI 乱改你笔下的江湖。",
  };

  function sealSvg(chars) {
    const c = (chars || "笔驭印").padEnd(4, "印");
    return (
      '<svg class="cinnabar-seal-svg" viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">' +
      '<rect x="6" y="6" width="108" height="108" rx="8" fill="#A63424" stroke="#7E2215" stroke-width="4"/>' +
      '<rect x="13" y="13" width="94" height="94" rx="4" fill="none" stroke="#F7F1E3" stroke-width="2.2" stroke-dasharray="48 4 36 3"/>' +
      '<line x1="60" y1="14" x2="60" y2="106" stroke="#F7F1E3" stroke-width="1.8" opacity="0.85"/>' +
      '<line x1="14" y1="60" x2="106" y2="60" stroke="#F7F1E3" stroke-width="1.8" opacity="0.85"/>' +
      '<text x="37" y="46" fill="#F7F1E3" font-family="serif" font-size="24" font-weight="700" text-anchor="middle">' + c[0] + "</text>" +
      '<text x="37" y="90" fill="#F7F1E3" font-family="serif" font-size="24" font-weight="700" text-anchor="middle">' + c[1] + "</text>" +
      '<text x="83" y="46" fill="#F7F1E3" font-family="serif" font-size="24" font-weight="700" text-anchor="middle">' + c[2] + "</text>" +
      '<text x="83" y="90" fill="#F7F1E3" font-family="serif" font-size="24" font-weight="700" text-anchor="middle">' + c[3] + "</text>" +
      "</svg>"
    );
  }

  function renderSealTab(key) {
    const seal = (sealState && sealState.seals || []).find((s) => s.key === key);
    const scroll = $("seal-scroll");
    if (!seal || !scroll) return;
    activeSealKey = key;
    scroll.innerHTML =
      '<span class="badge ' + (seal.achieved ? "need" : "") + '" style="margin-bottom:8px">' +
      (seal.achieved ? "里程碑已达成" : "尚未达成 · 继续耕读") + "</span>" +
      '<h3 style="font-family:var(--display-font);font-size:23px;font-weight:600;color:#262018;margin:4px 0 6px">' + seal.title + "</h3>" +
      '<p style="font-size:13px;color:#5A5144;margin:0 0 12px">' + seal.detail + "</p>" +
      sealSvg(SEAL_CHARS[key]) +
      '<p style="font-family:var(--serif);font-size:14.5px;color:#2E2820;margin:8px auto 12px;max-width:28em;line-height:1.75">' + SEAL_QUOTES[key] + "</p>" +
      '<div style="font-size:11.5px;color:#827868;border-top:1px dashed #D2C5A8;padding-top:10px">笔驭 biyu · 本地优先 AI 网文工作站&nbsp;|&nbsp;内测作者群：892467108</div>';
    document.querySelectorAll("#seal-tabs .b2").forEach((btn) => {
      btn.classList.toggle("current", btn.dataset.seal === key);
    });
  }

  function openSeals() {
    if (!sealState) return;
    const tabs = $("seal-tabs");
    if (!tabs) return;
    tabs.replaceChildren();
    sealState.seals.forEach((seal) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "b2 bs";
      btn.dataset.seal = seal.key;
      btn.textContent = (seal.achieved ? "💮 " : "◻ ") + seal.title;
      btn.addEventListener("click", () => renderSealTab(seal.key));
      tabs.appendChild(btn);
    });
    const firstAchieved = sealState.seals.find((s) => s.achieved) || sealState.seals[0];
    renderSealTab(firstAchieved.key);
    $("seals-overlay").hidden = false;
  }

  function saveSealPoster() {
    const scroll = $("seal-scroll");
    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 760;
    const ctx = canvas.getContext("2d");
    const grad = ctx.createLinearGradient(0, 0, 0, 760);
    grad.addColorStop(0, "#F7F3E6");
    grad.addColorStop(1, "#EFE8D4");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 640, 760);
    ctx.strokeStyle = "#D5C8A8";
    ctx.lineWidth = 4;
    ctx.strokeRect(14, 14, 612, 732);
    const title = (scroll.querySelector("h3") || {}).textContent || "朱批钤印";
    const paragraphs = scroll.querySelectorAll("p");
    const detail = (paragraphs[0] || {}).textContent || "";
    const quote = (paragraphs[1] || {}).textContent || "";
    ctx.textAlign = "center";
    ctx.fillStyle = "#262018";
    ctx.font = "600 34px 'Noto Serif SC', serif";
    ctx.fillText(title, 320, 140);
    ctx.font = "16px sans-serif";
    ctx.fillStyle = "#5A5144";
    ctx.fillText(detail, 320, 190, 540);
    ctx.fillStyle = "#A63424";
    ctx.fillRect(250, 250, 140, 140);
    ctx.strokeStyle = "#F7F1E3";
    ctx.lineWidth = 2;
    ctx.strokeRect(262, 262, 116, 116);
    const chars = SEAL_CHARS[activeSealKey] || "笔驭印印";
    ctx.fillStyle = "#F7F1E3";
    ctx.font = "700 34px serif";
    ctx.fillText(chars[0], 285, 310);
    ctx.fillText(chars[1], 355, 310);
    ctx.fillText(chars[2], 285, 370);
    ctx.fillText(chars[3], 355, 370);
    ctx.fillStyle = "#2E2820";
    ctx.font = "18px serif";
    const lines = quote.match(/.{1,26}/g) || [];
    lines.forEach((line, i) => ctx.fillText(line, 320, 470 + i * 34, 540));
    ctx.fillStyle = "#827868";
    ctx.font = "13px sans-serif";
    ctx.fillText("笔驭 biyu · 本地优先 AI 网文工作站 | 内测作者群：892467108", 320, 700);
    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "笔驭里程碑_" + title + ".png";
      a.click();
      URL.revokeObjectURL(url);
    });
  }

  function renderHomestead() {
    Promise.all([
      fetch("/api/homestead/stats").then((r) => r.json()),
      fetch("/api/seals/state").then((r) => r.json()),
    ]).then((payload) => {
      const stats = payload[0];
      sealState = payload[1];
      const card = $("homestead-card");
      if (!card) return;
      $("homestead-streak").textContent = "连续耕读 " + stats.streak_days + " 天";
      $("homestead-intercepted").textContent = "累计拦截 " + stats.intercepted_count + " 处 AI 翻译腔与套话";
      $("homestead-week-words").textContent = stats.week_words.toLocaleString() + " 字";
      $("homestead-approved").textContent = stats.approved_chapters + " 章";
      $("seal-count").textContent = sealState.achieved_count;
      const heat = $("homestead-heatmap");
      heat.replaceChildren(document.createTextNode("近 14 日手稿热力："));
      stats.heatmap.forEach((day) => {
        const cell = document.createElement("span");
        cell.className = "cal-heatmap-cell cal-lv-" + day.level;
        cell.title = day.label + "：" + day.words + " 字";
        const d = document.createElement("span");
        d.textContent = day.label.slice(3);
        const w = document.createElement("span");
        w.style.fontSize = "9px";
        w.textContent = day.words > 0 ? (day.words / 1000).toFixed(1) + "k" : "休";
        cell.append(d, w);
        heat.appendChild(cell);
      });
      card.hidden = false;
    }).catch(() => { /* 统计失败静默隐藏卡片,不阻塞书架 */ });
  }

  function wireExperienceLayer() {
    ["manual-create-button", "manual-create-empty-button", "welcome-manual-button"].forEach((id) => {
      const btn = $(id);
      if (!btn) return;
      btn.addEventListener("click", () => {
        $("create-book-overlay").hidden = false;
        $("create-book-title").focus();
      });
    });
    const keyGuideBtn = $("key-guide-button");
    if (keyGuideBtn) keyGuideBtn.addEventListener("click", openKeyGuide);
    wireKeyGuide();

    const sealBtn = $("seal-open-button");
    if (sealBtn) sealBtn.addEventListener("click", openSeals);
    const sealsOverlay = $("seals-overlay");
    if (sealsOverlay) {
      $("seals-close").addEventListener("click", () => { sealsOverlay.hidden = true; });
      sealsOverlay.addEventListener("click", (event) => {
        if (event.target === sealsOverlay) sealsOverlay.hidden = true;
      });
      $("seal-copy").addEventListener("click", () => {
        const seal = (sealState && sealState.seals || []).find((s) => s.key === activeSealKey);
        const text = "【笔驭 · 朱批钤印】我达成了「" + ((seal && seal.title) || "里程碑") +
          "」！机器起草、作者钦定，本地优先的 AI 网文工作站。内测作者群：892467108";
        if (navigator.clipboard) navigator.clipboard.writeText(text);
        $("seal-copy").textContent = "已复制 ✓";
        setTimeout(() => { $("seal-copy").textContent = "📋 复制群晒单文案"; }, 1600);
      });
      $("seal-save-poster").addEventListener("click", saveSealPoster);
    }

    const toggle = $("homestead-toggle");
    if (toggle) toggle.addEventListener("click", () => {
      const area = $("homestead-heatmap-area");
      const collapsed = area.style.display === "none";
      area.style.display = collapsed ? "flex" : "none";
      toggle.textContent = collapsed ? "收起日历 ▴" : "展开耕读日历 ▾";
      toggle.setAttribute("aria-expanded", String(collapsed));
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    wireExperienceLayer();
    Promise.all([
      fetch("/api/books").then((r) => r.json()),
      fetch("/api/setup/status").then((r) => r.json()),
    ]).then((payload) => {
      const books = payload[0].books || [];
      if (books.length === 0) return; // 图纸:迎宾条与耕读历仅在「有书态」注入
      renderWelcome(Boolean(payload[1].ready));
      renderHomestead();
    }).catch(() => { /* 体验层失败不影响书架主流程 */ });
  });
})();
