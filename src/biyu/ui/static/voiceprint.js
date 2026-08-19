const $ = id => document.getElementById(id);
const params = new URLSearchParams(location.search);
let book = params.get('book') || '';
let state = null;
let pendingImport = null;
let latestImportOutcome = null;

function showError(message) {
  const box = $('error-banner');
  box.replaceChildren();
  const row = document.createElement('div');
  row.className = 'error-banner-row';
  const icon = document.createElement('span');
  icon.className = 'error-banner-icon';
  icon.textContent = '✗';
  const text = document.createElement('span');
  text.className = 'error-banner-msg';
  text.textContent = message;
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'error-banner-close';
  close.textContent = '×';
  close.onclick = () => { box.hidden = true; };
  row.append(icon, text, close);
  box.append(row);
  box.hidden = false;
}

async function api(path, options) {
  const response = await fetch(
    `/api/voiceprint/books/${encodeURIComponent(book)}${path}`,
    options,
  );
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    const message = typeof detail === 'string'
      ? detail
      : detail?.message || `请求失败（${response.status}）`;
    throw new Error(message);
  }
  return response.json();
}

function buttonBusy(button, on, busyLabel = '处理中…') {
  if (on) {
    button.dataset.idleLabel = button.textContent;
    button.textContent = busyLabel;
    button.disabled=true;
  } else {
    button.disabled = false;
    button.textContent = button.dataset.idleLabel || button.textContent;
    delete button.dataset.idleLabel;
  }
  button.setAttribute('aria-busy', String(on));
}

function renderEstimate() {
  const estimate = state.estimate;
  const actual = state.last_actual_cost_yuan == null
    ? ''
    : `<p class="actual-cost">本次实际：¥${Number(state.last_actual_cost_yuan).toFixed(6)}</p>`;
  $('estimate').innerHTML = `
    <div class="summary-grid">
      <div><strong>${estimate.feedback_count}</strong>条反馈</div>
      <div><strong>${estimate.estimated_calls}</strong>次预计调用</div>
      <div><strong>¥${Number(estimate.estimated_cost_yuan).toFixed(3)}</strong>预计不超过</div>
    </div>
    <p class="muted">按当前反馈的实际序列化输入量、现役模型单价与输出上限估算。</p>
    ${actual}`;
}

function sourceRow(list, label, count, note = '') {
  const text = document.createElement('span');
  text.append(document.createTextNode(label));
  if (note) {
    const hint = document.createElement('small');
    hint.className = 'source-note';
    hint.textContent = ` ${note}`;
    text.append(hint);
  }
  const value = document.createElement('strong');
  value.textContent = `${count} 条`;
  list.append(text, value);
}

function renderSources() {
  const source = state.sources;
  const root = $('source-breakdown');
  root.replaceChildren();
  const heading = document.createElement('h3');
  heading.textContent = '这些反馈从哪来';
  const scope = document.createElement('p');
  scope.className = 'muted';
  scope.textContent = `当前读取《${$('book').selectedOptions[0]?.textContent || '当前书'}》· ${source.chapter_range}`;
  const list = document.createElement('div');
  list.className = 'source-list';
  sourceRow(list, '让写手改这句', source.revise, '这些也算问题信号，而且信号更强');
  sourceRow(list, '记下问题（暂不修改）', source.note_problem);
  sourceRow(list, '记为好句', source.good);
  sourceRow(list, '不算：章评的整章意见', source.chapter_excluded, '对整章说的，不是某一句，不进声纹');
  root.append(heading, scope, list);
}

