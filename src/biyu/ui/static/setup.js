 (() => {
   const $ = id => document.getElementById(id);
   const overlay = $('setup-overlay');
   if (!overlay) return;

   const form = $('setup-form');
   const model = $('setup-model');
   const provider = $('setup-provider');
   const customFields = $('setup-custom-fields');
   const landing = $('setup-landing');
   const status = $('setup-status');
   const submit = $('setup-submit');
   const cancel = $('setup-cancel');
   const settingsButton = $('connection-settings-button');
   const advanced = $('setup-advanced');
   const close = $('setup-close');
   const multiToggle = $('setup-multi-toggle');
   const multiFields = $('setup-multi-provider-fields');
   let snapshot = null;
   let regularMode = false;
   let initialSetupValues = null;

   const showError = message => {
     status.textContent = message;
     status.className = 'setup-error';
   };

   const selectedProvider = () => {
     if (provider && provider.value) return provider.value;
     const item = (snapshot?.models || []).find(entry => entry.alias === model.value);
     return item?.provider || '';
   };

   // Key 状态与书架同一口径:后端 key_sources 给出实际生效的来源(整改清单 #2)。
   const KEY_SOURCE_LABEL = { inline: '配置文件', env: '环境变量', keyring: '系统钥匙串' };
   const renderKeyState = () => {
     const source = snapshot?.key_sources?.[selectedProvider()] || '';
     const configured = Boolean(source || snapshot?.configured_providers?.[selectedProvider()]);
     const where = KEY_SOURCE_LABEL[source];
     $('setup-key-state').textContent = configured ? `API Key：已配置${where ? `（${where}）` : ''}` : 'API Key：未配置';
     $('setup-key').placeholder = configured ? '留空则继续使用现有 Key' : '请输入 API Key';
     if (regularMode) $('setup-key').required = !configured;
   };

   const renderMultiProviderFields = () => {
     if (!multiFields || !snapshot) return;
     const previous = Object.fromEntries([...multiFields.querySelectorAll('[data-provider-key]')].map(input => [input.dataset.providerKey, input.value]));
     const selected = provider?.value || '';
     multiFields.replaceChildren(...(snapshot.providers || []).filter(item => item.provider !== selected).map(item => {
       const label = document.createElement('label');
       label.textContent = `${item.label || item.provider} API Key`;
       const input = document.createElement('input');
       input.type = 'password'; input.autocomplete = 'off'; input.dataset.providerKey = item.provider;
       input.placeholder = snapshot.configured_providers?.[item.provider] ? '已配置，留空不变' : '输入后一起保存';
       input.value = previous[item.provider] || '';
       label.append(input); return label;
     }));
   };

   const renderModelChoices = () => {
     if (!model || !snapshot) return;
     const selected = provider?.value || '';
     const choices = (snapshot.models || []).filter(item => !selected || selected === 'custom' || item.provider === selected);
     model.replaceChildren(...choices.map(item => new Option(`${item.label}（${item.provider}）`, item.alias)));
     if (choices.some(item => item.alias === snapshot.selected_model)) model.value = snapshot.selected_model;
     else if (choices[0]) model.value = choices[0].alias;
   };

   const fillModels = () => {
     if (provider) {
       const choices = snapshot.providers || [];
       provider.replaceChildren(...choices.map(item => new Option(item.provider === 'custom' ? '其他（自己填）' : (item.label || item.provider), item.provider)));
       provider.value = snapshot.provider || (choices[0] || {}).provider || '';
       provider.onchange = renderProvider;
       renderProvider();
     }
     renderModelChoices();
     renderKeyState();
     renderMultiProviderFields();
   };

   const stageOverrides = () => Object.fromEntries([...document.querySelectorAll('#setup-advanced-fields [data-stage] select')].map(select => [select.closest('[data-stage]').dataset.stage, select.value]));
   // S-3B 走查修复:打开弹窗时记录下拉的生效初值。snapshot.selected_model/provider
   // 可能为空串,直接比较会让「没改任何东西」也判定为有未保存设置,取消时误弹确认。
   const hasUnsavedSetup = () => Boolean(
     $('setup-key')?.value ||
     [...document.querySelectorAll('[data-provider-key]')].some(input => input.value) ||
     (regularMode && initialSetupValues && (provider?.value !== initialSetupValues.provider || model?.value !== initialSetupValues.model))
   );
   const closeSetup = () => {
     if (hasUnsavedSetup() && !window.confirm('还有设置没有确认，确定关闭吗？')) return;
     overlay.hidden = true;
   };

   const renderProvider = () => {
     const isCustom = provider?.value === 'custom';
     if (customFields) customFields.hidden = !isCustom;
     const item = (snapshot.providers || []).find(entry => entry.provider === provider?.value);
     if (landing) landing.innerHTML = item ? Object.entries(item.models || {}).filter(([stage]) => stage !== 'polisher').map(([stage, name]) => `${stage === 'planner' ? '规划' : '写作'}用 ${name}`).join(' · ') : '';
     renderKeyState();
     renderModelChoices();
     renderKeyState();
     renderMultiProviderFields();
     // S-3B:分环节区已展开过的情况下,换服务商要按新服务商的环节模型重渲染
     const advancedFields = $('setup-advanced-fields');
     if (advancedFields && advancedFields.innerHTML) renderAdvanced();
   };

   const renderAdvanced = () => {
     const fields = $('setup-advanced-fields');
     if (!fields || !snapshot) return;
     const options = (snapshot.models || []).map(item => `<option value="${item.alias}">${item.label}（${item.provider}）</option>`).join('');
     // S-3B 走查修复:分环节下拉必须回显当前服务商的环节模型,否则展开后直接
     // 「确认并关闭」会把 stage_overrides 静默改成列表第一项(如写作档变推理模型)。
     // providers[].models 里是模型展示名(deepseek-chat),要与 models[].label 对回别名。
     const stageModels = ((snapshot.providers || []).find(entry => entry.provider === (provider?.value || snapshot.provider)) || {}).models || {};
     const currentAlias = stage => {
       const wanted = stageModels[stage];
       const hit = (snapshot.models || []).find(item => item.alias === wanted || item.label === wanted);
       return hit ? hit.alias : '';
     };
     fields.innerHTML = [
       ['规划', '规划把细纲变成写作方案。', 'planner'],
       ['写作', '写手照方案写出正文。不要用推理模型。', 'writer'],
       ['检查', '编辑读一遍，挑出问题和偏离。跟写作用同一个模型。', 'editor'],
     ].map(([name, why, stage]) => `<div class="setup-stage" data-stage="${stage}"><div class="setup-stage-head"><strong>${name}</strong><span class="setup-stage-why">${why}</span></div>${stage === 'editor' ? '<div class="setup-follow">跟写作用同一个模型</div>' : `<select aria-label="${name}模型">${options}</select>`}</div>`).join('');
     fields.querySelectorAll('[data-stage] select').forEach(select => {
       const current = currentAlias(select.closest('[data-stage]').dataset.stage);
       if (current) select.value = current;
     });
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
     $('setup-heading').textContent = 'Key 与模型';
     $('setup-description').textContent = '已保存的 Key 不会显示。留空表示继续使用当前服务商的 Key。';
     $('setup-key').required = false;
      document.getElementById('setup-key').value='';
     cancel.hidden = false;
     submit.textContent = '确认并关闭';
     status.textContent = '';
     fillModels();
     initialSetupValues = {provider: provider?.value ?? '', model: model?.value ?? ''};
     if ($('setup-model-legacy')) $('setup-model-legacy').hidden = true;
     overlay.hidden = false;
     renderKeyState();
   };

   const openFirstRun = () => {
     regularMode = false;
     $('setup-heading').textContent = '连接模型';
     $('setup-description').textContent = 'API Key 只存进系统钥匙串；系统会用一次极短请求校验连通性。';
     $('setup-key').required = true;
     cancel.hidden = true;
     fillModels();
     initialSetupValues = {provider: provider?.value ?? '', model: model?.value ?? ''};
     if ($('setup-model-legacy')) $('setup-model-legacy').hidden = true;
     overlay.hidden = false;
   };
   model.onchange = renderKeyState;
   cancel.onclick = closeSetup;
   if (close) close.onclick = closeSetup;
   if (multiToggle) multiToggle.onclick = () => {
     if (!multiFields.innerHTML) renderMultiProviderFields();
     multiFields.hidden = !multiFields.hidden;
     multiToggle.setAttribute('aria-expanded', String(!multiFields.hidden));
   };
   overlay.addEventListener('click', event => { if (event.target === overlay) closeSetup(); });
   document.addEventListener('keydown', event => { if (event.key === 'Escape' && !overlay.hidden) closeSetup(); });
   if (settingsButton) settingsButton.onclick = openRegularSettings;

   form.onsubmit = async event => {
     event.preventDefault();
     if (submit.disabled) return;
     submit.disabled = true;
     submit.textContent = '正在校验…';
     status.textContent = '正在校验模型连接…';
     status.className = '';
     try {
       const providerKeys = Object.fromEntries([...document.querySelectorAll('[data-provider-key]')].map(input => [input.dataset.providerKey, input.value]).filter(([, value]) => value));
       const payload = regularMode
         ? (provider?.value === 'custom' ? { provider: 'custom', base_url: $('setup-base-url').value, model_id: $('setup-model-id').value, api_key: $('setup-key').value, provider_keys: providerKeys, stage_overrides: stageOverrides() } : { provider: provider.value, model: model.value, api_key: $('setup-key').value, provider_keys: providerKeys, stage_overrides: stageOverrides() })
         : {
             api_key: $('setup-key').value,
             model: model.value,
             provider: provider?.value,
             stage_overrides: stageOverrides(),
             provider_keys: providerKeys,
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
       if (regularMode) overlay.hidden = true;
       else setTimeout(() => location.reload(), 500);
     } catch (error) {
       showError(error.message);
     } finally {
       submit.disabled = false;
       submit.textContent = regularMode ? '确认并关闭' : '保存并试一下连接';
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
