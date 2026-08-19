/* P8-M1 立项屏 — 原生 JS,无依赖。
 *
 * 流程:
 * 1. 页面加载 → 拉 /api/env 渲染右上环境章;拉 /api/session 拿 session_id
 * 2. 作者输入想法 → 点"体检" → POST /api/propose
 * 3. 三路径差异化渲染卡片(SPECIFIC/DIRECTIONAL/EMPTY)
 * 4. 各块按 source 字段渲染失败/降级态(D-70 出声)
 * 5. 软顶触发 → 200 + status="softcap_reached" → 弹确认框 → 用户同意后重发带 confirm
 */
(function () {
  "use strict";

  let sessionId = null;
  let cumulativeCost = 0;
  let softcapCny = 2.0;
  let lastRequest = null; // 用于软顶确认后重发

  // ---------- DOM ----------
  const $ = (id) => document.getElementById(id);
  const envBadge = $("env-badge");
  const envLabel = $("env-label");
  const submitBtn = $("submit-btn");
  const rescanBtn = $("rescan-btn");
  const ideaInput = $("idea-input");
  const sessionCostEl = $("session-cost");
  const cumulativeCostEl = $("cumulative-cost");
  const errorBanner = $("error-banner");
  const resultArea = $("result-area");
  const softcapModal = $("softcap-modal");
  const softcapModalText = $("softcap-modal-text");
  const scanCacheBadge = $("scan-cache-badge");

  // ---------- 初始化 ----------
  async function init() {
    try {
      const [envResp, sessResp, peakResp] = await Promise.all([
        fetch("/api/env"),
        fetch("/api/session"),
        fetch("/api/peak-hours"),
      ]);
      const env = await envResp.json();
      renderEnv(env);
      const sess = await sessResp.json();
      sessionId = sess.session_id;
      const peak = await peakResp.json();
      renderPeak(peak);
    } catch (e) {
      showError("环境或会话初始化失败:" + e.message + "。请刷新或检查服务。");
    }
  }

  function renderPeak(peak) {
    const badge = $("peak-badge");
    const label = $("peak-label");
    const hint = $("peak-hint");
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
    if (hint) {
      hint.textContent = peak.is_peak ? " · 当前" + peak.label : "";
    }
  }

  function renderEnv(env) {
    envBadge.classList.remove("env-test", "env-prod");
    envBadge.classList.add(env.level === "prod" ? "env-prod" : "env-test");
    envLabel.textContent = env.label + " · " + env.level;
    envBadge.title = "当前运行环境:" + env.label + "(BIYU_ENV=" + env.level + ")";
  }

  // ---------- 提交 ----------
  submitBtn.addEventListener("click", handleSubmit);

  // T4 重新扫榜按钮:强制现扫
  rescanBtn.addEventListener("click", () => {
    const idea = ideaInput.value.trim();
    lastRequest = { idea, name: null, confirm_over_softcap: false, force_refresh_scan: true };
    runPropose(lastRequest);
  });

  async function handleSubmit() {
    const idea = ideaInput.value.trim();
    lastRequest = { idea, name: null, confirm_over_softcap: false, force_refresh_scan: false };
    await runPropose(lastRequest);
  }

  // T3 stage 中文标签(spec line 11)
  const STAGE_LABELS = {
    scan: "扫榜",
    router: "路径判断",
    tropes: "套路归纳",
    redblue: "红蓝海",
    craft: "创作规律",
    done: "完成",
  };

  // 进度列表(T3)
  const progressList = $("progress-list");

  function resetProgress() {
    progressList.innerHTML = "";
    progressList.hidden = false;
  }

  function appendProgressItem(stage) {
    const li = document.createElement("li");
    li.className = "progress-item pi-active";
    li.dataset.stage = stage;
    li.innerHTML =
      '<span class="pi-icon"></span>' +
      '<span class="pi-stage">' + esc(STAGE_LABELS[stage] || stage) + "</span>" +
      '<span class="pi-status">进行中…</span>' +
      '<span class="pi-cost"></span>';
    progressList.appendChild(li);
    return li;
  }

  function updateProgressItem(li, evt) {
    if (!li) return;
    li.classList.remove("pi-active");
    if (evt.status === "done") {
      li.classList.add("pi-done");
      li.querySelector(".pi-status").textContent = "完成";
      if (typeof evt.cost_cny === "number") {
        li.querySelector(".pi-cost").textContent = formatMoney(evt.cost_cny);
      }
    } else if (evt.status === "failed") {
      li.classList.add("progress-failed");
      const err = evt.error || "失败";
      li.querySelector(".pi-status").textContent = "失败:" + err;
    }
  }

  async function runPropose(req) {
    setLoading(true);
    hideError();
    resetProgress();
    try {
      const resp = await fetch("/api/propose/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          idea: req.idea,
          name: req.name,
          session_id: sessionId,
          confirm_over_softcap: req.confirm_over_softcap,
          force_refresh_scan: !!req.force_refresh_scan,
        }),
      });

      if (!resp.ok) {
        // 非 SSE 错误(如 404/500 同步响应)
        let detail = "生成失败(HTTP " + resp.status + ")";
        try { detail = (await resp.json()).detail || detail; } catch (_) {}
        showError(detail);
        return;
      }

      // SSE 解析:从 response.body 读 chunk,按 \\n\\n 切帧
      const reader = resp.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      let finalResult = null;
      const stageItems = {};

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // 按 \n\n 切帧
        let sep;
        while ((sep = buffer.indexOf("\n\n")) >= 0) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          const evt = parseSseFrame(frame);
          if (!evt) continue;
          if (evt.type === "progress") {
            handleProgressEvent(evt, stageItems);
          } else if (evt.type === "result") {
            finalResult = evt;
          } else if (evt.type === "error") {
            showError(evt.message || evt.error || "生成失败,请重试。");
            return;
          }
        }
      }

      if (!finalResult) {
        showError("未收到结果(流被截断),请重试。");
        return;
      }

      // 软顶拦截 → 弹确认框(result 含 status=softcap_reached)
      if (finalResult.status === "softcap_reached") {
        showSoftcapModal(finalResult);
        return;
      }

      renderResult(finalResult);
      renderScanCacheBadge(finalResult.scan_cache || {});
    } catch (e) {
      showError("网络异常:" + e.message + "。请检查服务是否在跑。");
    } finally {
      setLoading(false);
    }
  }

  function parseSseFrame(frame) {
    // 形如 "data: {...}" 或 "data: [DONE]";剥前缀,JSON parse
    const lines = frame.split("\n");
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data:")) continue;
      const payload = trimmed.slice(5).trim();
      if (payload === "[DONE]") return null;
      try {
        return JSON.parse(payload);
      } catch (_) {
        return null;
      }
    }
    return null;
  }

  function handleProgressEvent(evt, stageItems) {
    const stage = evt.stage;
    if (!stage) return;
    if (evt.status === "start") {
      if (!stageItems[stage]) {
        stageItems[stage] = appendProgressItem(stage);
      }
    } else if (evt.status === "done" || evt.status === "failed") {
      // 防御性:若漏了 start 事件(done/failed 先到),惰性建行
      if (!stageItems[stage]) {
        stageItems[stage] = appendProgressItem(stage);
      }
      updateProgressItem(stageItems[stage], evt);
      // scan done 时也可早一步刷缓存徽标
      if (stage === "scan" && evt.status === "done") {
        renderScanCacheBadge({
          cached: evt.cached === true,
          cache_date: evt.cache_date || null,
          warning: null,
        });
      }
    }
  }

  function renderScanCacheBadge(meta) {
    if (!scanCacheBadge) return;
    if (!meta || (!meta.cache_date && !meta.warning)) {
      scanCacheBadge.hidden = true;
      return;
    }
    scanCacheBadge.hidden = false;
    scanCacheBadge.classList.remove("cache-hit", "cache-fresh", "cache-warn");
    if (meta.warning) {
      scanCacheBadge.classList.add("cache-warn");
      scanCacheBadge.innerHTML =
        '<span class="cache-icon">⚠️</span>' + esc(meta.warning);
    } else if (meta.cached) {
      scanCacheBadge.classList.add("cache-hit");
      scanCacheBadge.innerHTML =
        '<span class="cache-icon">📊</span>榜单数据 · ' + esc(meta.cache_date || "") + " · 缓存";
    } else {
      scanCacheBadge.classList.add("cache-fresh");
      scanCacheBadge.innerHTML =
        '<span class="cache-icon">📊</span>榜单数据 · ' + esc(meta.cache_date || "") + " · 现扫";
    }
  }

  // ---------- 渲染结果 ----------
  function renderResult(data) {
    resultArea.hidden = false;

    // R7 T7.2:缓存当前 result 给后续 renderAnalysis/renderHotGenre 查证据链用
    currentResult = data;

    // 路径行
    renderPathLine(data);

    // 红蓝海(SPECIFIC 才有)
    renderRedBlue(data);

    // 市场套路归纳
    renderAnalysis(data.analysis);

    // 创作规律
    renderCraft(data.craft);

    // 诚实声明
    $("honesty-note").textContent = data.honesty_note || "";

    // 元数据
    renderMeta(data);

    // 会话累计成本
    if (data.cumulative_cost_cny !== undefined) {
      cumulativeCost = data.cumulative_cost_cny;
      softcapCny = data.softcap_cny || 2.0;
      updateSessionCost();
    }

    // 滚到结果
    resultArea.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderPathLine(data) {
    const pathLabels = {
      specific: "具体想法 · 走红蓝海对照",
      directional: "半方向 · 走方向归纳",
      empty: "未填想法 · 看纯市场行情",
    };
    const label = pathLabels[data.path] || data.path;
    const routerCost = data.router ? formatMoney(data.router.cost_cny) : "—";
    // R7 T7.3:半方向(DIRECTIONAL)收敛——显"判断 + 一句证据 + 下一步建议"
    const nextStepHtml = renderPathNextStep(data);
    $("path-line").innerHTML =
      '<span class="path-tag">' + esc(data.path) + "</span>" +
      esc(label) +
      '<span class="path-money path-cost">本次合计 ' +
      formatMoney(data.total_cost_cny) + " · 耗时 " +
      (data.elapsed_seconds || 0).toFixed(1) + "s</span>" +
      nextStepHtml;
  }

  // R7 T7.3:三路径差异化的"下一步建议"
  function renderPathNextStep(data) {
    if (!data || !data.path) return "";
    const nextSteps = {
      specific: '<div class="path-next-step"><span class="next-label">下一步:</span>具体想法已走红蓝海,可点下方「给它起名」直接立项。</div>',
      directional: '<div class="path-next-step"><span class="next-label">下一步:</span>半方向已识别题材,但具体设定不足。建议<b>补充主角特征 / 核心冲突 / 关键设定</b>后重跑,可走红蓝海对照(更准)。</div>',
      empty: '<div class="path-next-step"><span class="next-label">下一步:</span>未填想法,当前是纯市场行情视角。有具体设想后填入上方输入框重跑,可得定制化分析。</div>',
    };
    return nextSteps[data.path] || "";
  }

  function renderRedBlue(data) {
    const card = $("redblue-card");
    const warn = $("risk-warning");
    const body = $("redblue-body");

    if (data.path !== "specific" || !data.redblue) {
      card.hidden = true;
      warn.hidden = true;
      return;
    }
    card.hidden = false;

    const rb = data.redblue;
    if (rb.source !== "llm") {
      // 失败/降级
      body.innerHTML =
        '<div class="redblue-fallback">⚠️ 本次红蓝海对照未生成(' +
        sourceLabel(rb.source) + "),可重跑。</div>";
      warn.hidden = true;
      return;
    }

    // 象限徽章(死海/荒漠显红色 risk)
    const riskQuadrants = ["死海", "荒漠"];
    const isRisk = riskQuadrants.includes(rb.quadrant);
    const badgeClass = isRisk ? "q-risk" : "q-normal";
    const quadrantDesc = {
      "红海": "多人写多人看",
      "蓝海": "少人写多人看",
      "死海": "多人写少人看",
      "荒漠": "少人写少人看(警示:没人写可能因为没人看)",
    }[rb.quadrant] || "";

    // R7 T7.4:四象限"这对你意味着什么"人话注解
    const quadrantMeaning = {
      "红海": "竞争激烈,要靠差异化(人物、设定、节奏)杀出来;题材本身有读者基础,但同质化风险高。",
      "蓝海": "题材有受众但供给少,机会窗口好;但仍需验证「少人写」是真需求还是伪需求——可能因为难写或冷门。",
      "死海": "供给过剩但需求弱,典型红海内卷;不建议跟风,除非有强差异化破局点。",
      "荒漠": "没人写也没人看,题材冷门风险高;除非你有特殊理由(个人兴趣 / 垂直读者 / 实验性),否则慎重。",
    }[rb.quadrant] || "";

    body.innerHTML =
      '<div class="quadrant-badge ' + badgeClass + '">' +
      esc(rb.quadrant || "(未归类)") + " · " + esc(quadrantDesc) + "</div>" +
      (quadrantMeaning ? '<div class="quadrant-meaning"><span class="meaning-label">这对你意味着:</span>' + esc(quadrantMeaning) + '</div>' : '') +
      '<div class="redblue-row"><span class="row-label">供给拥挤度:</span>' +
      esc(rb.supply_crowding) + "</div>" +
      '<div class="redblue-row"><span class="row-label">同类在榜弱信号:</span>' +
      esc(rb.demand_weak_signal) + "</div>";

    // 死海/荒漠显风险警示
    if (isRisk) {
      warn.hidden = false;
      warn.textContent = "⚠️ 象限定性为「" + rb.quadrant +
        "」:供给侧或需求侧存在明显弱势,建议结合行业经验慎重判断。";
    } else {
      warn.hidden = true;
    }
  }

  function renderAnalysis(analysis) {
    const body = $("analysis-body");
    if (!analysis) {
      body.innerHTML = '<div class="redblue-fallback">⚠️ 市场套路归纳数据缺失。</div>';
      return;
    }
    if (analysis.source !== "llm") {
      body.innerHTML =
        '<div class="redblue-fallback">⚠️ 市场套路归纳未生成(' +
        sourceLabel(analysis.source) + "),可重跑。</div>";
      return;
    }

    let html = "";
    // R7 T7.2:证据链元数据(扫榜日期 + 平台 + 缓存状态)
    html += renderEvidenceHeader(currentResult);
    if (analysis.hot_genres && analysis.hot_genres.length) {
      html += "<h3>热门题材</h3>";
      analysis.hot_genres.forEach((g) => {
        html += renderHotGenreWithEvidence(g, currentResult);
      });
    }
    if (analysis.hot_tropes && analysis.hot_tropes.length) {
      html += "<h3>横切套路要素</h3><ul>";
      analysis.hot_tropes.forEach((t) => {
        html += "<li>" + esc(t) + "</li>";
      });
      html += "</ul>";
    }
    if (analysis.market_summary) {
      html += "<h3>行情概括</h3><p>" + esc(analysis.market_summary) + "</p>";
    }
    body.innerHTML = html;
  }

  // R7 T7.2 + T7.5:证据链渲染 helpers ============
  // currentResult 缓存:renderResult 时存,后续 renderAnalysis 可读
  let currentResult = null;

  function renderEvidenceHeader(data) {
    // T7.5 兜底:scan_cache 缺失 → 显式标"证据链不全"
    if (!data || !data.scan_cache) {
      return '<div class="evidence-header evidence-missing">' +
        '<span class="evidence-icon">⚠️</span>' +
        '<span>扫榜缓存缺失,证据链不全(数据来自早期 propose,无 scan_cache 字段)。</span>' +
        '</div>';
    }
    const sc = data.scan_cache || {};
    const cacheDate = sc.cache_date || "";
    const cached = sc.cached;
    const platformLabels = sc.platform_labels || {};
    const platformText = Object.keys(platformLabels).length
      ? Object.values(platformLabels).join(" + ")
      : "(平台未提供)";
    if (!cacheDate) {
      return '<div class="evidence-header evidence-missing">' +
        '<span class="evidence-icon">⚠️</span>' +
        '<span>扫榜日期缺失,证据链不全(缓存元数据无 cache_date)。</span>' +
        '</div>';
    }
    const cacheMode = cached ? "缓存命中" : "现扫";
    return '<div class="evidence-header">' +
      '<span class="evidence-icon">📊</span>' +
      '<span>扫榜日期:<b>' + esc(cacheDate) + '</b> · 平台:' + esc(platformText) +
      ' · ' + esc(cacheMode) + '</span>' +
      '</div>';
  }

  function renderHotGenreWithEvidence(g, data) {
    const titles = g.sample_titles || [];
    const titleIndex = (data && data.scan_cache && data.scan_cache.title_rank_index) || {};
    const platformLabels = (data && data.scan_cache && data.scan_cache.platform_labels) || {};

    // 每个 title 旁显榜位(若查到)
    let titlesHtml = "";
    if (titles.length === 0) {
      // T7.5 兜底:LLM 未提取代表作品
      titlesHtml = '<div class="genre-titles evidence-missing">代表作品:(LLM 未提取,证据链不全)</div>';
    } else {
      const titleItems = titles.map((t) => {
        const rankInfo = lookupRank(t, titleIndex, platformLabels);
        return '<span class="title-with-rank">' +
          '《' + esc(t) + '》' +
          (rankInfo ? '<span class="rank-badge">' + esc(rankInfo) + '</span>' : '<span class="rank-unknown" title="LLM 给的书名在扫榜缓存中未找到">(榜位未知)</span>') +
          '</span>';
      });
      titlesHtml = '<div class="genre-titles">代表作品:' + titleItems.join("、") + '</div>';
    }

    return '<div class="hot-genre">' +
      '<div><span class="genre-name">' + esc(g.genre || "(未命名)") + "</span>" +
      '<span class="genre-heat">' + esc(g.heat_signal || "") + "</span></div>" +
      titlesHtml +
      "</div>";
  }

  function lookupRank(title, titleIndex, platformLabels) {
    // 遍历所有平台,返第一个命中的 "{平台中文} #{rank}"(可能有多个平台都命中,只显首个)
    for (const platformCode of Object.keys(titleIndex)) {
      const rank = titleIndex[platformCode][title];
      if (rank != null) {
        const label = platformLabels[platformCode] || platformCode;
        return label + " #" + rank;
      }
    }
    return null;
  }

  function renderCraft(craft) {
    const body = $("craft-body");
    if (!craft) {
      body.innerHTML = '<div class="redblue-fallback">⚠️ 创作规律数据缺失。</div>';
      return;
    }
    let note = "";
    if (craft.source === "template_fallback") {
      note = '<div class="craft-fallback-note">⚠️ LLM 失败,已降级到蒸馏模板。</div>';
    } else if (craft.source === "template") {
      note = '<div class="craft-fallback-note">未调 LLM,使用蒸馏模板。</div>';
    }
    body.innerHTML = note + miniMarkdown(craft.markdown || "");
  }

  function renderMeta(data) {
    const metaBody = $("meta-body");
    const lines = [
      "总成本:" + formatMoney(data.total_cost_cny),
      "耗时:" + (data.elapsed_seconds || 0).toFixed(2) + " 秒",
      "模型:" + (data.model_alias || "(未记录)"),
      "套路归纳来源:" + sourceLabel(data.analysis?.source),
      "红蓝海来源:" + (data.redblue ? sourceLabel(data.redblue.source) : "(未走该路径)"),
      "创作规律来源:" + sourceLabel(data.craft?.source),
      "落盘路径:" + (data.out_path || "(未记录)"),
      "本次会话累计:" + formatMoney(data.cumulative_cost_cny ?? cumulativeCost),
    ];
    metaBody.innerHTML = lines.map((l) => "<div>" + esc(l) + "</div>").join("");
  }

  // ---------- 软顶弹窗 ----------
  function showSoftcapModal(data) {
    softcapModalText.textContent =
      "本次会话已累计 " + formatMoney(data.cumulative_cost_cny) +
      ",达到软顶 " + formatMoney(data.softcap_cny) +
      "。继续生成会再花约 ¥0.10。是否继续?";
    softcapModal.hidden = false;
  }

  $("softcap-cancel").addEventListener("click", () => {
    softcapModal.hidden = true;
    setLoading(false);
  });
  $("softcap-confirm").addEventListener("click", () => {
    softcapModal.hidden = true;
    lastRequest.confirm_over_softcap = true;
    runPropose(lastRequest);
  });

  // ---------- 工具 ----------
  function setLoading(loading) {
    submitBtn.disabled = loading;
    submitBtn.querySelector(".btn-label").hidden = loading;
    submitBtn.querySelector(".btn-loading").hidden = !loading;
  }

  function showError(msg) {
    errorBanner.textContent = msg;
    errorBanner.hidden = false;
  }
  function hideError() {
    errorBanner.hidden = true;
  }

  function updateSessionCost() {
    sessionCostEl.hidden = false;
    cumulativeCostEl.textContent = formatMoney(cumulativeCost);
    const hint = $("softcap-hint");
    if (cumulativeCost >= softcapCny * 0.8) {
      hint.textContent = "(接近软顶 " + formatMoney(softcapCny) + ")";
    } else {
      hint.textContent = "";
    }
  }

  function formatMoney(n) {
    if (n === null || n === undefined) return "¥—";
    return "¥" + Number(n).toFixed(4);
  }

  function sourceLabel(s) {
    const m = {
      llm: "LLM 生成",
      llm_failed: "LLM 失败",
      unavailable: "未配置 LLM",
      template: "蒸馏模板",
      template_fallback: "蒸馏模板(降级)",
      empty_short_circuit: "空输入短路",
      heuristic_no_adapter: "启发式(无 adapter)",
      llm_heuristic_fallback: "启发式降级",
    };
    return m[s] || s;
  }

  // 极简 markdown 渲染(支持 ## ### ** > - 和段落)
  function miniMarkdown(md) {
    if (!md) return "";
    const lines = md.split("\n");
    let html = "";
    let inList = false;
    let inQuote = false;
    function closeList() { if (inList) { html += "</ul>"; inList = false; } }
    function closeQuote() { if (inQuote) { html += "</blockquote>"; inQuote = false; } }

    lines.forEach((raw) => {
      const line = raw.trimEnd();
      if (!line.trim()) { closeList(); closeQuote(); return; }
      if (line.startsWith("### ")) {
        closeList(); closeQuote();
        html += "<h3>" + inline(line.slice(4)) + "</h3>";
      } else if (line.startsWith("## ")) {
        closeList(); closeQuote();
        html += "<h3>" + inline(line.slice(3)) + "</h3>";
      } else if (line.startsWith("# ")) {
        closeList(); closeQuote();
        html += "<h3>" + inline(line.slice(2)) + "</h3>";
      } else if (line.startsWith("> ")) {
        closeList();
        if (!inQuote) { html += "<blockquote>"; inQuote = true; }
        html += inline(line.slice(2)) + " ";
      } else if (line.startsWith("- ") || line.startsWith("* ")) {
        closeQuote();
        if (!inList) { html += "<ul>"; inList = true; }
        html += "<li>" + inline(line.slice(2)) + "</li>";
      } else if (line === "---") {
        closeList(); closeQuote();
        html += "<hr>";
      } else {
        closeList(); closeQuote();
        html += "<p>" + inline(line) + "</p>";
      }
    });
    closeList(); closeQuote();
    return html;
  }

  function inline(s) {
    // **bold**、`code`、*italic*
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

  // ---------- T7 起名器 ----------

  const namingCard = $("naming-card");
  const namingCandidates = $("naming-candidates");
  const refreshNamesBtn = $("refresh-names-btn");
  let lastNamingIdea = "";
  let lastNamingGenre = "xuanhuan";

  // 给其他模块用的:在结果渲染后补充起名按钮
  function addNamingButton(data) {
    if (!namingCard) return;
    const btn = document.createElement("button");
    btn.className = "btn-secondary naming-trigger";
    btn.type = "button";
    btn.textContent = "给它起名";
    btn.addEventListener("click", () => {
      const idea = (data && data.analysis && data.analysis.raw_idea) || ideaInput.value.trim() || "新书设想";
      lastNamingIdea = idea;
      // 从红蓝海结果推断题材
      attemptNaming(idea, lastNamingGenre);
    });
    // 放在创作规律卡片之后,元数据之前
    const craftCard = $("craft-card");
    if (craftCard && craftCard.parentNode) {
      craftCard.parentNode.insertBefore(btn, craftCard.nextSibling);
    }
  }

  function attemptNaming(idea, genre) {
    setNamingLoading(true);
    fetch("/api/naming", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idea: idea, genre: genre }),
    })
      .then((r) => {
        if (!r.ok) throw new Error("起名请求失败(" + r.status + ")");
        return r.json();
      })
      .then((data) => {
        renderNamingCandidates(data.candidates || [], data.source);
        namingCard.hidden = false;
      })
      .catch((e) => {
        showError("起名失败:" + e.message);
      })
      .finally(() => {
        setNamingLoading(false);
      });
  }

  function setNamingLoading(loading) {
    if (refreshNamesBtn) refreshNamesBtn.disabled = loading;
    if (refreshNamesBtn) refreshNamesBtn.textContent = loading ? "生成中…" : "换一批";
  }

  function renderNamingCandidates(candidates, source) {
    if (!namingCandidates) return;
    if (!candidates || candidates.length === 0) {
      namingCandidates.innerHTML = '<p class="naming-empty">暂未生成候选,请重试。</p>';
      return;
    }
    let html = "";
    // 降级出声:D-70, template_fallback 时显式徽标
    if (source === "template_fallback") {
      html += '<div class="naming-degraded-badge">已降级:模板候选(LLM 未达)</div>';
    }
    html += '<div class="naming-grid">';
    candidates.forEach((c, idx) => {
      html +=
        '<div class="naming-item" data-name="' + esc(c.name) + '">' +
        '<span class="naming-name">' + esc(c.name) + '</span>' +
        '<span class="naming-paradigm">' + esc(c.paradigm) + '</span>' +
        '<button class="btn-small naming-apply" data-name="' + esc(c.name) + '">选用</button>' +
        "</div>";
    });
    html += "</div>";
    namingCandidates.innerHTML = html;

    // 绑定选用按钮(R4 T4.6:弹窗确认,不再 alert)
    namingCandidates.querySelectorAll(".naming-apply").forEach((btn) => {
      btn.addEventListener("click", () => {
        const name = btn.dataset.name;
        showNamingApplyModal(name);
      });
    });
  }

  // ---------- R4 T4.6:起名选用确认弹窗(与 R5 防连点共用) ----------
  let _namingApplyModal = null;
  let _namingApplyPreview = null;
  let _namingApplySelect = null;
  let _namingApplyResult = null;
  let _namingApplyConfirmBtn = null;
  let _namingBooksCache = null;

  function showNamingApplyModal(name) {
    if (!_namingApplyModal) {
      _namingApplyModal = document.getElementById("naming-apply-modal");
      _namingApplyPreview = document.getElementById("naming-apply-preview");
      _namingApplySelect = document.getElementById("naming-apply-book");
      _namingApplyResult = document.getElementById("naming-apply-result");
      _namingApplyConfirmBtn = document.getElementById("naming-apply-confirm");
      document.getElementById("naming-apply-cancel").addEventListener("click", closeNamingApplyModal);
      _namingApplyConfirmBtn.addEventListener("click", () => confirmNamingApply(name));
    } else {
      // 重新绑定 confirm(因 name 变)
      _namingApplyConfirmBtn.onclick = null;
      _namingApplyConfirmBtn.addEventListener("click", function handler() {
        _namingApplyConfirmBtn.removeEventListener("click", handler);
        confirmNamingApply(name);
      });
    }

    // 预览候选名
    _namingApplyPreview.innerHTML =
      '<div style="padding:10px 14px;background:rgba(0,0,0,0.04);border-radius:4px;font-size:15px;font-weight:600;color:var(--seal);">' +
      esc(name) + '</div>';

    // 加载书列表(若未缓存)
    if (_namingBooksCache) {
      populateNamingBookSelect(_namingBooksCache);
      openNamingApplyModal();
    } else {
      _namingApplySelect.innerHTML = '<option>加载中…</option>';
      fetch("/api/books")
        .then((r) => r.json())
        // F3 (P8-M3R-fix):/api/books 返 dict schema {books, count}
        .then((data) => {
          _namingBooksCache = (data && data.books) || [];
          populateNamingBookSelect(_namingBooksCache);
          openNamingApplyModal();
        })
        .catch((e) => {
          _namingApplySelect.innerHTML = '<option value="">加载失败: ' + esc(e.message) + '</option>';
          openNamingApplyModal();
        });
    }
  }

  function populateNamingBookSelect(books) {
    if (!_namingApplySelect) return;
    // URL ?book=X 优先选中
    const params = new URLSearchParams(window.location.search);
    const urlBook = params.get("book") || params.get("name");
    // 过滤:real 书在前,test 在后
    const sorted = books.slice().sort((a, b) => {
      const ak = (a.kind === "real") ? 0 : 1;
      const bk = (b.kind === "real") ? 0 : 1;
      return ak - bk;
    });
    let html = "";
    sorted.forEach((b) => {
      const val = b.id || b.name;
      const dn = b.display_name || b.title || b.name;
      const kindLabel = b.kind === "real" ? "[书]" : "[测]";
      const sel = (val === urlBook) ? " selected" : "";
      html += '<option value="' + esc(val) + '"' + sel + '>' + kindLabel + " " + esc(dn) + " · " + esc(val) + '</option>';
    });
    if (!html) html = '<option value="">(无可用书)</option>';
    _namingApplySelect.innerHTML = html;
  }

  function openNamingApplyModal() {
    if (_namingApplyModal) {
      _namingApplyModal.hidden = false;
      if (_namingApplyResult) {
        _namingApplyResult.hidden = true;
        _namingApplyResult.innerHTML = "";
      }
      if (_namingApplyConfirmBtn) _namingApplyConfirmBtn.disabled = false;
    }
  }

  function closeNamingApplyModal() {
    if (_namingApplyModal) _namingApplyModal.hidden = true;
  }

  async function confirmNamingApply(name) {
    const bookVal = _namingApplySelect ? _namingApplySelect.value : "";
    if (!bookVal) {
      alert("请选择目标书");
      return;
    }
    // R5 T5.3 防连点(提前到 T4.6 实现,避免 confirm 重复触发)
    _namingApplyConfirmBtn.disabled = true;
    _namingApplyConfirmBtn.textContent = "应用中…";
    if (_namingApplyResult) {
      _namingApplyResult.hidden = false;
      _namingApplyResult.innerHTML = '<div style="color:var(--ink-dim);font-size:12px;">正在应用…</div>';
    }

    try {
      const resp = await fetch("/api/naming/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ book: bookVal, title: name }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || "HTTP " + resp.status);
      }
      const data = await resp.json();
      // 成功:更新 books 缓存 + 显示成功链接
      _namingBooksCache = null; // 失效缓存
      if (_namingApplyResult) {
        _namingApplyResult.innerHTML =
          '<div style="margin-top:12px;padding:10px 14px;background:#e8f5e9;color:#2e7d32;border-radius:4px;font-size:13px;">' +
          '✓ 已应用到 ' + esc(data.display_name || name) + '(R1 slug ID 不变,只 display_name 变)' +
          '<br><a href="/" style="color:var(--accent);">→ 查看书架</a>' +
          '</div>';
      }
      _namingApplyConfirmBtn.textContent = "已应用";
      // 不立即关弹窗,让用户看到成功提示
    } catch (e) {
      if (_namingApplyResult) {
        _namingApplyResult.hidden = false;
        _namingApplyResult.innerHTML =
          '<div style="margin-top:12px;padding:10px 14px;background:#ffebee;color:#c0392b;border-radius:4px;font-size:13px;">' +
          '✗ 应用失败: ' + esc(e.message) + '</div>';
      }
      _namingApplyConfirmBtn.disabled = false;
      _namingApplyConfirmBtn.textContent = "应用";
    }
  }

  function applyName(name) {
    // 兼容旧调用(R4 T4.6 前的入口)—— 走新弹窗
    showNamingApplyModal(name);
  }

  // 换一批
  if (refreshNamesBtn) {
    refreshNamesBtn.addEventListener("click", () => {
      attemptNaming(lastNamingIdea, lastNamingGenre);
    });
  }

  // 修改 renderResult 末尾以触发起名按钮
  const _origRenderResult = renderResult;
  renderResult = function (data) {
    _origRenderResult(data);
    addNamingButton(data);
  };

  // ---------- 启动 ----------
  init();
})();