function renderGroups() {
  const root = $('groups');
  root.replaceChildren();
  const showAll = $('show-all-groups').checked;
  const groups = showAll ? state.review.all_groups : state.review.groups;
  const last = state.review.last_distilled_at
    ? new Date(state.review.last_distilled_at).toLocaleString()
    : '还没有蒸馏过';
  $('redistill-meta').textContent =
    `上次蒸馏：${last} · 本次新增反馈 ${state.review.new_feedback_count} 条`;
  if (!groups.length) {
    root.textContent = showAll ? '还没有复核组。' : '没有待复核的组。';
    return;
  }
  groups.forEach(group => {
    const card = document.createElement('article');
    card.className = 'voice-card';
    const title = document.createElement('h3');
    title.textContent = group.kind === 'legacy'
      ? `以前记下的 · ${group.count} 条`
      : `这类你说过 ${group.count} 次`;
    card.append(title);
    if (group.needs_reconfirmation) {
      const grown = document.createElement('p');
      grown.className = 'guard';
      grown.textContent = `这组又出现了 ${group.new_count} 次，请重新确认。`;
      card.append(grown);
    } else if (group.decision) {
      const status = document.createElement('p');
      status.className = 'review-decision';
      status.textContent = group.decision === 'common'
        ? '已判定：这是通病'
        : '已判定：就那几次';
      card.append(status);
    }
    group.items.forEach(item => {
      const quote = document.createElement('blockquote');
      const origin = item.action === 'legacy'
        ? '存量记录'
        : `第 ${item.chapter} 章 · 第 ${item.round} 轮`;
      quote.textContent = `${origin}\n${item.text || ''}${item.author_comment ? `\n批注：${item.author_comment}` : ''}`;
      card.append(quote);
    });
    if (!group.decision || group.needs_reconfirmation) {
      const footer = document.createElement('footer');
      let actions = [['这是通病', 'common'], ['就那几次', 'specific']];
      if (group.needs_reconfirmation) {
        const keep = group.previous_decision;
        actions = [['维持原判', keep], ['改判', keep === 'common' ? 'specific' : 'common']];
      }
      actions.forEach(([label, decision]) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = label;
        button.onclick = () => decide(group.id, decision, button);
        footer.append(button);
      });
      card.append(footer);
    }
    root.append(card);
  });
}

function editableLineCard(line, profileId = '') {
  const box = document.createElement('div');
  box.className = 'voice-line';
  const heading = document.createElement('h3');
  heading.textContent = line.dimension;
  if(line.source==='author') {
    const edited = document.createElement('span');
    edited.className = 'author-edited-badge';
    edited.textContent = '你改过';
    heading.append(' ', edited);
  }
  const textLabel = document.createElement('label');
  textLabel.textContent = '规则是什么';
  const textarea = document.createElement('textarea');
  textarea.value = line.text;
  const whyLabel = document.createElement('label');
  whyLabel.textContent = '为什么';
  const why = document.createElement('textarea');
  why.value = line.why || '';
  const save = document.createElement('button');
  save.type = 'button';
  save.textContent = '保存这一行';
  save.onclick = () => saveLine(line.id, textarea.value, why.value, profileId, save);
  box.append(heading, textLabel, textarea, whyLabel, why, save);
  return box;
}

function renderLines() {
  const root = $('lines');
  root.replaceChildren();
  const profiles = (state.catalog || []).filter(profile => profile.lines?.length);
  if (!profiles.length) {
    root.textContent = '蒸馏、复核或导入作品后，声纹片段会显示在这里。';
    return;
  }
  profiles.forEach(profile => {
    const section = document.createElement('section');
    section.className = 'editable-profile';
    const title = document.createElement('h3');
    title.textContent = profile.name || '未命名声纹';
    const note = document.createElement('p');
    note.className = 'muted';
    note.textContent = profile.kind === 'imported'
      ? '来自你导入的作品；原文没有保存。'
      : profile.kind === 'combined' ? '机械合并稿；每条仍保留来源。'
      : profile.kind === 'manual' ? '你手写的声纹。' : '可逐行查看和修改。';
    section.append(title, note);
    (profile.lines || []).forEach(line => section.append(editableLineCard(line, profile.id)));
    root.append(section);
  });
}

function renderActive() {
  const active = state.merged?.lines || [];
  const profile = state.active_profile;
  $('active-name').textContent = profile
    ? `${profile.name}`
    : '当前没有生效的声纹。';
  $('active-count').textContent = profile
    ? `${active.length} 条规则 · ${profile.kind || '内置'}`
    : '';
  // S-1 留白栏：当前生效条数（中文数字）+ 当前声纹名
  const countNum = $('voice-count-num');
  if (countNum) {
    countNum.textContent = String(active.length);
  }
  const meta = $('voice-active-meta');
  if (meta) meta.innerHTML = profile ? `当前<br>${profile.name}` : '当前<br>无';
  $('active-source-warning').hidden = !profile?.sources_stale;
  const activeRoot = $('active-lines');
  if (activeRoot) {
    activeRoot.replaceChildren();
    if (!active.length) {
      activeRoot.textContent = '可以从“我的声纹”选择一份，或在下方新建。';
    } else {
      active.forEach(line => {
        const row = document.createElement('article');
        row.className = 'active-line';
        const title = document.createElement('strong');
        title.textContent = line.dimension;
        const text = document.createElement('p');
        text.textContent = line.text;
        const why = document.createElement('small');
        why.textContent = line.why ? `为什么：${line.why}` : '';
        row.append(title, text);
        if (why.textContent) row.append(why);
        activeRoot.append(row);
      });
    }
  }

  $('merged').innerHTML = window.MiniMd.render(state.merged?.text || '当前没有生效的声纹。');
}

