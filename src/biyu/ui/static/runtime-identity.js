(() => {
  const el = document.getElementById('runtime-identity');
  if (!el) return;
  fetch('/api/version').then(r => r.json()).then(info => {
    el.textContent = `笔驭 ${info.version} · ${info.sha}`;
    const update = info.update || {};
    if (update.available || info.update_available) {
      el.classList.add('has-update');
      el.title = `有新版本：${update.published || info.latest_version || '可用更新'}`;
      const dot = document.createElement('span');
      dot.className = 'update-dot';
      dot.setAttribute('aria-label', '有新版本');
      el.appendChild(dot);
    }
    // 2026-10 老板要求:落后 origin/main 标红点,点击拉取最新
    const behind = Number(info.behind_commits || 0);
    if (behind > 0) {
      el.classList.add('has-update');
      const behindDot = document.createElement('button');
      behindDot.className = 'update-dot update-dot-behind';
      behindDot.setAttribute('aria-label', `落后 ${behind} 个提交`);
      behindDot.title = `落后最新版本 ${behind} 个提交，点击拉取（拉取后重启笔驭生效）`;
      behindDot.onclick = async () => {
        behindDot.disabled = true;
        behindDot.title = '正在拉取…';
        try {
          const result = await (await fetch('/api/update/pull', { method: 'POST' })).json();
          behindDot.title = result.ok ? result.hint : `拉取失败：${result.message}`;
          if (result.ok) behindDot.classList.add('pulled');
        } catch (_e) {
          behindDot.title = '拉取失败：服务未响应';
        } finally { behindDot.disabled = false; }
      };
      el.appendChild(behindDot);
    }
  }).catch(() => { el.textContent = '版本无法确认'; });
})();
