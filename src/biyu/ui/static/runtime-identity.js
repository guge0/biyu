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
  }).catch(() => { el.textContent = '版本无法确认'; });
})();