function renderCatalog() {
  const root = $('catalog');
  root.replaceChildren();
  if (!(state.catalog || []).length) {
    // U-1：声纹「我的声纹」空态
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    const t = document.createElement('p');
    t.className = 'es-title';
    t.textContent = '还没有声纹。';
    const h = document.createElement('p');
    h.className = 'es-hint';
    h.textContent = '从下面四种方式新建一份：导入作品、从本书好坏句、合并已有的、或者自己写。';
    empty.append(t, h);
    root.append(empty);
    renderCombineSources();
    renderActive();
    return;
  }
  (state.catalog || []).forEach(profile => {
    const row = document.createElement('div');
    row.className = 'catalog-item';
    const text = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = `${profile.name}（${(profile.lines || []).length} 条）`;
    const note = document.createElement('small');
    note.textContent = profile.sources_stale ? '来源已有变化，可重合并' : profile.id === state.active ? '当前生效' : '';
    text.append(title, note);
    row.append(text);
    // W-2：能点必须有信号。当前生效=status-text 纯文字（不可点）；其余=「设为当前」按钮（可点）
    if (profile.id === state.active) {
      const activeTag = document.createElement('span');
      activeTag.className = 'status-text';
      activeTag.textContent = '当前生效';
      row.append(activeTag);
    } else {
      const activate = document.createElement('button');
      activate.type = 'button';
      activate.textContent = '设为当前';
      activate.onclick = () => activateProfile(profile.id, activate);
      row.append(activate);
    }
    root.append(row);
  });
  renderCombineSources();
  renderActive();
}

function renderCombineSources() {
  const root = $('combine-sources');
  root.replaceChildren();
  (state.catalog || []).forEach(profile => {
    const label = document.createElement('label');
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.value = profile.id;
    label.append(input, document.createTextNode(`${profile.name}（${(profile.lines || []).length} 条）`));
    root.append(label);
  });
}

async function activateProfile(profileId, button) {
  buttonBusy(button, true, '正在切换…');
  try {
    await api('/selection', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({active: profileId}),
    });
    await load();
  } catch (error) {
    showError(error.message);
  } finally {
    buttonBusy(button, false);
  }
}

function render() {
  renderEstimate();
  renderSources();
  renderGroups();
  renderLines();
  renderCatalog();
}

async function load() {
  if (!book) {
    showError('缺少书籍参数，请从章节工作台进入。');
    return;
  }
  state = await api('');
  render();
}

function syncBookContext() {
  const encoded = encodeURIComponent(book);
  history.replaceState(null, '', `/voiceprint.html?book=${encoded}`);
  $('workbench-link').href = `/workbench.html?book=${encoded}`;
  const memoryLink = $('memory-link');
  if (memoryLink) memoryLink.href = `/memory.html?book=${encoded}`;
}

async function loadBooks() {
  const response = await fetch('/api/workbench/books');
  if (!response.ok) throw new Error('书籍列表读取失败');
  const data = await response.json();
  const requested = book;
  const valid = data.books.some(item => item.id === requested);
  if (!valid) {
    const setup = await fetch('/api/setup/status').then(item => item.ok ? item.json() : ({}));
    book = setup.selected_book || data.books[0]?.id || '';
  }
  const select = $('book');
  select.replaceChildren(...data.books.map(item =>
    new Option(item.display_name, item.id, false, item.id === book)));
  if (book) syncBookContext();
  return {requested, valid};
}

async function decide(groupId, decision, button) {
  buttonBusy(button, true);
  try {
    await api(`/review/${encodeURIComponent(groupId)}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({decision}),
    });
    await load();
    if (latestImportOutcome?.status === 'ready') {
      const refreshed = (state.imports || []).find(
        profile => profile.id === latestImportOutcome.import_id,
      );
      if (refreshed) {
        latestImportOutcome = {...latestImportOutcome, profile: refreshed};
        renderImportOutcome(latestImportOutcome);
      }
    }
  } catch (error) {
    showError(error.message);
  } finally {
    buttonBusy(button, false);
  }
}

async function saveLine(lineId, text, why, profileId, button) {
  buttonBusy(button, true);
  try {
    await api(`/lines/${encodeURIComponent(lineId)}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text, why, profile_id: profileId}),
    });
    await load();
  } catch (error) {
    showError(error.message);
  } finally {
    buttonBusy(button, false);
  }
}

