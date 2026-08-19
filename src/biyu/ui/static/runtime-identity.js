(() => {
  const el = document.getElementById('runtime-identity');
  if (!el) return;
  fetch('/api/version').then(r => r.json()).then(info => {
    el.textContent = `${info.role} · ${info.checkout} · ${info.repo} · ${info.sha} · ${info.data_root}`;
  }).catch(() => { el.textContent = '版本无法确认'; });
})();
