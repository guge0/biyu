/* P8-M3 T2 编辑部对话壳 — 会话 + SSE 流式 + 工具亮牌 + 角色切换 + 历史侧栏。
 *
 * API 依赖(T1 会话基座):
 *   POST   /api/chat/sessions              — 新建会话
 *   GET    /api/chat/sessions              — 会话列表
 *   GET    /api/chat/sessions/{id}         — 会话详情(含消息)
 *   POST   /api/chat/sessions/{id}/messages — 发送消息(SSE)
 *   DELETE /api/chat/sessions/{id}         — 软删除
 */
(function () {
  "use strict";

  // ---------- 状态 ----------
  let currentSessionId = null;   // 当前选中会话
  let currentBook = "";
  let currentRole = "editor";
  let sessions = [];            // 侧栏会话列表
  let books = [];               // 书列表(下拉用)
  let abortController = null;   // 用于中断当前 SSE 流

  // ---------- DOM ----------
  const $ = (id) => document.getElementById(id);

  const envBadge = $("env-badge");
  const envLabel = $("env-label");
  const peakBadge = $("peak-badge");
  const peakLabel = $("peak-label");
  const errorBanner = $("error-banner");
  const placeholderBanner = $("placeholder-banner");

  // 侧栏
  const bookSelect = $("book-select");
  const roleSelect = $("role-select");
  const newSessionBtn = $("new-session-btn");
  const sessionList = $("session-list");

  // 聊天区
  const chatHeader = $("chat-header");
  const chatBookRole = $("chat-book-role");
  const chatCostDisplay = $("chat-cost-display");
  const messageList = $("message-list");
  const chatPlaceholder = $("chat-placeholder");
  const inputArea = $("input-area");
  const chatInput = $("chat-input");
  const sendBtn = $("send-btn");

  // ---------- 初始化 ----------
  async function init() {
    try {
      const [envResp, peakResp, booksResp, modeResp] = await Promise.all([
        fetch("/api/env"),
        fetch("/api/peak-hours"),
        fetch("/api/books"),
        fetch("/api/chat/mode"),
      ]);
      renderEnv(await envResp.json());
      renderPeak(await peakResp.json());
      // F3 (P8-M3R-fix):/api/books 返 dict schema {books, count}
      books = (await booksResp.json()).books;
      populateBookSelect(books);
      // R5 T5.4:横幅根据真实模式显示
      renderModeBanner(await modeResp.json());
      // 初始加载时以选中书过滤会话
      await refreshSessions();
    } catch (e) {
      showError("初始化失败:" + e.message);
    }
  }

  // ---------- R5 T5.4:横幅反映真实模式(黄=占位 / 绿=真 LLM) ----------
  function renderModeBanner(mode) {
    if (!placeholderBanner) return;
    placeholderBanner.hidden = false;
    placeholderBanner.classList.remove("banner-real", "banner-placeholder", "banner-mixed");
    const level = mode.level || "placeholder";
    const label = mode.label || "";
    if (level === "real") {
      placeholderBanner.classList.add("banner-real");
      placeholderBanner.innerHTML =
        '<strong>✓ 真实 LLM 模式</strong> · ' + escapeHtml(label) +
        ' · 责编/导演会调真模型(花费入 cost_log.csv,D-93)';
    } else if (level === "mixed") {
      placeholderBanner.classList.add("banner-mixed");
      placeholderBanner.innerHTML =
        '<strong>⚠ 混合模式</strong> · ' + escapeHtml(label) +
        ' · 部分角色仍在占位(PLACEHOLDER_FLAGS 未翻 False)';
    } else {
      placeholderBanner.classList.add("banner-placeholder");
      placeholderBanner.innerHTML =
        '<strong>⚠ 占位模式</strong> · ' + escapeHtml(label) +
        ' · 当前仅代查资料,编辑人格未接真 LLM(PLACEHOLDER_FLAGS=True)';
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ---------- 按书过滤刷新会话 ----------
  async function refreshSessions() {
    const book = bookSelect.value;
    // R6 T6.3:UI 默认隐 source=test 会话;不传 include_test=true → 后端默认 include_test=False
    // 双保险:即便后端返了 test 会话(理论不会),前端也过滤掉
    const url = book ? "/api/chat/sessions?book=" + encodeURIComponent(book) : "/api/chat/sessions";
    try {
      const resp = await fetch(url);
      if (resp.ok) {
        const allSessions = (await resp.json()).sessions || [];
        // 前端兜底过滤:source === "test" 不显
        sessions = allSessions.filter(function (s) { return s.source !== "test"; });
        renderSessionList();
      }
    } catch (e) {
      showError("会话加载失败:" + e.message);
    }
  }

  // 书选择变更时刷新会话列表
  bookSelect.addEventListener("change", function () {
    // 清当前会话选择
    currentSessionId = null;
    resetChatArea();
    refreshSessions();
    checkArchiveStatus(bookSelect.value);
  });

  // R2 D-96:无档案提示(导入书未建档时不静默降级)
  async function checkArchiveStatus(bookId) {
    const banner = document.getElementById("archive-warning");
    if (!banner) return;
    if (!bookId) { banner.hidden = true; return; }
    try {
      const resp = await fetch("/api/books/" + encodeURIComponent(bookId) + "/archive-status");
      if (!resp.ok) { banner.hidden = true; return; }
      const status = await resp.json();
      // 无 truth_files 或无 outlines → 显提示
      if (!status.has_truth_files || !status.has_outlines) {
        banner.hidden = false;
      } else {
        banner.hidden = true;
      }
    } catch (e) {
      // 检查失败不阻塞,隐 banner
      banner.hidden = true;
    }
  }

  function renderEnv(env) {
    if (!envBadge || !envLabel) return;
    envBadge.classList.remove("env-test", "env-prod");
    envBadge.classList.add(env.level === "prod" ? "env-prod" : "env-test");
    envLabel.textContent = env.label + " · " + env.level;
  }

  function renderPeak(peak) {
    if (!peakBadge || !peakLabel) return;
    peakBadge.classList.remove("peak-pending", "peak-on", "peak-off");
    if (peak.is_peak) peakBadge.classList.add("peak-on");
    else if (peak.label && peak.label.indexOf("即将生效") >= 0) peakBadge.classList.add("peak-pending");
    else peakBadge.classList.add("peak-off");
    peakLabel.textContent = peak.label || "";
  }

  function _bookDisplayName(bookIdOrName) {
    if (!bookIdOrName || !books) return bookIdOrName || "?";
    // R1: 同时匹配 id 或 name(session.book 可能是目录名,下拉值是 id)
    const b = books.find((b) => b.id === bookIdOrName || b.name === bookIdOrName);
    return b ? (b.display_name || b.title || b.name) : bookIdOrName;
  }

  function populateBookSelect(books) {
    bookSelect.innerHTML = '<option value="">— 选择书 —</option>';
    (books || []).forEach((b) => {
      const opt = document.createElement("option");
      // R1 slug ID:option value 用 book.id(无 id 时 /api/books 回退目录名)
      opt.value = b.id;
      opt.textContent = b.display_name || b.title || b.name;
      bookSelect.appendChild(opt);
    });
  }

  // ---------- 侧栏:会话列表面 ----------
  function renderSessionList() {
    sessionList.innerHTML = "";
    if (!sessions || sessions.length === 0) {
      sessionList.innerHTML = '<div class="sidebar-empty">暂无会话,选书并开始一个新会话。</div>';
      return;
    }
    sessions.forEach((s) => {
      const item = document.createElement("div");
      item.className = "session-item";
      if (s.id === currentSessionId) item.classList.add("session-item-active");
      item.dataset.sid = s.id;

      // 角色徽标
      const roleLabel = s.role === "director" ? "导演" : "责编";
      const roleBadge = document.createElement("span");
      roleBadge.className = "session-role-badge";
      roleBadge.classList.add(s.role === "director" ? "role-director" : "role-editor");
      roleBadge.textContent = roleLabel;

      // 标题行:书 + 日期
      const titleLine = document.createElement("div");
      titleLine.className = "session-item-title";
      const bookName = _bookDisplayName(s.book) || "(未知)";
      const dateStr = formatDate(s.created_at);
      titleLine.textContent = bookName + " · " + dateStr;

      // 删除按钮
      const delBtn = document.createElement("button");
      delBtn.className = "session-del-btn";
      delBtn.textContent = "×";
      delBtn.title = "删除会话";
      delBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        await deleteSession(s.id);
      });

      item.appendChild(roleBadge);
      item.appendChild(titleLine);
      item.appendChild(delBtn);
      item.addEventListener("click", () => loadSession(s.id));
      sessionList.appendChild(item);
    });
  }

  function formatDate(ts) {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    const pad = (n) => String(n).padStart(2, "0");
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
      " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  // ---------- 新建会话 ----------
  newSessionBtn.addEventListener("click", async () => {
    const book = bookSelect.value;
    const role = roleSelect.value;
    if (!book) {
      showError("请先选择一本书");
      return;
    }
    try {
      newSessionBtn.disabled = true;
      newSessionBtn.textContent = "创建中…";
      const resp = await fetch("/api/chat/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ book, role }),
      });
      if (!resp.ok) {
        const err = (await resp.json()).detail || "创建失败";
        showError(err);
        return;
      }
      const session = await resp.json();
      sessions.unshift(session);
      renderSessionList();
      loadSession(session.id);
    } catch (e) {
      showError("创建会话失败:" + e.message);
    } finally {
      newSessionBtn.disabled = false;
      newSessionBtn.textContent = "开始新会话";
    }
  });

  // ---------- 加载会话 ----------
  async function loadSession(sid) {
    try {
      const resp = await fetch("/api/chat/sessions/" + sid);
      if (!resp.ok) {
        showError("加载会话失败");
        return;
      }
      const session = await resp.json();
      currentSessionId = session.id;
      currentBook = session.book || "";
      currentRole = session.role || "editor";

      // 刷新会话列表高亮
      renderSessionList();

      // 显示聊天区
      showChatArea(session);
    } catch (e) {
      showError("加载会话失败:" + e.message);
    }
  }

  function showChatArea(session) {
    // 聊天头
    chatHeader.hidden = false;
    const roleLabel = session.role === "director" ? "导演" : "责编";
    chatBookRole.textContent = _bookDisplayName(session.book || "?") + " · " + roleLabel;

    // 成本
    updateCostDisplay(session);

    // 渲染消息
    renderMessages(session.messages || []);

    // 显输入区
    inputArea.hidden = false;
    chatInput.disabled = false;
    chatInput.placeholder = session.role === "director"
      ? "输入你的剧情想法和特殊要求…"
      : "输入你想与责编讨论的创作问题…";
    chatInput.focus();
  }

  function updateCostDisplay(session) {
    if (!chatCostDisplay) return;
    const msgs = session.messages || [];
    let total = 0;
    msgs.forEach((m) => {
      if (m.cost != null) total += Number(m.cost);
    });
    chatCostDisplay.textContent = "¥" + total.toFixed(4);
  }

  // ---------- 渲染消息 ----------
  function renderMessages(msgs) {
    messageList.innerHTML = "";
    chatPlaceholder.hidden = true;

    if (!msgs || msgs.length === 0) {
      chatPlaceholder.hidden = false;
      chatPlaceholder.innerHTML = "<p>新会话,发送第一条消息开始对话。</p>";
      return;
    }

    msgs.forEach((msg) => {
      if (msg.role === "user") {
        appendUserMessage(msg.content);
      } else if (msg.role === "assistant") {
        appendAssistantMessage(msg.content, msg.tool_call);
      }
    });
    scrollToBottom();
  }

  function appendUserMessage(text) {
    const div = document.createElement("div");
    div.className = "msg msg-user";
    div.textContent = text;
    messageList.appendChild(div);
  }

  function appendAssistantMessage(text, toolCall) {
    const div = document.createElement("div");
    div.className = "msg msg-assistant";

    // 文本(R5 T5.2:用 mini-md.js 渲染 markdown,先 esc 后 md 防 XSS)
    const textDiv = document.createElement("div");
    textDiv.className = "msg-text";
    if (window.MiniMd && text) {
      textDiv.innerHTML = window.MiniMd.render(text);
    } else {
      textDiv.textContent = text || "";
    }
    div.appendChild(textDiv);

    // 工具亮牌(R5 T5.6:兼容两种形状)
    // - 实时 SSE:toolCall = {name, args, result}(扁平,单个)
    // - 加载历史:toolCall = {tools: [{name, args, result}, ...]}(包装,可能多个)
    //   旧版"切书回来显未命中"根因 = 形状不匹配,tc.name/args/result 全 undefined。
    if (toolCall) {
      const cards = renderToolCallCards(toolCall);
      cards.forEach((c) => div.appendChild(c));
    }

    messageList.appendChild(div);
  }

  // R5 T5.6:统一渲染工具卡,兼容扁平 / 包装两种形状
  function renderToolCallCards(toolCall) {
    if (!toolCall) return [];
    // 包装形状:{tools: [...]}
    if (toolCall.tools && Array.isArray(toolCall.tools)) {
      return toolCall.tools.filter((t) => t && typeof t === "object").map(renderToolCallCard);
    }
    // 扁平形状:{name, args, result}
    if (toolCall.name || toolCall.args || Object.prototype.hasOwnProperty.call(toolCall, "result")) {
      return [renderToolCallCard(toolCall)];
    }
    // 未知形状:不渲染(避免错误显示)
    return [];
  }

  // ---------- 工具亮牌卡 ----------
  function renderToolCallCard(tc) {
    const card = document.createElement("div");
    card.className = "tool-call-card";

    // 工具名
    const nameLine = document.createElement("div");
    nameLine.className = "tool-call-name";
    nameLine.textContent = "🔧 " + (tc.name || "工具调用");
    card.appendChild(nameLine);

    // 参数摘要(始终显)
    const argsStr = summarizeArgs(tc.args);
    const argsLine = document.createElement("div");
    argsLine.className = "tool-call-args";
    argsLine.textContent = "参数: " + (argsStr || "(无参数)");
    card.appendChild(argsLine);

    // 结果摘要(≤3 行,空则显"未命中")
    const rawResult = tc.result;
    const resultDisplay = (rawResult != null && rawResult !== "")
      ? String(rawResult)
      : "未命中";
    const truncated = resultDisplay.length > 120
      ? resultDisplay.slice(0, 117) + "…"
      : resultDisplay;
    const resultLine = document.createElement("div");
    resultLine.className = "tool-call-result";
    resultLine.textContent = "结果: " + truncated;
    card.appendChild(resultLine);

    return card;
  }

  function summarizeArgs(args) {
    if (!args) return "";
    if (typeof args === "string") return args.length > 60 ? args.slice(0, 57) + "…" : args;
    try {
      const pairs = Object.entries(args).map(([k, v]) => {
        const val = typeof v === "object" ? JSON.stringify(v) : String(v);
        return k + "=" + (val.length > 40 ? val.slice(0, 37) + "…" : val);
      });
      return pairs.join(", ").slice(0, 80);
    } catch (_) {
      return String(args).slice(0, 60);
    }
  }

  // ---------- SSE 发送消息 ----------
  sendBtn.addEventListener("click", handleSend);
  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  });

  async function handleSend() {
    const text = chatInput.value.trim();
    if (!text || !currentSessionId) return;

    chatInput.value = "";
    setSending(true);

    // 立即回显用户消息
    appendUserMessage(text);
    scrollToBottom();

    // 创建助理消息占位(R5 T5.2:思考中… + spinner)
    const assistantDiv = document.createElement("div");
    assistantDiv.className = "msg msg-assistant";
    const textDiv = document.createElement("div");
    textDiv.className = "msg-text msg-thinking";
    textDiv.innerHTML = '<span class="spinner spinner-dark"></span><span style="color:var(--ink-dim);font-style:italic;">思考中…</span>';
    assistantDiv.appendChild(textDiv);
    messageList.appendChild(assistantDiv);
    scrollToBottom();

    let firstTokenReceived = false;
    let assistantText = "";
    // R5 T5.6:多工具支持(后端可能 emit 多个 tool_call SSE)
    let toolCallList = [];

    try {
      abortController = new AbortController();
      const resp = await fetch("/api/chat/sessions/" + currentSessionId + "/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: text }),
        signal: abortController.signal,
      });

      if (!resp.ok) {
        let detail = "发送失败(HTTP " + resp.status + ")";
        try { detail = (await resp.json()).detail || detail; } catch (_) {}
        showPersistentError("发送失败:" + detail);
        assistantDiv.remove();
        return;
      }

      // SSE 解析
      const reader = resp.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let sep;
        while ((sep = buffer.indexOf("\n\n")) >= 0) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          const evt = parseSseFrame(frame);
          if (!evt) continue;

          if (evt.type === "token") {
            if (!firstTokenReceived) {
              firstTokenReceived = true;
              textDiv.classList.remove("msg-thinking");
              textDiv.innerHTML = "";
            }
            assistantText += evt.content || "";
            // 流式期间显纯文本(性能 + 防 XSS:textContent 安全)
            textDiv.textContent = assistantText;
            scrollToBottom();
          } else if (evt.type === "tool_call") {
            // R5 T5.6:收集所有工具调用(后端每个工具 emit 一次)
            toolCallList.push({ name: evt.name, args: evt.args, result: evt.result });
          } else if (evt.type === "cost") {
            // 刷新成本显示
            refreshCost();
          } else if (evt.type === "error") {
            showPersistentError("响应异常:" + (evt.message || "(未提供错误信息)"));
          }
        }
      }

      // SSE 中断检测:有响应但没拿到任何 token 也没 tool_call
      if (!firstTokenReceived && toolCallList.length === 0) {
        showPersistentError("SSE 中断:服务端未发送任何 token 就关闭(可能超时或网络异常)。");
        assistantDiv.remove();
        return;
      }

      // 流结束后:渲染 markdown(R5 T5.2:先 esc 后 md 防 XSS)
      if (firstTokenReceived && window.MiniMd) {
        textDiv.innerHTML = window.MiniMd.render(assistantText);
      } else if (!firstTokenReceived) {
        // 没有 token(可能只有 tool_call),清空思考占位
        textDiv.textContent = "";
      }

      // 工具亮牌(全部,R5 T5.6:多工具支持)
      toolCallList.forEach((tc) => {
        assistantDiv.appendChild(renderToolCallCard(tc));
      });
    } catch (e) {
      if (e.name === "AbortError") {
        showPersistentError("已取消发送(AbortError)。");
        return;
      }
      showPersistentError("网络异常:" + e.message + "(SSE 可能已中断,请重试)");
      assistantDiv.remove();
    } finally {
      setSending(false);
      abortController = null;
    }
  }

  function parseSseFrame(frame) {
    const lines = frame.split("\n");
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data:")) continue;
      const payload = trimmed.slice(5).trim();
      if (payload === "[DONE]") return null;
      try { return JSON.parse(payload); } catch (_) { return null; }
    }
    return null;
  }

  // ---------- 刷新成本 ----------
  async function refreshCost() {
    if (!currentSessionId) return;
    try {
      const resp = await fetch("/api/chat/sessions/" + currentSessionId);
      if (resp.ok) {
        const session = await resp.json();
        updateCostDisplay(session);
      }
    } catch (_) {}
  }

  // ---------- 删除会话 ----------
  async function deleteSession(sid) {
    try {
      const resp = await fetch("/api/chat/sessions/" + sid, { method: "DELETE" });
      if (!resp.ok) return;
      sessions = sessions.filter((s) => s.id !== sid);
      if (currentSessionId === sid) {
        currentSessionId = null;
        resetChatArea();
      }
      renderSessionList();
    } catch (e) {
      showError("删除失败:" + e.message);
    }
  }

  function resetChatArea() {
    chatHeader.hidden = true;
    messageList.innerHTML = "";
    chatPlaceholder.hidden = false;
    chatPlaceholder.innerHTML = "<p>选择一本书和角色,点击「开始新会话」,或从左侧选择一个已有会话。</p>";
    inputArea.hidden = true;
  }

  // ---------- 工具 ----------
  function setSending(loading) {
    sendBtn.disabled = loading;
    sendBtn.querySelector(".btn-label").hidden = loading;
    sendBtn.querySelector(".btn-loading").hidden = !loading;
    chatInput.disabled = loading;
  }

  // 兼容旧调用:showError 走持久 banner(R5 T5.2:不再 6 秒消失)
  function showError(msg) {
    showPersistentError(msg);
  }

  // R5 T5.2:持久错误 banner,需用户手动关闭(不再 6 秒消失)
  function showPersistentError(msg) {
    if (!errorBanner) return;
    const safeMsg = window.MiniMd ? window.MiniMd.esc(msg) : String(msg).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
    errorBanner.innerHTML =
      '<div class="error-banner-row">' +
      '<span class="error-banner-icon">✗</span>' +
      '<span class="error-banner-msg">' + safeMsg + '</span>' +
      '<button class="error-banner-close" type="button" aria-label="关闭">×</button>' +
      '</div>';
    errorBanner.hidden = false;
    const closeBtn = errorBanner.querySelector(".error-banner-close");
    if (closeBtn) {
      closeBtn.addEventListener("click", function () {
        errorBanner.hidden = true;
      });
    }
  }

  function clearError() {
    if (errorBanner) {
      errorBanner.hidden = true;
      errorBanner.innerHTML = "";
    }
  }

  function scrollToBottom() {
    messageList.scrollTop = messageList.scrollHeight;
  }

  // ---------- 启动 ----------
  document.addEventListener("DOMContentLoaded", init);
})();
