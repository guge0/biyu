(() => {
  const el = document.getElementById('runtime-identity');
  if (!el) return;
  fetch('/api/version').then(r => r.json()).then(info => {
    el.textContent = `笔驭 ${info.version} · ${info.sha}`;
  }).catch(() => { el.textContent = '版本无法确认'; });
})();
