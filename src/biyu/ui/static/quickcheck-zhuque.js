/* S-6 · 朱雀体检与降分(快检台②卡 + 左栏分段视图)。
   逻辑独立于 quickcheck.js,只通过 window.__zqText 对接文本取用。
   分数口径与后端一致:0.5 起算「疑似 AI」,要改的窗从 0.45 起算(给判定留缓冲)。 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const input = $("qc-input");
  const view = $("qc-highlight-view");
  if (!input || !view || !$("zq-card")) return; // 页面没这张卡就不启用

  const RED = 0.5;      // 朱雀口径:0.5 以上疑似
  const FIXABLE = 0.45; // 引擎改写起点(与后端 PASS 一致)

  const S = {
    stage: "empty",        // empty | checked | fixing | done
    mode: "api",           // api | web
    windows: [],
    verdict: null,
    smooth: null,
    reportInfo: null,      // 网页复核:{red, total} 报告回读后
    hasKey: false,
    rewriter: null,
    terms: [],
    side: false,
    open: {}, reverted: {}, edited: {},
    job: null, progress: null,
    fixPending: false, estimate: null,
    webTargets: null,
  };

  // ---------- 基础工具 ----------

  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  };
  const fmt = (n) => (n == null ? "—" : Number(n).toFixed(2));
  const fmtTokens = (n) => (n >= 10000 ? Math.round(n / 1000) / 10 + " 万" : String(n));
  const toneOf = (s) => (s == null ? "amber" : s >= 0.99 ? "deep" : s >= RED ? "red" : "ok");
  const labelScore = (s) => (s == null ? "未测" : (s >= 0.99 ? "AI " : s >= RED ? "疑似 AI " : "像人写 ") + fmt(s));
  const normText = (s) => String(s || "").replace(/\s+/g, "");
  // 需手改的两种状态:自动模式没过线 / 盲改没过守卫
  const isManual = (w) => w.status === "未过线,需手改" || w.status === "未过守卫,需手改";

  async function api(path, options) {
    const resp = await fetch(path, options);
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(body.detail || "请求失败，稍后再试。");
    return body;
  }
  const postJson = (path, payload) => api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  function showErrorZq(msg) {
    const banner = $("error-banner");
    if (!banner) return;
    banner.textContent = "✗ " + msg;
    banner.style.color = "";
    banner.hidden = false;
    // S-7d:朱雀体检失败时给「导出诊断包」小链接(shell.js 公共函数)
    if (window.BiyuShell?.mountDiagnosticsLink) window.BiyuShell.mountDiagnosticsLink(banner);
  }

  function updateCharCountLocal() {
    const counter = $("qc-char-count");
    if (counter) counter.textContent = "字数：" + input.value.length.toLocaleString();
  }

  // ---------- 文本口径:当前采用的全文 ----------

  const effective = (w) => (S.edited[w.order] != null ? S.edited[w.order]
    : S.reverted[w.order] ? w.before : w.after);
  function currentText() {
    return S.windows.length ? S.windows.map(effective).join("") : input.value;
  }
  // quickcheck.js 的接线口:朱雀视图激活时取当前全文;未激活返回 null 走原逻辑
  window.__zqText = () => (S.stage === "empty" || !S.windows.length ? null : currentText());

  // ---------- 渲染 ----------

  function render() {
    const showZq = S.stage !== "empty";
    input.hidden = showZq;
    view.hidden = !showZq;
    $("legend-zq").style.display = showZq ? "flex" : "none";
    $("legend-local").style.display = showZq ? "none" : "flex";
    view.replaceChildren();
    if (showZq) {
      if (S.stage === "fixing") {
        view.appendChild(el("div", "zq-progress-line", progressLine()));
      }
      S.windows.forEach((w) => view.appendChild(renderWindow(w)));
    }
    renderVerdict();
    renderButtons();
    renderTerms();
    renderRewriter();
  }

  function ratioLine(lr) {
    const pct = (k) => Math.round(100 * (Number((lr || {})[k]) || 0));
    return "人工 " + pct("0") + "% · 疑似 " + pct("2") + "% · AI " + pct("1") + "%";
  }

  function renderVerdict() {
    let verdict = "还没体检";
    let sub = "先看朱雀会把哪几段判成 AI，再决定要不要改。";
    if (S.stage === "fixing") {
      verdict = "正在处理";
      sub = "可以先去做别的，改完会停在这里。";
    } else if (S.mode === "web") {
      if (S.reportInfo) {
        verdict = S.reportInfo.red > 0
          ? "报告读完了：还有 " + S.reportInfo.red + " 段在 0.5 以上"
          : "报告读完了：全部片段都低于 0.5";
        sub = S.reportInfo.red > 0
          ? "点「只重改还红的 " + S.reportInfo.red + " 段」再来一轮，或直接复制全文去发。"
          : "这版可以去发了，发前记得通读一遍。";
      } else if (S.stage === "done") {
        verdict = "改完一轮，去朱雀测分";
        sub = "点上面的「复制全文并打开朱雀」，测完把报告拖回来。";
      }
    } else if (S.stage === "checked" && S.verdict) {
      verdict = ratioLine(S.verdict.labels_ratio);
      const red = S.windows.filter((w) => (w.conf ?? 0) >= RED).length;
      sub = S.windows.length ? "共 " + S.windows.length + " 段，" + red + " 段会被判成 AI。" : "";
    } else if (S.stage === "done" && S.verdict) {
      verdict = ratioLine(S.verdict.labels_ratio);
      const ok = S.windows.filter((w) => w.changed && !isManual(w) && !S.reverted[w.order]).length;
      const manual = S.windows.filter(isManual).length;
      const smoothNote = S.smooth && S.smooth.total ? " 顺稿采用 " + S.smooth.kept + "/" + S.smooth.total + " 窗。" : "";
      sub = "改好 " + ok + " 段；" + (manual ? manual + " 段没过线，需要你手改。" : "没有需要手改的段。") + smoothNote;
    }
    $("zq-verdict").textContent = verdict;
    $("zq-sub").textContent = sub;
  }

  function renderButtons() {
    const apiMode = S.mode === "api";
    $("zq-api").hidden = !apiMode;
    $("zq-web").hidden = apiMode; // S-6b:原来误写成 !apiMode,网页模式三步区永远不出来
    $("zq-key-form").hidden = S.hasKey;
    const fixable = S.windows.filter((w) => (w.conf ?? 0) >= FIXABLE).length;
    $("zq-check").hidden = S.stage !== "empty";
    $("zq-fix").hidden = !(apiMode && S.stage === "checked" && fixable > 0);
    $("zq-fix").textContent = S.fixPending ? "确认开始改写" : "改掉红色的 " + fixable + " 段";
    $("zq-est").hidden = !S.fixPending;
    if (S.fixPending && S.estimate) {
      $("zq-est").textContent = "预计 " + S.estimate.minutes + " 分钟，模型约 " + S.estimate.cost_cny
        + " 元，朱雀额度约 " + fmtTokens(S.estimate.zhuque_tokens) + "。再点一次就开始，中途别关这页。";
    }
    const progressText = S.stage === "fixing" ? progressLine() : "";
    $("zq-progress").hidden = !(apiMode && S.stage === "fixing");
    if (apiMode) $("zq-progress").textContent = progressText;
    $("zq-web-progress").hidden = !(S.mode === "web" && S.stage === "fixing");
    if (!apiMode) $("zq-web-progress").textContent = progressText;
    $("zq-recheck").hidden = !(apiMode && S.stage === "done");
    $("zq-reset").hidden = S.stage === "empty";
    const webLabel = S.webTargets && S.webTargets.length
      ? "只重改还红的 " + S.webTargets.length + " 段"
      : (S.stage === "empty" ? "开始改写" : "再改一轮");
    $("zq-web-fix").textContent = webLabel;
    $("zq-web-fix").disabled = S.stage === "fixing";
    $("zq-badge").textContent = S.hasKey ? "已用自己的 Key" : "用你自己的 Key";
  }

  function progressLine() {
    const p = S.progress || {};
    if (p.phase === "outer") return "第 " + (p.pass_no || 1) + " 遍检查：共 " + (p.windows ?? "?") + " 窗，要改 " + (p.red ?? "?") + " 窗…";
    if (p.phase === "window") return "正在改写并逐段复测：已过线 " + (p.pass || 0) + " 段，正在改第 " + (p.index || 1) + " 段（共 " + (p.total ?? "?") + " 段）…";
    if (p.phase === "smooth") return "正在顺稿去翻译腔…";
    if (p.phase === "done") return "改完了。";
    return "正在启动改写…";
  }

  function renderTerms() {
    const host = $("zq-terms");
    if (!host) return;
    host.replaceChildren();
    if (!S.terms.length) {
      const hint = el("span", "aside-hint", "（词表还是空的，点「编辑词表」加人名地名，改写时原样保留）");
      hint.style.border = "none";
      hint.style.padding = "0";
      host.appendChild(hint);
      return;
    }
    S.terms.forEach((term) => host.appendChild(el("span", null, term)));
  }

  function renderRewriter() {
    const host = $("zq-rewriter");
    if (!host) return;
    host.replaceChildren();
    host.append("改写模型：");
    if (!S.rewriter || !S.rewriter.available) {
      host.append("还没配置，去书架页右上「换 Key / 换模型」");
      return;
    }
    host.appendChild(el("b", null,
      (S.rewriter.provider ? S.rewriter.provider + " " : "") + (S.rewriter.model || "")
      + (S.rewriter.verified ? "（已验证）" : "（未验证）")));
  }

  // ---------- 分段视图 ----------

  function chipFor(w) {
    const c = el("span", "zq-chip");
    const rev = !!S.reverted[w.order];
    const done = S.stage === "done";
    if (done && isManual(w)) {
      c.dataset.tone = "amber";
      c.textContent = w.status === "未过线,需手改"
        ? "没过线 " + fmt(w.s0) + " · 需要手改"
        : "没过守卫 · 需要手改";
      return c;
    }
    if (rev) {
      c.dataset.tone = toneOf(w.s0 ?? w.conf);
      c.textContent = "已退回原文 · " + labelScore(w.s0 ?? w.conf);
      return c;
    }
    if (done && w.changed && S.mode === "api" && w.s1 != null) {
      c.dataset.tone = "ok";
      c.textContent = fmt(w.s0) + " → " + fmt(w.s1) + " 已过线";
      return c;
    }
    if (done && w.changed && w.conf == null) {
      c.dataset.tone = "ok";
      c.textContent = "已改写 · 待朱雀复测";
      return c;
    }
    c.dataset.tone = toneOf(w.conf);
    c.textContent = labelScore(w.conf);
    return c;
  }

  function toneForWindow(w, rev) {
    if (S.stage === "done" && isManual(w)) return "amber";
    if (S.stage === "done" && w.changed && !rev) return "ok";
    const tone = toneOf(w.s0 ?? w.conf);
    return tone === "deep" ? "red" : tone;
  }

  function progressLabelFor(w) {
    if (S.stage !== "fixing" || !S.progress) return null;
    const queue = S.mode === "web"
      ? (S.webTargets || S.windows.map((x) => x.order))
      : S.windows.filter((x) => (x.conf ?? 0) >= FIXABLE).map((x) => x.order);
    const idx = queue.indexOf(w.order);
    if (idx < 0) return null;
    const done = S.progress.done || 0;
    if (idx < done) return "已处理";
    if (idx === done) return "改写中…";
    return "排队中";
  }

  function riskTitle(r) {
    const kind = r.kind === "number" ? "数字变化" : r.kind === "unit" ? "计量单位变化" : "专名";
    return kind + "：改前「" + (r.before || "（原稿里没有）") + "」→ 改后「" + (r.after || "（改后没有了）")
      + "」，请确认意思没变。";
  }

  // 在 parent 里按段落渲染 text;done 阶段落对白灰显;改后文本里标出 risks
  function appendParas(parent, text, grayDialogue, w) {
    const edited = w && S.edited[w.order] != null;
    const risks = w && !edited ? (w.risks || []).filter((r) => r.start != null && r.start >= 0) : [];
    let offset = 0;
    String(text).split("\n").forEach((line) => {
      const p = el("p", grayDialogue && line.charAt(0) === "“" ? "zq-lock" : "");
      const start = offset;
      const end = offset + line.length;
      let cursor = start;
      risks.forEach((r) => {
        const rs = Math.max(r.start, start);
        const re = Math.min(r.end, end);
        if (re <= rs) return;
        if (rs > cursor) p.appendChild(document.createTextNode(line.slice(cursor - start, rs - start)));
        const span = el("span", "zq-risk", line.slice(rs - start, re - start));
        span.title = riskTitle(r);
        p.appendChild(span);
        cursor = re;
      });
      if (cursor < end) p.appendChild(document.createTextNode(line.slice(cursor - start)));
      parent.appendChild(p);
      offset = end + 1; // 换行占一位
    });
  }

  function renderWindow(w) {
    const done = S.stage === "done";
    const rev = !!S.reverted[w.order];
    const changed = !!(w.changed && w.after !== w.before);
    const showAfter = done && changed && !rev && !isManual(w);

    const section = el("section", "zq-win");
    section.setAttribute("data-tone", toneForWindow(w, rev));
    const head = el("div", "zq-win-head");
    head.appendChild(el("span", "", "第 " + w.order + " 段"));
    head.appendChild(chipFor(w));
    if (S.stage === "fixing") {
      const p = progressLabelFor(w);
      if (p) head.appendChild(el("span", "", p));
    }
    if (showAfter) {
      const tools = el("div", "zq-win-tools");
      if (!S.side) {
        const b1 = el("button", "b3 bs", S.open[w.order] ? "收起改前" : "看改前");
        b1.type = "button";
        b1.onclick = () => { S.open[w.order] = !S.open[w.order]; render(); };
        tools.appendChild(b1);
      }
      const b2 = el("button", "b3 bs", rev ? "用回改后" : "退回原文");
      b2.type = "button";
      b2.onclick = () => { if (rev) delete S.reverted[w.order]; else S.reverted[w.order] = true; render(); };
      tools.appendChild(b2);
      head.appendChild(tools);
    }
    section.appendChild(head);

    if (showAfter && S.side) {
      const cols = el("div", "zq-cols");
      const left = el("div");
      const right = el("div");
      left.appendChild(el("div", "zq-col-label", "改前"));
      appendParas(left, w.before, false);
      right.appendChild(el("div", "zq-after-label", "改后 · 可以直接改字"));
      const body = el("div");
      body.contentEditable = "true";
      body.addEventListener("blur", () => { S.edited[w.order] = body.innerText.replace(/\n+$/, ""); });
      appendParas(body, effective(w), done, w);
      right.appendChild(body);
      cols.appendChild(left);
      cols.appendChild(right);
      section.appendChild(cols);
    } else {
      if (showAfter && S.open[w.order]) {
        const before = el("div", "zq-before");
        before.appendChild(el("div", "zq-before-label", "改前"));
        appendParas(before, w.before, false);
        section.appendChild(before);
      }
      if (showAfter) section.appendChild(el("div", "zq-after-label", "改后 · 可以直接在下面改字"));
      const body = el("div");
      if (showAfter) {
        body.contentEditable = "true";
        body.addEventListener("blur", () => { S.edited[w.order] = body.innerText.replace(/\n+$/, ""); });
      }
      appendParas(body, effective(w), done, w);
      section.appendChild(body);
    }

    if (done && isManual(w)) {
      const fail = el("div", "zq-fail");
      const tries = (w.attempts || []).length;
      fail.appendChild(el("div", "",
        w.status === "未过线,需手改"
          ? "试了 " + tries + " 稿都没过线，这段保留原文。打斗和大段描写最难改，建议你自己动手顺一遍，改完点「复测整章」。"
          : "试了 " + tries + " 稿都没过守卫，这段保留原文，建议你自己改。"));
      if (w.best_try && w.best_try.text) {
        fail.appendChild(el("div", "zq-best",
          "最接近的一稿（" + (w.best_try.score != null ? fmt(w.best_try.score) : "未测分") + "，未采用）：\n"
          + String(w.best_try.text).trim()));
      }
      section.appendChild(fail);
    }
    const noteRisks = (w.risks || []).filter((r) => r.start == null || r.start < 0);
    if (done && noteRisks.length) {
      section.appendChild(el("div", "zq-risk-note", "留意：" + noteRisks.map((r) =>
        r.kind === "term" ? "专名「" + r.before + "」改后没有了" : "数字「" + r.before + "」改后没有了"
      ).join("；")));
    }
    return section;
  }

  // ---------- 数据装配 ----------

  const normalizeCheckWindow = (w) => ({
    order: w.order, start: w.start, end: w.end,
    before: w.text, after: w.text, s0: w.conf, s1: null, conf: w.conf,
    changed: false, status: null, attempts: [], risks: [], best_try: null,
  });

  function applyFixResult(result) {
    S.verdict = result.verdict || null;
    S.smooth = result.smooth || null;
    const rowsByAfter = new Map();
    (result.rows || []).forEach((row) => rowsByAfter.set(row.after, row));
    S.windows = (result.windows || []).map((w) => {
      const row = rowsByAfter.get(w.text);
      if (row) {
        rowsByAfter.delete(w.text);
        return {
          order: w.order, start: w.start, end: w.end, conf: w.conf,
          before: row.before, after: row.after, s0: row.s0, s1: row.s1,
          changed: row.after !== row.before, status: row.status,
          attempts: row.attempts || [], risks: row.risks || [], best_try: row.best_try,
        };
      }
      return normalizeCheckWindow(w);
    });
    S.open = {}; S.reverted = {}; S.edited = {};
    S.fixPending = false; S.estimate = null; S.progress = null; S.job = null;
    S.stage = "done";
    render();
  }

  function applyBlindResult(result) {
    // 没再改的窗沿用上一轮已测到的分数(文本没变,报告分数仍有效)
    const prevScores = new Map();
    S.windows.forEach((w) => {
      if (w.conf != null) prevScores.set(normText(effective(w)), w.conf);
    });
    S.windows = (result.rows || []).map((row) => {
      const changed = row.after !== row.before;
      return {
        order: row.order, start: null, end: null,
        before: row.before, after: row.after, s0: row.s0, s1: row.s1,
        conf: changed ? null : (prevScores.get(normText(row.after)) ?? null),
        changed, status: row.status,
        attempts: row.attempts || [], risks: row.risks || [], best_try: row.best_try,
      };
    });
    S.reportInfo = null;
    S.webTargets = null;
    S.progress = null; S.job = null;
    S.open = {}; S.reverted = {}; S.edited = {};
    S.stage = "done";
    render();
  }

  // ---------- 动作 ----------

  async function loadStatus() {
    try {
      const st = await api("/api/zhuque/status");
      S.hasKey = !!st.has_key;
      S.rewriter = st.rewriter || null;
    } catch (_e) {
      S.hasKey = false;
    }
    render();
  }

  async function doCheck() {
    const text = currentText().trim();
    if (!text) { showErrorZq("先在左边粘贴章节文本。"); return; }
    $("zq-check").disabled = true;
    $("zq-check").textContent = "体检中…";
    try {
      const r = await postJson("/api/zhuque/check", { text });
      S.windows = r.windows.map(normalizeCheckWindow);
      S.verdict = r.verdict;
      S.open = {}; S.reverted = {}; S.edited = {};
      S.stage = "checked"; S.fixPending = false; S.estimate = null;
      render();
    } catch (e) {
      showErrorZq(e.message || String(e));
    } finally {
      $("zq-check").disabled = false;
      $("zq-check").textContent = "朱雀体检";
    }
  }

  async function onFixClick() {
    const text = currentText().trim();
    if (!text) { showErrorZq("先在左边粘贴章节文本。"); return; }
    try {
      if (!S.fixPending) {
        const r = await postJson("/api/zhuque/fix", { text, terms: S.terms, estimate_only: true });
        S.estimate = r.estimate;
        S.fixPending = true;
        render();
        return;
      }
      const r = await postJson("/api/zhuque/fix", { text, terms: S.terms, estimate_only: false });
      S.job = r.job_id;
      S.stage = "fixing";
      S.progress = null;
      render();
      pollJob();
    } catch (e) {
      showErrorZq(e.message || String(e));
    }
  }

  async function blindFix() {
    const text = currentText().trim();
    if (!text) { showErrorZq("先在左边粘贴章节文本。"); return; }
    if (!S.rewriter || !S.rewriter.available) { showErrorZq("还没配降 AI 率用的模型 Key（推荐智谱 glm-5.2）：到书架页「Key / 模型」保存，或点「怎么申请？」看步骤。"); return; }
    try {
      const r = await postJson("/api/zhuque/fix-blind", {
        text, terms: S.terms, targets: S.webTargets,
      });
      S.job = r.job_id;
      S.stage = "fixing";
      S.progress = null;
      render();
      pollJob();
    } catch (e) {
      showErrorZq(e.message || String(e));
    }
  }

  function pollJob() {
    const tick = async () => {
      if (!S.job) return;
      try {
        const r = await api("/api/zhuque/jobs/" + S.job);
        if (r.status === "running") {
          S.progress = r.progress;
          render();
          setTimeout(tick, 1500);
          return;
        }
        if (r.status === "error") {
          showErrorZq(r.error || "任务失败，请重试。");
          S.stage = S.windows.length ? "done" : "empty";
          S.job = null;
          render();
          return;
        }
        if (r.kind === "fix-blind") applyBlindResult(r.result);
        else applyFixResult(r.result);
      } catch (e) {
        showErrorZq(e.message || String(e));
      }
    };
    tick();
  }

  async function recheck() {
    const text = currentText().trim();
    if (!text) return;
    $("zq-recheck").disabled = true;
    try {
      const r = await postJson("/api/zhuque/check", { text });
      S.windows = r.windows.map(normalizeCheckWindow);
      S.verdict = r.verdict;
      S.open = {}; S.reverted = {}; S.edited = {};
      S.stage = "checked"; S.fixPending = false; S.estimate = null;
      render();
    } catch (e) {
      showErrorZq(e.message || String(e));
    } finally {
      $("zq-recheck").disabled = false;
    }
  }

  function resetToInput() {
    // 重新开始:把当前采用的全文(含手改)放回输入框,回本地扫描态
    input.value = currentText();
    S.stage = "empty";
    S.windows = []; S.verdict = null; S.smooth = null; S.reportInfo = null;
    S.open = {}; S.reverted = {}; S.edited = {};
    S.fixPending = false; S.estimate = null; S.progress = null; S.job = null;
    S.webTargets = null;
    render();
    updateCharCountLocal();
  }

  function clearSoft() {
    // 载入新文本(示例/粘贴/拖文件)或本地扫描时:只清朱雀态,不动输入框与画布
    if (S.stage === "empty") return;
    S.stage = "empty";
    S.windows = []; S.verdict = null; S.smooth = null; S.reportInfo = null;
    S.open = {}; S.reverted = {}; S.edited = {};
    S.fixPending = false; S.estimate = null; S.progress = null; S.job = null;
    S.webTargets = null;
    $("legend-zq").style.display = "none";
    $("legend-local").style.display = "flex";
    renderVerdict();
    renderButtons();
  }

  async function uploadReport(file) {
    if (!file) return;
    const label = $("zq-drop-label");
    const original = label ? label.textContent : "";
    if (label) label.textContent = "正在读报告…";
    try {
      const fd = new FormData();
      fd.append("pdf", file);
      fd.append("text", currentText());
      const r = await api("/api/zhuque/report", { method: "POST", body: fd });
      let matched = 0;
      r.windows.forEach((w, i) => {
        const cur = S.windows[i];
        if (!cur) return;
        if (normText(effective(cur)) === normText(w.text) || normText(cur.after) === normText(w.text)) {
          cur.conf = w.score;
          if (w.score != null) matched += 1;
        } else {
          cur.conf = null;
        }
      });
      S.webTargets = r.windows.filter((w) => (w.score ?? 0) >= RED).map((w) => w.order);
      S.reportInfo = { red: r.red || 0, total: r.windows.length, matched };
      render();
    } catch (e) {
      showErrorZq(e.message || String(e));
    } finally {
      if (label) label.textContent = original;
    }
  }

  // ---------- 接线 ----------

  $("zq-check").addEventListener("click", doCheck);
  $("zq-fix").addEventListener("click", onFixClick);
  $("zq-recheck").addEventListener("click", recheck);
  $("zq-reset").addEventListener("click", resetToInput);
  $("zq-web-fix").addEventListener("click", blindFix);

  $("zq-key-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const key = $("zq-key-input").value.trim();
    if (!key) { showErrorZq("先粘贴 Key 再保存。"); return; }
    try {
      await postJson("/api/zhuque/key", { key });
      $("zq-key-input").value = "";
      await loadStatus();
    } catch (e) {
      showErrorZq(e.message || String(e));
    }
  });

  Array.prototype.forEach.call(document.getElementsByName("zq-mode"), (radio) => {
    radio.addEventListener("change", () => {
      if (!radio.checked) return;
      S.mode = radio.value;
      render();
    });
  });

  $("zq-layout").addEventListener("click", function () {
    S.side = !S.side;
    this.textContent = S.side ? "切到上下对照" : "切到左右对照";
    render();
  });

  $("zq-open").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(currentText()); } catch (_e) { /* 剪贴板被拒时靠手动复制 */ }
  });

  const drop = $("zq-drop");
  drop.addEventListener("dragover", (event) => { event.preventDefault(); drop.classList.add("zq-dragover"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("zq-dragover"));
  drop.addEventListener("drop", (event) => {
    event.preventDefault();
    drop.classList.remove("zq-dragover");
    const file = event.dataTransfer.files && event.dataTransfer.files[0];
    if (file) uploadReport(file);
  });
  $("zq-pick").addEventListener("click", () => $("zq-file").click());
  $("zq-file").addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0];
    if (file) uploadReport(file);
    event.target.value = "";
  });

  $("zq-terms-toggle").addEventListener("click", () => {
    const box = $("zq-terms-edit");
    box.hidden = !box.hidden;
    $("zq-terms-toggle").textContent = box.hidden ? "编辑词表" : "收起词表";
    if (!box.hidden) $("zq-terms-input").value = S.terms.join("\n");
  });
  $("zq-terms-save").addEventListener("click", () => {
    S.terms = $("zq-terms-input").value.split("\n").map((s) => s.trim()).filter(Boolean);
    try { localStorage.setItem("biyu-zq-terms", JSON.stringify(S.terms)); } catch (_e) { /* 隐私模式存不进就算了 */ }
    renderTerms();
  });

  // 载入新文本或点本地扫描时,让位给原有快检逻辑
  ["qc-sample-btn", "qc-paste-btn"].forEach((id) => {
    const btn = $(id);
    if (btn) btn.addEventListener("click", clearSoft);
  });
  const fileInput = $("qc-file");
  if (fileInput) fileInput.addEventListener("change", clearSoft);
  const scanBtn = $("qc-scan-btn");
  if (scanBtn) scanBtn.addEventListener("click", clearSoft);

  // ---------- 启动 ----------

  try { S.terms = JSON.parse(localStorage.getItem("biyu-zq-terms") || "[]"); } catch (_e) { S.terms = []; }
  if (!Array.isArray(S.terms)) S.terms = [];
  loadStatus();
})();