function invalidateImportPreflight() {
  pendingImport = null;
  latestImportOutcome = null;
  $('import-extract').disabled = true;
  $('import-preflight-result').hidden = true;
  $('import-result').hidden = true;
}

function importPayload() {
  const text = $('import-text').value.trim();
  if (!text) throw new Error('请粘贴作品正文，或选择一份 .txt / .md 文件');
  const sourceName = $('import-source-name').value.trim() || '粘贴文本.txt';
  return {source_name: sourceName, text};
}

function renderImportPreflight(result) {
  const box = $('import-preflight-result');
  box.innerHTML = `
    <h3>提取前确认</h3>
    <div class="import-cost-grid">
      <div><span>实际抽取样本</span><strong>${result.sampled_chars} 字</strong></div>
      <div><span>正常情况</span><strong>${result.normal_calls} 次</strong></div>
      <div><span>格式重试风险</span><strong>最多 ${result.max_calls} 次</strong></div>
      <div><span>正常预估</span><strong>¥${Number(result.estimated_cost).toFixed(4)}</strong></div>
      <div><span>最多可能</span><strong>¥${Number(result.max_estimated_cost).toFixed(4)}</strong></div>
    </div>
    <p class="muted">若第一次返回的格式不能使用，最多再试一次，所以最高费用按两次显示。</p>
    <p class="${result.prompt_ready ? 'ready-note' : 'import-blocked'}">${
      result.prompt_ready
        ? '提示词已可用。只有你点“确认提取”后才会调用模型。'
        : '提取提示词还在等老板签字。现在不能调用模型，也不会产生费用。'
    }</p>`;
  box.hidden = false;
  $('import-extract').disabled = !result.prompt_ready;
}

async function preflightImport() {
  const button = $('import-preflight');
  buttonBusy(button, true, '正在核对…');
  try {
    const payload = importPayload();
    const result = await api('/imports/preflight', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    pendingImport = {payload, result};
    renderImportPreflight(result);
    if (!result.prompt_ready) showError('提取提示词还在等老板签字；现在不会调用模型，也不会产生费用。');
  } catch (error) {
    pendingImport = null;
    $('import-extract').disabled = true;
    showError(error.message);
  } finally {
    buttonBusy(button, false);
  }
}

function renderImportOutcome(result) {
  latestImportOutcome = result;
  const box = $('import-result');
  box.replaceChildren();
  const heading = document.createElement('h3');
  if (result.status === 'insufficient') {
    heading.textContent = '这份文本暂时提炼不出稳定声纹';
    const reason = document.createElement('p');
    reason.textContent = result.quality_gate?.reason || '现有文本里还看不出足够稳定的写法。';
    const missing = document.createElement('ul');
    (result.quality_gate?.missing_evidence || []).forEach(item => {
      const row = document.createElement('li');
      row.textContent = item;
      missing.append(row);
    });
    const cost = document.createElement('p');
    cost.className = 'actual-cost';
    cost.textContent = `本次实际费用：¥${Number(result.actual_cost || 0).toFixed(6)}。这是有效结果，没有重试，也没有保存空声纹。`;
    box.append(heading, reason);
    if (missing.childElementCount) box.append(missing);
    box.append(cost);
  } else {
    heading.textContent = '作品声纹已经加入';
    const note = document.createElement('p');
    note.textContent = `${result.source_name || '这份作品'}已生成一份新声纹并设为当前；原文没有保存。`;
    const cost = document.createElement('p');
    cost.className = 'actual-cost';
    cost.textContent = `本次实际费用：¥${Number(result.actual_cost || 0).toFixed(6)}`;
    const editor = document.createElement('section');
    editor.className = 'imported-profile-editor';
    const editorTitle = document.createElement('h4');
    editorTitle.textContent = '提取出的写法（可以逐条修改）';
    editor.append(editorTitle);
    (result.profile?.lines || []).forEach(line => editor.append(editableLineCard(line, result.profile?.id || '')));
    box.append(heading, note, cost, editor);
  }
  box.hidden = false;
}

async function extractImport() {
  if (!pendingImport) {
    showError('文本已经变化，请重新查看字数和费用');
    return;
  }
  const button = $('import-extract');
  buttonBusy(button, true, '正在提取…');
  try {
    const result = await api('/imports/extract', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(pendingImport.payload),
    });
    renderImportOutcome(result);
    if (result.workspace) {
      state = result.workspace;
      render();
    } else {
      await load();
    }
    pendingImport = null;
    button.disabled=true;
  } catch (error) {
    showError(error.message);
  } finally {
    buttonBusy(button, false);
    if (!pendingImport) button.disabled = true;
  }
}

