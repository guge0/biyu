/* ==========================================================================
   笔驭 biyu · S-1 全局壳（V2 视觉规范 v2.0）
   主题引擎 / 背景图引擎 / 顶栏与状态栏注入 / 外观抽屉
   事实源：reference_biyu_ai_v2.html（令牌表经零差异测试钉住，勿就地改值）
   持久化：GET/PUT /api/ui/prefs；背景图 POST /api/ui/background（JSON base64）
   ========================================================================== */
(function () {
  'use strict';

  const THEME_PRESETS = /*S1-THEME-BEGIN*/{"default": {"name": "温润手稿 · 云宣白卡 (默认)", "--paper": "#F3F1EA", "--surface": "#FFFFFF", "--surface-subtle": "#F9F8F3", "--ink": "#1F1C18", "--ink-solid": "#26221C", "--ink-soft": "#524C42", "--ink-mute": "#827B6E", "--ink-faint": "#ABA496", "--rule": "rgba(38, 33, 25, 0.08)", "--rule-strong": "#DED8CA", "--rule-soft": "#EFECE4", "--numeral": "#C4BDAE", "--mark": "#A64B38", "--mark-bg": "#F6E6E1", "--accent": "#26221C", "--accent-fg": "#FAF8F3", "--btn-border": "#D5CEBF", "--outer-bg": "#E5E1D6"}, "lingshu": {"name": "灵枢青瓷 · 松石绿 (对标竞品)", "--paper": "#F4F5F0", "--surface": "#FFFFFF", "--surface-subtle": "#F8FAF7", "--ink": "#1A2421", "--ink-solid": "#1D5B50", "--ink-soft": "#42544E", "--ink-mute": "#73857E", "--ink-faint": "#9EB0A9", "--rule": "rgba(29, 91, 80, 0.09)", "--rule-strong": "#D5DFDC", "--rule-soft": "#EBF0EE", "--numeral": "#B5C4BF", "--mark": "#1D5B50", "--mark-bg": "#E1F0EC", "--accent": "#1D5B50", "--accent-fg": "#FFFFFF", "--btn-border": "#C4D4CE", "--outer-bg": "#E2E7E4"}, "parchment": {"name": "古籍羊皮 · 暖杏护眼", "--paper": "#F3ECD8", "--surface": "#FCF8EE", "--surface-subtle": "#F7F1E1", "--ink": "#2B2318", "--ink-solid": "#30271B", "--ink-soft": "#5E513F", "--ink-mute": "#8A7D68", "--ink-faint": "#AFA28C", "--rule": "rgba(48, 39, 27, 0.09)", "--rule-strong": "#DDD3BC", "--rule-soft": "#EAE1CC", "--numeral": "#BFB399", "--mark": "#9E4735", "--mark-bg": "#F2DCD4", "--accent": "#382B1E", "--accent-fg": "#FCF8EE", "--btn-border": "#C8B99E", "--outer-bg": "#DFD5BE"}, "celadon": {"name": "宋刻竹青 · 润眼茶白", "--paper": "#EBF0EA", "--surface": "#F9FBF9", "--surface-subtle": "#F1F5F0", "--ink": "#1F2821", "--ink-solid": "#232D25", "--ink-soft": "#4A594D", "--ink-mute": "#758578", "--ink-faint": "#9BA99E", "--rule": "rgba(35, 45, 37, 0.09)", "--rule-strong": "#CFDAD1", "--rule-soft": "#E1EAE2", "--numeral": "#B0C0B3", "--mark": "#8E4A3B", "--mark-bg": "#EFE0DC", "--accent": "#2B4738", "--accent-fg": "#F9FBF9", "--btn-border": "#B8C7BB", "--outer-bg": "#D8E2D9"}, "stone": {"name": "澄心冷灰 · 碑拓质感", "--paper": "#EFECE6", "--surface": "#FAF9F6", "--surface-subtle": "#F4F2ED", "--ink": "#22201C", "--ink-solid": "#262420", "--ink-soft": "#54514B", "--ink-mute": "#827E76", "--ink-faint": "#A8A49C", "--rule": "rgba(38, 36, 32, 0.08)", "--rule-strong": "#D8D4CC", "--rule-soft": "#E6E2DA", "--numeral": "#BDB8AE", "--mark": "#964B3B", "--mark-bg": "#EFE0DC", "--accent": "#262420", "--accent-fg": "#FAF9F6", "--btn-border": "#C4BFB5", "--outer-bg": "#DAD6CE"}, "pure": {"name": "素练极简 · 现代纯白", "--paper": "#F6F7F9", "--surface": "#FFFFFF", "--surface-subtle": "#F9FAFB", "--ink": "#111827", "--ink-solid": "#1E293B", "--ink-soft": "#4B5563", "--ink-mute": "#6B7280", "--ink-faint": "#9CA3AF", "--rule": "rgba(17, 24, 39, 0.07)", "--rule-strong": "#E5E7EB", "--rule-soft": "#F3F4F6", "--numeral": "#CBD5E1", "--mark": "#B93829", "--mark-bg": "#FEE2E2", "--accent": "#18181B", "--accent-fg": "#FFFFFF", "--btn-border": "#D1D5DB", "--outer-bg": "#E5E7EB"}, "dark": {"name": "玄墨夜读 · 暗色纸感", "--paper": "#181614", "--surface": "#221F1C", "--surface-subtle": "#282420", "--ink": "#DDD5C7", "--ink-solid": "#E8E0D2", "--ink-soft": "#B0A797", "--ink-mute": "#857C6D", "--ink-faint": "#5E574B", "--rule": "rgba(255, 248, 235, 0.08)", "--rule-strong": "#36312A", "--rule-soft": "#2C2822", "--numeral": "#4A4339", "--mark": "#D47660", "--mark-bg": "#422822", "--accent": "#D47660", "--accent-fg": "#181614", "--btn-border": "#484138", "--outer-bg": "#0F0E0C"}}/*S1-THEME-END*/;

  const WALLPAPER_PRESETS = /*S1-WALLPAPER-BEGIN*/{"none": "none", "xuan": "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='600' height='600' viewBox='0 0 600 600'%3E%3Crect width='600' height='600' fill='%23EFECE2'/%3E%3Cg stroke='%23C9C0AC' stroke-width='0.8' opacity='0.45' fill='none'%3E%3Cpath d='M0 120 Q 150 90 300 130 T 600 110'/%3E%3Cpath d='M0 280 Q 180 310 350 260 T 600 290'/%3E%3Cpath d='M0 450 Q 120 420 280 460 T 600 440'/%3E%3C/g%3E%3Ccircle cx='480' cy='140' r='90' fill='%23DFD6C3' opacity='0.35'/%3E%3Ccircle cx='140' cy='460' r='130' fill='%23E3DAC8' opacity='0.4'/%3E%3C/svg%3E\")", "mist": "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='1200' height='800' viewBox='0 0 1200 800'%3E%3Cdefs%3E%3ClinearGradient id='g1' x1='0' y1='0' x2='0' y2='1'%3E%3Cstop offset='0%25' stop-color='%23DCE5E2'/%3E%3Cstop offset='100%25' stop-color='%23F2EFE6'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='1200' height='800' fill='url(%23g1)'/%3E%3Cpath d='M0 540 Q 240 420 520 500 T 1020 460 L 1200 510 L 1200 800 L 0 800 Z' fill='%23BACAC4' opacity='0.45'/%3E%3Cpath d='M0 620 Q 320 520 680 600 T 1200 560 L 1200 800 L 0 800 Z' fill='%239EB3AC' opacity='0.45'/%3E%3Cpath d='M0 700 Q 420 640 820 710 T 1200 680 L 1200 800 L 0 800 Z' fill='%23839B94' opacity='0.4'/%3E%3Ccircle cx='920' cy='210' r='54' fill='%23C87D6A' opacity='0.38'/%3E%3C/svg%3E\")", "bamboo": "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='900' height='700' viewBox='0 0 900 700'%3E%3Crect width='900' height='700' fill='%23EAEFE8'/%3E%3Cg stroke='%238BA190' stroke-linecap='round' opacity='0.35' fill='none'%3E%3Cline x1='760' y1='0' x2='730' y2='700' stroke-width='6'/%3E%3Cline x1='810' y1='80' x2='795' y2='700' stroke-width='4'/%3E%3Cpath d='M750 180 Q 680 150 640 190' stroke-width='3'/%3E%3Cpath d='M745 320 Q 670 300 610 340' stroke-width='3'/%3E%3Cpath d='M798 260 Q 850 230 885 265' stroke-width='2.5'/%3E%3C/g%3E%3C/svg%3E\")"}/*S1-WALLPAPER-END*/;

  const SAFE_TOKENS = /*S1-SAFE-TOKENS-BEGIN*/["--paper", "--surface", "--ink", "--mark", "--mark-bg"]/*S1-SAFE-TOKENS-END*/;

  const THEME_KEYS = ['default', 'lingshu', 'parchment', 'celadon', 'stone', 'pure', 'dark'];
  const THEME_NAMES = {
    default: '温润手稿 · 默认', lingshu: '灵枢青瓷 · 松绿', parchment: '古籍羊皮 · 暖杏',
    celadon: '宋刻竹青 · 护眼', stone: '澄心冷灰 · 碑拓', pure: '素练极简 · 纯白',
    dark: '玄墨夜读 · 暗色纸感'
  };
  const THEME_SWATCH = {
    default: ['#F3F1EA', '#A64B38'], lingshu: ['#F4F5F0', '#1D5B50'],
    parchment: ['#F3ECD8', '#9E4735'], celadon: ['#EBF0EA', '#2D6659'],
    stone: ['#EFECE6', '#964B3B'], pure: ['#F7F8FA', '#1E293B'],
    dark: ['#181614', '#C86D58']
  };
  const BG_NAMES = { none: '无背景图 · 纯净纸底', xuan: '宣纸云纹 · 手工纤维', mist: '江南烟雨 · 水墨远山', bamboo: '宋刻竹影 · 案头清风' };
  const OVERLAY = { min: 65, max: 98, uploadAuto: 82, presetAuto: 84, presetAutoAbove: 92, default: 90 };
  const BLUR = { min: 0, max: 20, default: 0 };

  const state = {
    themeKey: 'default',
    custom: null,
    background: { type: 'none', preset: null, file: null, overlay: OVERLAY.default, blur: BLUR.default },
    version: null,
    dataRoot: null,
    dataRootTemporary: false,
    book: null
  };

  let saveTimer = null;
  let toastTimer = null;

  /* ---------- 基础工具 ---------- */
  function clampNumber(value, low, high, fallback) {
    const num = Number(value);
    if (!isFinite(num)) return fallback;
    return Math.max(low, Math.min(high, num));
  }

  function showToast(message) {
    let toast = document.getElementById('biyu-shell-toast');
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add('show');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 2600);
  }

  function schedulePersist() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(persistPrefs, 350);
  }

  function persistPrefs() {
    const payload = {
      theme: state.themeKey,
      custom: state.custom,
      background: {
        type: state.background.type,
        preset: state.background.preset,
        file: state.background.file,
        overlay: state.background.overlay,
        blur: state.background.blur
      }
    };
    fetch('/api/ui/prefs', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).catch(() => { /* 离线不打断使用 */ });
  }

  /* ---------- 主题引擎 ---------- */
  function applyThemeTokens(key) {
    const preset = THEME_PRESETS[key] || THEME_PRESETS.default;
    const root = document.documentElement;
    Object.keys(preset).forEach((name) => {
      if (name.indexOf('--') === 0) root.style.setProperty(name, preset[name]);
    });
  }

  function applyCustomColors() {
    const root = document.documentElement;
    SAFE_TOKENS.forEach((token) => {
      const value = state.custom && state.custom[token];
      if (value) {
        root.style.setProperty(token, value);
        if (token === '--ink') root.style.setProperty('--ink-solid', value);
      }
    });
  }

  function resolveThemeKey(raw) {
    return raw && THEME_PRESETS[raw] ? raw : 'default';
  }

  function syncThemeInputs() {
    const preset = THEME_PRESETS[state.themeKey];
    THEME_KEYS.forEach((key) => {
      const btn = document.getElementById('biyu-theme-' + key);
      if (btn) btn.classList.toggle('active', key === state.themeKey);
    });
    const values = {
      '--paper': preset['--paper'], '--surface': preset['--surface'],
      '--ink': preset['--ink'], '--mark': preset['--mark'], '--mark-bg': preset['--mark-bg']
    };
    SAFE_TOKENS.forEach((token) => {
      const input = document.getElementById('biyu-picker' + token.replace(/-([a-z])/g, (m, c) => c.toUpperCase()));
      if (input) input.value = (state.custom && state.custom[token]) || values[token];
    });
    const resetBtn = document.getElementById('biyu-theme-reset');
    if (resetBtn) {
      const hasCustom = !!(state.custom && Object.keys(state.custom).length);
      resetBtn.textContent = hasCustom ? '恢复默认（清除取色覆盖）' : '恢复默认';
    }
  }

  function chooseTheme(key) {
    if (!THEME_PRESETS[key]) return;
    state.themeKey = key;
    applyThemeTokens(key);
    applyCustomColors();
    syncThemeInputs();
    schedulePersist();
    showToast('已切换主题：' + THEME_PRESETS[key].name);
  }

  function pickColor(token, value) {
    if (SAFE_TOKENS.indexOf(token) === -1) return;
    if (!state.custom) state.custom = {};
    state.custom[token] = value;
    const root = document.documentElement;
    root.style.setProperty(token, value);
    if (token === '--ink') root.style.setProperty('--ink-solid', value);
    syncThemeInputs();
    schedulePersist();
  }

  function resetAppearance() {
    state.custom = null;
    applyThemeTokens(state.themeKey);
    state.background = { type: 'none', preset: null, file: null, overlay: OVERLAY.default, blur: BLUR.default };
    applyBackgroundTokens();
    syncThemeInputs();
    syncBackgroundInputs();
    schedulePersist();
    showToast('已恢复默认：清除取色覆盖，回到当前主题原值');
  }

  /* ---------- 背景图引擎 ---------- */
  function applyBackgroundTokens() {
    const root = document.documentElement;
    let image = 'none';
    if (state.background.type === 'preset' && WALLPAPER_PRESETS[state.background.preset]) {
      image = WALLPAPER_PRESETS[state.background.preset];
    } else if (state.background.type === 'custom' && state.background.file) {
      image = 'url("/api/ui/background-file/' + encodeURIComponent(state.background.file) + '")';
    }
    root.style.setProperty('--bg-image', image);
    root.style.setProperty('--bg-overlay-alpha', (state.background.overlay / 100).toFixed(2));
    root.style.setProperty('--bg-blur', state.background.blur + 'px');
  }

  function syncBackgroundInputs() {
    const activeKey = state.background.type === 'preset' ? state.background.preset
      : (state.background.type === 'custom' ? 'custom' : 'none');
    ['none', 'xuan', 'mist', 'bamboo', 'custom'].forEach((key) => {
      const btn = document.getElementById('biyu-bg-' + key);
      if (btn) btn.classList.toggle('active', key === activeKey);
    });
    const overlaySlider = document.getElementById('biyu-bg-overlay-slider');
    const overlayLabel = document.getElementById('biyu-bg-overlay-label');
    if (overlaySlider) overlaySlider.value = state.background.overlay;
    if (overlayLabel) overlayLabel.textContent = state.background.overlay + '%';
    const blurSlider = document.getElementById('biyu-bg-blur-slider');
    const blurLabel = document.getElementById('biyu-bg-blur-label');
    if (blurSlider) blurSlider.value = state.background.blur;
    if (blurLabel) blurLabel.textContent = state.background.blur + 'px';
  }

  function setWallpaperPreset(key) {
    if (key === 'none') {
      state.background = { type: 'none', preset: null, file: null, overlay: state.background.overlay, blur: state.background.blur };
      applyBackgroundTokens();
      syncBackgroundInputs();
      schedulePersist();
      showToast('已恢复纯色纸底（无背景图）');
      return;
    }
    if (!WALLPAPER_PRESETS[key]) return;
    state.background.type = 'preset';
    state.background.preset = key;
    state.background.file = null;
    if (state.background.overlay > OVERLAY.presetAutoAbove) {
      state.background.overlay = OVERLAY.presetAuto;
    }
    applyBackgroundTokens();
    syncBackgroundInputs();
    schedulePersist();
    showToast('已启用背景纹理：' + BG_NAMES[key]);
  }

  function updateOverlay(value) {
    state.background.overlay = clampNumber(value, OVERLAY.min, OVERLAY.max, OVERLAY.default);
    applyBackgroundTokens();
    const label = document.getElementById('biyu-bg-overlay-label');
    if (label) label.textContent = Math.round(state.background.overlay) + '%';
    schedulePersist();
  }

  function updateBlur(value) {
    state.background.blur = clampNumber(value, BLUR.min, BLUR.max, BLUR.default);
    applyBackgroundTokens();
    const label = document.getElementById('biyu-bg-blur-label');
    if (label) label.textContent = Math.round(state.background.blur) + 'px';
    schedulePersist();
  }

  function handleBackgroundUpload(file) {
    if (!file) return;
    if (!/^image\//.test(file.type || '')) {
      showToast('仅支持图片（PNG / JPG / WebP）');
      return;
    }
    const reader = new FileReader();
    reader.onload = function (event) {
      const dataUrl = String(event.target.result || '');
      const comma = dataUrl.indexOf(',');
      if (comma < 0) { showToast('图片读取失败'); return; }
      fetch('/api/ui/background', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: file.name || 'background', data: dataUrl.slice(comma + 1) })
      }).then((resp) => resp.json().then((body) => ({ ok: resp.ok, body })))
        .then(({ ok, body }) => {
          if (!ok) {
            showToast((body && body.detail) || '背景图上传失败：仅支持图片');
            return;
          }
          state.background.type = 'custom';
          state.background.preset = null;
          state.background.file = body.file;
          state.background.overlay = OVERLAY.uploadAuto;
          applyBackgroundTokens();
          syncBackgroundInputs();
          schedulePersist();
          showToast('已应用自定义背景（自动开启 82% 宣纸护眼蒙层）');
        })
        .catch(() => showToast('背景图上传失败：服务不可达'));
    };
    reader.readAsDataURL(file);
  }

  /* ---------- 外观抽屉 ---------- */
  function buildDrawer() {
    const drawer = document.createElement('aside');
    drawer.className = 'biyu-theme-drawer';
    drawer.id = 'biyu-theme-drawer';

    const head = document.createElement('div');
    head.className = 'biyu-drawer-head';
    const title = document.createElement('span');
    title.className = 'biyu-drawer-title';
    title.textContent = '外观 · 纸感配色与自定义背景图';
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'biyu-drawer-close';
    close.textContent = '关闭';
    close.addEventListener('click', toggleDrawer);
    head.appendChild(title);
    head.appendChild(close);
    drawer.appendChild(head);

    const intro = document.createElement('p');
    intro.className = 'biyu-drawer-intro';
    intro.textContent = '默认「温润手稿·云宣白卡」，拉开纸底与卡片明度差；支持七套预设与自定义背景壁纸。';
    drawer.appendChild(intro);

    const presetLabel = document.createElement('p');
    presetLabel.className = 'biyu-eyebrow';
    presetLabel.textContent = '1 · 预设主题色板（7 套）';
    drawer.appendChild(presetLabel);

    const presetGrid = document.createElement('div');
    presetGrid.className = 'biyu-preset-grid';
    THEME_KEYS.forEach((key) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'biyu-preset-btn';
      btn.id = 'biyu-theme-' + key;
      const circle = document.createElement('span');
      circle.className = 'biyu-preset-circle';
      circle.style.background = THEME_SWATCH[key][0];
      circle.style.borderColor = THEME_SWATCH[key][1];
      const label = document.createElement('span');
      label.textContent = THEME_NAMES[key];
      btn.appendChild(circle);
      btn.appendChild(label);
      btn.addEventListener('click', () => chooseTheme(key));
      presetGrid.appendChild(btn);
    });
    drawer.appendChild(presetGrid);

    const bgLabel = document.createElement('p');
    bgLabel.className = 'biyu-eyebrow';
    bgLabel.textContent = '2 · 自定义背景图与意境纹理';
    drawer.appendChild(bgLabel);

    const bgGrid = document.createElement('div');
    bgGrid.className = 'biyu-bg-grid';
    ['none', 'xuan', 'mist', 'bamboo'].forEach((key) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'biyu-bg-thumb';
      btn.id = 'biyu-bg-' + key;
      if (key !== 'none') btn.style.backgroundImage = WALLPAPER_PRESETS[key];
      else btn.style.background = 'var(--paper)';
      const label = document.createElement('span');
      label.className = 'biyu-bg-thumb-label';
      label.textContent = BG_NAMES[key];
      btn.appendChild(label);
      btn.addEventListener('click', () => setWallpaperPreset(key));
      bgGrid.appendChild(btn);
    });
    const customThumb = document.createElement('button');
    customThumb.type = 'button';
    customThumb.className = 'biyu-bg-thumb';
    customThumb.id = 'biyu-bg-custom';
    customThumb.textContent = '';
    const customLabel = document.createElement('span');
    customLabel.className = 'biyu-bg-thumb-label';
    customLabel.textContent = '本地图片';
    customThumb.appendChild(customLabel);
    customThumb.addEventListener('click', () => {
      const input = document.getElementById('biyu-bg-file');
      if (input) input.click();
    });
    bgGrid.appendChild(customThumb);
    drawer.appendChild(bgGrid);

    const uploadRow = document.createElement('div');
    uploadRow.className = 'biyu-upload-row';
    const uploadBtn = document.createElement('button');
    uploadBtn.type = 'button';
    uploadBtn.className = 'biyu-b2 biyu-bs';
    uploadBtn.textContent = '上传本地背景图 (JPG / PNG / WebP)';
    uploadBtn.addEventListener('click', () => {
      const input = document.getElementById('biyu-bg-file');
      if (input) input.click();
    });
    const clearBtn = document.createElement('button');
    clearBtn.type = 'button';
    clearBtn.className = 'biyu-b3 biyu-bs';
    clearBtn.textContent = '清除背景图';
    clearBtn.addEventListener('click', () => setWallpaperPreset('none'));
    uploadRow.appendChild(uploadBtn);
    uploadRow.appendChild(clearBtn);
    drawer.appendChild(uploadRow);

    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = 'image/png,image/jpeg,image/webp';
    fileInput.id = 'biyu-bg-file';
    fileInput.style.display = 'none';
    fileInput.addEventListener('change', (event) => {
      handleBackgroundUpload(event.target.files && event.target.files[0]);
      event.target.value = '';
    });
    drawer.appendChild(fileInput);

    drawer.appendChild(sliderRow('biyu-bg-overlay-slider', 'biyu-bg-overlay-label',
      '纸感蒙层浓度（护眼防花眼）：', OVERLAY.min, OVERLAY.max, OVERLAY.default, '%', updateOverlay));
    drawer.appendChild(sliderRow('biyu-bg-blur-slider', 'biyu-bg-blur-label',
      '背景柔焦模糊度：', BLUR.min, BLUR.max, BLUR.default, 'px', updateBlur));

    const colorLabel = document.createElement('p');
    colorLabel.className = 'biyu-eyebrow';
    colorLabel.textContent = '3 · 核心色彩令牌自由取色';
    drawer.appendChild(colorLabel);

    const tokenLabels = {
      '--paper': '窗口纸底色 (--paper)',
      '--surface': '卡片表面色 (--surface)',
      '--ink': '正文墨色 (--ink)',
      '--mark': '重点信号色 (--mark)',
      '--mark-bg': '好句划选底色 (--mark-bg)'
    };
    SAFE_TOKENS.forEach((token) => {
      const row = document.createElement('div');
      row.className = 'biyu-color-row';
      const label = document.createElement('span');
      label.textContent = tokenLabels[token];
      const input = document.createElement('input');
      input.type = 'color';
      input.id = 'biyu-picker' + token.replace(/-([a-z])/g, (m, c) => c.toUpperCase());
      input.addEventListener('input', () => pickColor(token, input.value));
      row.appendChild(label);
      row.appendChild(input);
      drawer.appendChild(row);
    });

    const foot = document.createElement('div');
    foot.className = 'biyu-drawer-foot';
    const resetBtn = document.createElement('button');
    resetBtn.type = 'button';
    resetBtn.className = 'biyu-b2 biyu-bs';
    resetBtn.id = 'biyu-theme-reset';
    resetBtn.textContent = '恢复默认';
    resetBtn.addEventListener('click', resetAppearance);
    foot.appendChild(resetBtn);
    drawer.appendChild(foot);

    return drawer;
  }

  function sliderRow(id, labelId, text, min, max, value, unit, onInput) {
    const row = document.createElement('div');
    row.className = 'biyu-slider-row';
    const label = document.createElement('span');
    label.innerHTML = '';
    const prefix = document.createElement('span');
    prefix.textContent = text;
    const strong = document.createElement('strong');
    strong.id = labelId;
    strong.textContent = value + unit;
    label.appendChild(prefix);
    label.appendChild(strong);
    const input = document.createElement('input');
    input.type = 'range';
    input.id = id;
    input.min = String(min);
    input.max = String(max);
    input.value = String(value);
    input.addEventListener('input', () => onInput(input.value));
    row.appendChild(label);
    row.appendChild(input);
    return row;
  }

  function toggleDrawer() {
    const drawer = document.getElementById('biyu-theme-drawer');
    if (drawer) drawer.classList.toggle('open');
  }

  /* ---------- 顶栏与状态栏 ---------- */
  function currentPage() {
    const path = location.pathname.replace(/\\/g, '/');
    const file = path.split('/').pop() || 'index.html';
    return file.replace(/\.html$/, '').replace(/^$/, 'index');
  }

  function buildTitlebarNavLinks() {
    const nav = document.createElement('nav');
    nav.className = 'biyu-nav-links';
    nav.setAttribute('aria-label', '主导航');

    const shelfBtn = document.createElement('a');
    shelfBtn.className = 'biyu-nav-btn';
    shelfBtn.href = '/';
    shelfBtn.textContent = '书架';
    if (currentPage() === 'index') shelfBtn.classList.add('current');
    nav.appendChild(shelfBtn);

    const book = state.book;
    if (book) {
      const bookBtn = document.createElement('a');
      bookBtn.className = 'biyu-nav-btn';
      const inBook = ['book', 'workbench', 'overview', 'voiceprint', 'good-sentences', 'memory'].indexOf(currentPage()) !== -1;
      if (inBook) bookBtn.classList.add('current');
      bookBtn.href = '/workbench.html?book=' + encodeURIComponent(book.id);
      bookBtn.textContent = '《' + (book.display_name || book.title || book.name) + '》';

      const pills = document.createElement('span');
      pills.className = 'biyu-secondary-pills';
      const pillDefs = [
        ['全书概览', '/overview.html?book=' + encodeURIComponent(book.id), 'overview'],
        ['声纹', '/voiceprint.html?book=' + encodeURIComponent(book.id), 'voiceprint'],
        ['好句', '/good-sentences.html?book=' + encodeURIComponent(book.id), 'good-sentences'],
        ['回收站', '/trash.html', 'trash']
      ];
      pillDefs.forEach((def) => {
        const pill = document.createElement('a');
        pill.className = 'biyu-sub-pill';
        pill.href = def[1];
        pill.textContent = def[0];
        if (currentPage() === def[2]) pill.classList.add('current');
        pills.appendChild(pill);
      });
      nav.appendChild(bookBtn);
      nav.appendChild(pills);
    }
    return nav;
  }

  function refreshTitlebarNav() {
    const header = document.querySelector('.biyu-titlebar');
    if (!header) return;
    const left = header.querySelector('.biyu-win-left');
    const oldNav = header.querySelector('.biyu-nav-links');
    if (left && oldNav) {
      const divider = left.querySelector('.biyu-brand-divider');
      if (divider) divider.insertAdjacentElement('afterend', buildTitlebarNavLinks());
      oldNav.remove();
    }
    if (state.book) {
      const settingsBtn = header.querySelector('.biyu-win-right a.biyu-nav-btn[href$="#settings-entry"]');
      if (settingsBtn) settingsBtn.href = '/settings.html?book=' + encodeURIComponent(state.book.id);
    }
  }

  function buildTitlebar(books) {
    const header = document.createElement('header');
    header.className = 'biyu-titlebar';

    const left = document.createElement('div');
    left.className = 'biyu-win-left';

    const brand = document.createElement('a');
    brand.className = 'biyu-brand';
    brand.href = '/';
    brand.title = '返回书架首页';
    const seal = document.createElement('span');
    seal.className = 'biyu-seal';
    seal.textContent = '驭';
    const wordmark = document.createElement('span');
    wordmark.className = 'biyu-wordmark';
    wordmark.textContent = '笔驭';
    brand.appendChild(seal);
    brand.appendChild(wordmark);
    left.appendChild(brand);

    const divider = document.createElement('span');
    divider.className = 'biyu-brand-divider';
    left.appendChild(divider);

    left.appendChild(buildTitlebarNavLinks());
    header.appendChild(left);

    const right = document.createElement('div');
    right.className = 'biyu-win-right';

    const gacha = document.createElement('button');
    gacha.type = 'button';
    gacha.className = 'biyu-gacha-switch';
    gacha.title = '抽卡模式：细纲抽一版自动批准（后续版本上线）';
    const dot = document.createElement('span');
    dot.className = 'biyu-gacha-dot';
    const gachaLabel = document.createElement('span');
    gachaLabel.textContent = '抽卡模式';
    gacha.appendChild(dot);
    gacha.appendChild(gachaLabel);
    gacha.addEventListener('click', () => showToast('抽卡模式将于后续版本开放'));
    right.appendChild(gacha);

    const themeTrigger = document.createElement('button');
    themeTrigger.type = 'button';
    themeTrigger.className = 'biyu-theme-trigger';
    themeTrigger.id = 'biyu-theme-trigger';
    const swatch = document.createElement('span');
    swatch.className = 'biyu-swatch-dot';
    const themeText = document.createElement('span');
    themeText.textContent = '外观与背景';
    themeTrigger.appendChild(swatch);
    themeTrigger.appendChild(themeText);
    themeTrigger.addEventListener('click', toggleDrawer);
    right.appendChild(themeTrigger);

    const settingsBtn = document.createElement('a');
    settingsBtn.className = 'biyu-nav-btn';
    settingsBtn.textContent = '设置';
    const page = currentPage();
    const bookParam = state.book ? '?book=' + encodeURIComponent(state.book.id) : '';
    if (page === 'settings') settingsBtn.classList.add('current');
    settingsBtn.href = state.book ? '/settings.html' + bookParam : '/index.html#settings-entry';
    right.appendChild(settingsBtn);

    const controls = document.createElement('span');
    controls.className = 'biyu-win-controls';
    controls.title = '窗口控制在桌面客户端形态提供';
    ['—', '□', '×'].forEach((glyph) => {
      const btn = document.createElement('span');
      btn.className = 'biyu-win-ctrl-btn';
      btn.textContent = glyph;
      controls.appendChild(btn);
    });
    right.appendChild(controls);

    header.appendChild(right);
    return header;
  }

  function buildStatusBar() {
    const bar = document.createElement('footer');
    bar.className = 'biyu-statusbar';
    const leftGroup = document.createElement('span');
    leftGroup.className = 'biyu-sb-group';
    const dot = document.createElement('span');
    dot.className = 'biyu-sb-dot';
    const pathText = document.createElement('span');
    pathText.id = 'biyu-sb-data-root';
    pathText.textContent = state.dataRoot
      ? '本地自动落盘：' + state.dataRoot + (state.dataRootTemporary ? '（临时数据根）' : '')
      : '';
    leftGroup.appendChild(dot);
    leftGroup.appendChild(pathText);
    const rightGroup = document.createElement('span');
    rightGroup.className = 'biyu-sb-group';
    // S-3 决策6A:状态栏常驻内测 Q 群胶囊 + 联系反馈弹窗
    const contactPill = document.createElement('button');
    contactPill.type = 'button';
    contactPill.className = 'biyu-contact-pill';
    contactPill.id = 'biyu-contact-pill';
    contactPill.title = '内测作者交流 Q 群与问题反馈';
    contactPill.textContent = '💬 内测 Q 群：892467108 · 反馈';
    contactPill.addEventListener('click', openContactFeedback);
    rightGroup.appendChild(contactPill);
    const versionText = document.createElement('span');
    versionText.textContent = state.version ? '笔驭 v' + state.version : '';
    rightGroup.appendChild(versionText);
    bar.appendChild(leftGroup);
    bar.appendChild(rightGroup);
    return bar;
  }

  /* ---------- S-3 决策6A:联系与反馈弹窗(图纸 openContactFeedbackModal 搬运) ---------- */
  function openContactFeedback() {
    let overlay = document.getElementById('biyu-contact-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.className = 'biyu-modal-overlay';
      overlay.id = 'biyu-contact-overlay';
      overlay.innerHTML =
        '<div class="biyu-modal" role="dialog" aria-modal="true" aria-labelledby="biyu-contact-title">' +
        '<h2 id="biyu-contact-title">💬 笔驭 (biyu) 作者交流群与问题反馈</h2>' +
        '<div class="card" style="background:var(--surface-subtle);margin-bottom:14px">' +
        '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:8px">' +
        '<div><div style="font-size:15px;font-weight:600">官方内测作者交流 QQ 群：<code style="color:var(--mark);font-size:15px">892467108</code></div>' +
        '<div style="font-size:12.5px;color:var(--ink-mute)">群内提供声纹卡分享、拆书模板、保真闸调优技巧与开发组直接答疑</div></div>' +
        '<button type="button" class="b2 bs" id="biyu-contact-copy">复制群号</button></div>' +
        '<div style="font-size:12px;color:var(--ink-soft);border-top:1px solid var(--rule);padding-top:8px">' +
        '· 反馈邮箱：<code>feedback@biyu.studio</code></div></div>' +
        '<p class="eyebrow" style="margin-bottom:6px">快速提交问题或建议</p>' +
        '<textarea class="biyu-contact-textarea" id="biyu-contact-text" rows="3" placeholder="写下你遇到的问题或功能建议…"></textarea>' +
        '<div class="biyu-modal-actions">' +
        '<button type="button" class="b3" id="biyu-contact-close">关闭</button>' +
        '<button type="button" class="b1" id="biyu-contact-send">提交反馈</button></div>' +
        '</div>';
      document.body.appendChild(overlay);
      overlay.addEventListener('click', (event) => {
        if (event.target === overlay) overlay.hidden = true;
      });
      document.getElementById('biyu-contact-close').addEventListener('click', () => { overlay.hidden = true; });
      document.getElementById('biyu-contact-copy').addEventListener('click', (event) => {
        if (navigator.clipboard) navigator.clipboard.writeText('892467108');
        event.target.textContent = '已复制 ✓';
        setTimeout(() => { event.target.textContent = '复制群号'; }, 1500);
      });
      document.getElementById('biyu-contact-send').addEventListener('click', () => {
        const text = document.getElementById('biyu-contact-text').value.trim();
        const subject = encodeURIComponent('笔驭反馈');
        const body = encodeURIComponent(text || '（请在邮件正文中描述你遇到的问题）');
        window.location.href = 'mailto:feedback@biyu.studio?subject=' + subject + '&body=' + body;
      });
    }
    overlay.hidden = false;
  }

  /* ---------- 启动 ---------- */
  function fetchJson(url, fallback) {
    return fetch(url).then((resp) => (resp.ok ? resp.json() : fallback)).catch(() => fallback);
  }

  function loadContext() {
    const params = new URLSearchParams(location.search);
    const bookId = params.get('book');
    const jobs = [fetchJson('/api/version', {}), fetchJson('/api/books', {})];
    return Promise.all(jobs).then((results) => {
      const version = results[0] || {};
      state.version = version.version || null;
      state.dataRoot = version.data_root || null;
      state.dataRootTemporary = !!version.data_root_temporary;
      if (bookId) {
        const list = (results[1] && results[1].books) || [];
        state.book = list.find((entry) => String(entry.id) === String(bookId)
          || entry.name === bookId) || null;
      }
    });
  }

  function loadPrefs() {
    return fetchJson('/api/ui/prefs', null).then((prefs) => {
      if (!prefs) return;
      state.themeKey = resolveThemeKey(prefs.theme);
      state.custom = prefs.custom || null;
      const bg = prefs.background || {};
      state.background = {
        type: ['none', 'preset', 'custom'].indexOf(bg.type) !== -1 ? bg.type : 'none',
        preset: bg.preset || null,
        file: bg.file || null,
        overlay: clampNumber(bg.overlay, OVERLAY.min, OVERLAY.max, OVERLAY.default),
        blur: clampNumber(bg.blur, BLUR.min, BLUR.max, BLUR.default)
      };
      if (state.background.type === 'custom' && !state.background.file) state.background.type = 'none';
      if (state.background.type === 'preset' && !WALLPAPER_PRESETS[state.background.preset]) {
        state.background.type = 'none';
        state.background.preset = null;
      }
    });
  }

  function mountShell() {
    const oldNav = document.querySelector('nav.top-nav');
    if (oldNav) oldNav.style.display = 'none';

    const wallpaper = document.createElement('div');
    wallpaper.className = 'biyu-shell-bg-wallpaper';
    wallpaper.setAttribute('aria-hidden', 'true');
    const overlay = document.createElement('div');
    overlay.className = 'biyu-shell-bg-overlay';
    overlay.setAttribute('aria-hidden', 'true');
    document.body.insertBefore(overlay, document.body.firstChild);
    document.body.insertBefore(wallpaper, overlay);

    const titlebar = buildTitlebar();
    document.body.insertBefore(titlebar, wallpaper.nextSibling);

    const drawer = buildDrawer();
    document.body.appendChild(drawer);

    const statusBar = buildStatusBar();
    document.body.appendChild(statusBar);

    const toast = document.createElement('div');
    toast.className = 'biyu-toast';
    toast.id = 'biyu-shell-toast';
    document.body.appendChild(toast);

    document.body.classList.add('biyu-shell-active');
    if (!oldNav) {
      console.warn('[biyu-shell] 本页没有旧导航容器，已按无壳降级处理：仅注入新壳。');
    }
  }

  function boot() {
    mountShell();
    applyThemeTokens(state.themeKey);
    applyBackgroundTokens();
    loadContext()
      .then(loadPrefs)
      .then(() => {
        refreshTitlebarNav();
        applyThemeTokens(state.themeKey);
        applyCustomColors();
        applyBackgroundTokens();
        syncThemeInputs();
        syncBackgroundInputs();
        const statusBarPath = document.getElementById('biyu-sb-data-root');
        if (statusBarPath) {
          statusBarPath.textContent = state.dataRoot
            ? '本地自动落盘：' + state.dataRoot + (state.dataRootTemporary ? '（临时数据根）' : '')
            : '';
        }
        const versionSpan = document.querySelector('.biyu-statusbar .biyu-sb-group:last-child span');
        if (versionSpan && state.version) versionSpan.textContent = '笔驭 v' + state.version;
      })
      .catch(() => {
        console.warn('[biyu-shell] 壳数据初始化失败，保持默认主题。');
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  window.BiyuShell = {
    chooseTheme: chooseTheme,
    setWallpaperPreset: setWallpaperPreset,
    toggleDrawer: toggleDrawer,
    THEME_PRESETS: THEME_PRESETS,
    WALLPAPER_PRESETS: WALLPAPER_PRESETS
  };
})();
