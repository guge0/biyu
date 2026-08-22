 (() => {
   const $ = id => document.getElementById(id);
   const overlay = $('setup-overlay');
   if (!overlay) return;

   const form = $('setup-form');
   const model = $('setup-model');
   const provider = $('setup-provider');
   const customFields = $('setup-custom-fields');
   const landing = $('setup-landing');
   const book = $('setup-book');
   const create = $('setup-create');
   const titleRow = $('setup-title-row');
   const genreRow = $('setup-genre-row');
   const status = $('setup-status');
   const submit = $('setup-submit');
   const cancel = $('setup-cancel');
   const settingsButton = $('connection-settings-button');
   const advanced = $('setup-advanced');
   let snapshot = null;
   let regularMode = false;

   const showError = message => {
     status.textContent = message;
     status.className = 'setup-error';
   };

   const selectedProvider = () => {
     if (provider && provider.value) return provider.value;
     const item = (snapshot?.models || []).find(entry => entry.alias === model.value);
     return item?.provider || '';
   };

   const renderKeyState = () => {
     const configured = Boolean(snapshot?.configured_providers?.[selectedProvider()]);
     $('setup-key-state').textContent = `API Key：${configured ? '已配置' : '未配置'}`;
     $('setup-key').placeholder = configured ? '留空则继续使用现有 Key' : '请输入 API Key';
     if (regularMode) $('setup-key').required = !configured;
   };

   const fillModels = () => {
     if (provider) {
       const choices = snapshot.providers || [];
       provider.replaceChildren(...choices.map(item => new Option(item.provider === 'custom' ? '其他（自己填）' : (item.label || item.provider), item.provider)));
       provider.value = snapshot.provider || (choices[0] || {}).provider || '';
       provider.onchange = renderProvider;
       renderProvider();
     }
     model.replaceChildren(...snapshot.models.map(item => new Option(`${item.label}（${item.provider}）`, item.alias)));
     if (snapshot.selected_model) model.value = snapshot.selected_model;
     renderKeyState();
   };

   const stageOverrides = () => Object.fromEntries([...document.querySelectorAll('#setup-advanced-fields [data-stage] select')].map(select => [select.closest('[data-stage]').dataset.stage, select.value]));

   const renderProvider = () => {
     const isCustom = provider?.value === 'custom';
     if (customFields) customFields.hidden = !isCustom;
     const item = (snapshot.providers || []).find(entry => entry.provider === provider?.value);
     if (landing) landing.innerHTML = item ? Object.entries(item.models || {}).map(([stage, name]) => `${stage === 'planner' ? '规划' : stage === 'writer' ? '写作' : '润色'}用 ${name}`).join(' · ') : '';
     renderKeyState();
   };

   const renderAdvanced = () => {
     const fields = $('setup-advanced-fields');
     if (!fields || !snapshot) return;
     const options = (snapshot.models || []).map(item => `<option value="${item.alias}">${item.label}（${item.provider}）</option>`).join('');
     fields.innerHTML = [
       ['规划', '规划把细纲变成写作方案。', 'planner'],
       ['写作', '写手照方案写出正文。不要用推理模型。', 'writer'],
       ['检查', '编辑读一遍，挑出问题和偏离。跟写作用同一个模型。', 'editor'],
       ['润色', '再顺一遍文字，默认关闭。', 'polisher'],
     ].map(([name, why, stage]) => `<div class="setup-stage" data-stage="${stage}"><div class="setup-stage-head"><strong>${name}</strong><span class="setup-stage-why">${why}</span></div>${stage === 'editor' ? '<div class="setup-follow">跟写作用同一个模型</div>' : `<select aria-label="${name}模型">${options}</select>`}</div>`).join('');
   };

   if (advanced) advanced.onclick = () => {
     const fields = $('setup-advanced-fields');
     if (!fields.innerHTML) renderAdvanced();
     fields.hidden = !fields.hidden;
     advanced.setAttribute('aria-expanded', String(!fields.hidden));
   };

   const openRegularSettings = () => {
     if (!snapshot) {
       overlay.hidden = false;
       showError('正在读取连接设置，请稍候再试。');
       return;
     }
     regularMode = true;
     $('setup-heading').textContent = '换 Key / 换模型';
     $('setup-description').textContent = '已保存的 Key 不会显示。留空表示继续使用当前服务商的 Key。';
     $('setup-book-fields').hidden = true;
     $('setup-key').required = false;
      document.getElementById('setup-key').value='';
     cancel.hidden = false;
     submit.textContent = '保存并试一下连接';
     status.textContent = '';
     fillModels();
     if ($('setup-model-legacy')) $('setup-model-legacy').hidden = true;
     overlay.hidden = false;
     renderKeyState();
   };

   const openFirstRun = () => {
     regularMode = false;
     $('setup-heading').textContent = '第一次使用，先完成连接';
     $('setup-description').textContent = 'API Key 只存进系统钥匙串；系统会用一次极短请求校验连通性。';
     $('setup-book-fields').hidden = false;
     $('setup-key').required = true;
     cancel.hidden = true;
     fillModels();
     if ($('setup-model-legacy')) $('setup-model-legacy').hidden = true;
     book.replaceChildren(...snapshot.books.map(item => new Option(item.title, item.id)));
     if (!snapshot.books.length) {
       create.checked = true;
       create.onchange();
     }
     overlay.hidden = false;
   };

   create.onchange = () => {
     titleRow.hidden = !create.checked;
     genreRow.hidden = !create.checked;
     book.disabled = create.checked;
   };
   model.onchange = renderKeyState;
   cancel.onclick = () => { overlay.hidden = true; };
   if (settingsButton) settingsButton.onclick = openRegularSettings;

   form.onsubmit = async event => {
     event.preventDefault();
     if (submit.disabled) return;
     submit.disabled = true;
     submit.textContent = '正在校验…';
     status.textContent = '正在校验模型连接…';
     status.className = '';
     try {
       const payload = regularMode
         ? (provider?.value === 'custom' ? { provider: 'custom', base_url: $('setup-base-url').value, model_id: $('setup-model-id').value, api_key: $('setup-key').value, stage_overrides: stageOverrides() } : { provider: provider.value, model: model.value, api_key: $('setup-key').value, stage_overrides: stageOverrides() })
         : {
             api_key: $('setup-key').value,
             model: model.value,
             provider: provider?.value,
             stage_overrides: stageOverrides(),
             book: book.value,
             create_book: create.checked,
             book_title: $('setup-title').value,
             genre: $('setup-genre').value,
           };
       const response = await fetch(regularMode ? '/api/setup/update' : '/api/setup/complete', {
         method: 'POST',
         headers: { 'Content-Type': 'application/json' },
         body: JSON.stringify(payload),
       });
       const body = await response.json().catch(() => ({}));
       if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '设置没有完成');
       $('setup-key').value = '';
       status.textContent = `${body.message}；密钥保存在${body.secret_storage}`;
       const savedProvider = selectedProvider();
       snapshot.selected_model = model.value;
       snapshot.provider = savedProvider;
       snapshot.configured_providers[savedProvider] = true;
       renderKeyState();
       if (!regularMode) setTimeout(() => location.reload(), 500);
     } catch (error) {
       showError(error.message);
     } finally {
       submit.disabled = false;
       submit.textContent = '保存并试一下连接';
     }
   };

   fetch('/api/setup/status')
     .then(async response => {
       if (!response.ok) throw new Error('无法读取首次设置状态');
       snapshot = await response.json();
       if (!snapshot.ready) openFirstRun();
     })
     .catch(error => showError(error.message));
 })();