$('show-all-groups').onchange = () => renderGroups();$('book').onchange = async () => {
  book = $('book').value;
  syncBookContext();
  invalidateImportPreflight();
  try {
    await load();
  } catch (error) {
    showError(error.message);
  }
};
$('combine-create').onclick = async () => {
  const button = $('combine-create');
  const sourceIds = [...document.querySelectorAll('#combine-sources input:checked')].map(item => item.value);
  buttonBusy(button, true, '正在合并…');
  try {
    const result = await api('/profiles/combine', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: $('combine-name').value, source_ids: sourceIds}),
    });
    state = result.workspace;
    render();
  } catch (error) { showError(error.message); }
  finally { buttonBusy(button, false); }
};
$('manual-create').onclick = async () => {
  const button = $('manual-create');
  buttonBusy(button, true, '正在保存…');
  try {
    const result = await api('/profiles/manual', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: $('manual-name').value, lines: [{
        dimension: $('manual-dimension').value,
        text: $('manual-text').value,
        why: $('manual-why').value,
      }]}),
    });
    state = result.workspace;
    render();
    $('manual-text').value = '';
    $('manual-why').value = '';
  } catch (error) { showError(error.message); }
  finally { buttonBusy(button, false); }
};
$('distill').onclick = async () => {
  const button = $('distill');
  buttonBusy(button, true);
  try {
    const result = await api('/distill', {method: 'POST'});
    state = result.workspace;
    state.last_actual_cost_yuan = result.cost;
    render();
  } catch (error) {
    showError(error.message);
  } finally {
    buttonBusy(button, false);
  }
};
$('import-file').onchange = async event => {
  invalidateImportPreflight();
  const file = event.target.files?.[0];
  if (!file) return;
  if (!/\.(txt|md)$/i.test(file.name)) {
    event.target.value = '';
    showError('只支持 .txt 或 .md 文本文件');
    return;
  }
  try {
    $('import-source-status').textContent = '正在读取本地文件…';
    $('import-text').value = await file.text();
    $('import-source-name').value = file.name;
    $('import-source-status').textContent = `已读取 ${file.name}；原文只用于这次提取，不会保存到书稿目录。`;
  } catch {
    showError('本地文件读取失败，请重新选择或直接粘贴文本');
  }
};
$('import-text').addEventListener('input', invalidateImportPreflight);
$('import-source-name').addEventListener('input', invalidateImportPreflight);
$('import-preflight').onclick = preflightImport;
$('import-extract').onclick = extractImport;

// ---------- S-1 两层视图：第一层只管选；逐行修改与四种新建点进去，返回停在原位 ----------
let selectScrollY = 0;

function showSelectView() {
  $('select-view').hidden = false;
  $('lines-view').hidden = true;
  $('create-view').hidden = true;
  window.scrollTo(0, selectScrollY);
}

function openLinesView() {
  selectScrollY = window.scrollY;
  $('select-view').hidden = true;
  $('lines-view').hidden = false;
  $('create-view').hidden = true;
  window.scrollTo(0, 0);
}

function openCreateView(kind) {
  selectScrollY = window.scrollY;
  $('select-view').hidden = true;
  $('lines-view').hidden = true;
  $('create-view').hidden = false;
  ['import', 'distill', 'combine', 'manual'].forEach(key => {
    $('create-method-' + key).hidden = key !== kind;
  });
  window.scrollTo(0, 0);
}

$('open-lines').onclick = openLinesView;
$('back-to-select').onclick = showSelectView;
$('back-to-select-2').onclick = showSelectView;
document.querySelectorAll('.create-card').forEach(card => {
  card.onclick = () => openCreateView(card.dataset.create);
});

async function boot() {
  await loadBooks();
  if (book) await load();
  else showError('还没有可用书籍，请先从书架新建一本书。');
}

boot().catch(error => showError(error.message));
