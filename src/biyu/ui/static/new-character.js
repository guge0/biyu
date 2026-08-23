(function () {
  const params = new URLSearchParams(location.search);
  const book = params.get('book');
  if (!book) return;
  const encoded = encodeURIComponent(book);
  const roster = document.getElementById('roster');
  if (!roster) return;

  function fieldsFromForm(form) {
    const value = name => form.querySelector(`[data-new-field="${name}"]`)?.value.trim() || '';
    const called = {};
    value('别人怎么叫他').split(/\n|；|;/).map(v => v.trim()).filter(Boolean).forEach(item => {
      const parts = item.split(/[:：]/, 2);
      if (parts[0] && parts[1]) called[parts[0].trim()] = parts[1].trim();
    });
    return {
      '基础': { name: value('姓名'), tier: form.querySelector('[data-new-field="档位"]').value, role: value('角色定位') },
      '背景': value('背景'), '性格': value('性格'),
      '称谓': { '叙述者怎么称呼他': value('叙述者怎么称呼他'), '他怎么自称': value('他怎么自称'), '别人怎么叫他': called,
        '正文里不许用的称呼': value('正文里不许用的称呼').split(/\n|、|；|;/).map(v => v.trim()).filter(Boolean) },
      '语声样本': value('语声样本').split('\n').map(v => v.trim()).filter(Boolean),
    };
  }

  function openForm() {
    if (document.getElementById('new-character-dialog')) return;
    const dialog = document.createElement('dialog'); dialog.id = 'new-character-dialog';
    dialog.innerHTML = `<form method="dialog" class="new-character-form"><h3>新建人物卡</h3>
      <label>姓名（必填）<input required data-new-field="姓名" autofocus></label>
      <label>档位<select data-new-field="档位"><option value="protagonist">主角</option><option value="antagonist">反派</option><option value="major_supporting">重要配角</option><option value="supporting">次要配角</option><option value="npc">龙套</option></select></label>
      <label>角色定位<textarea data-new-field="角色定位"></textarea></label><label>背景<textarea data-new-field="背景"></textarea></label><label>性格<textarea data-new-field="性格"></textarea></label>
      <label>叙述者怎么称呼他<input data-new-field="叙述者怎么称呼他"></label><label>他怎么自称<input data-new-field="他怎么自称"></label>
      <label>别人怎么叫他<textarea data-new-field="别人怎么叫他" placeholder="例如：母亲：孩子"></textarea></label><label>正文里不许用的称呼<textarea data-new-field="正文里不许用的称呼"></textarea></label><label>语声样本<textarea data-new-field="语声样本"></textarea></label>
      <p class="new-character-status" role="status"></p><div class="actions"><button value="cancel">算了</button><button value="default" class="b1">创建人物卡</button></div></form>`;
    document.body.append(dialog); const form = dialog.querySelector('form');
    form.addEventListener('submit', async event => {
      event.preventDefault(); const status = form.querySelector('.new-character-status');
      const fields = fieldsFromForm(form); if (!fields['基础'].name) return;
      status.textContent = '正在创建…';
      try {
        const response = await fetch(`/api/settings/books/${encoded}/characters`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ fields }) });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || '人物卡没有创建成功。');
        dialog.close(); location.reload();
      } catch (error) { status.textContent = error.message; }
    });
    dialog.addEventListener('close', () => dialog.remove()); dialog.showModal();
  }

  function addButton(parent) { if (!parent || parent.querySelector('.new-character-action')) return; const button = document.createElement('button'); button.type = 'button'; button.className = 'new-character-action'; button.textContent = '＋ 新建人物卡'; button.addEventListener('click', openForm); parent.append(button); }
  const observer = new MutationObserver(() => {
    addButton(roster.querySelector('.roster-rule')?.parentElement || roster);
    roster.querySelectorAll('#roster-groups > section').forEach(group => addButton(group));
    const empty = roster.querySelector('.empty-state'); if (empty) addButton(empty);
  });
  observer.observe(roster, { childList: true, subtree: true });
  addButton(roster);
})();
