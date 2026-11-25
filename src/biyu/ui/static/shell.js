/* ==========================================================================
   笔驭 biyu · S-1 全局壳（V2 视觉规范 v2.0）
   主题引擎 / 背景图引擎 / 顶栏与状态栏注入 / 外观抽屉
   事实源：reference_biyu_ai_v2.html（令牌表经零差异测试钉住，勿就地改值）
   持久化：GET/PUT /api/ui/prefs；背景图 POST /api/ui/background（JSON base64）
   ========================================================================== */
(function () {
  'use strict';

  const THEME_PRESETS = /*S1-THEME-BEGIN*/{"default": {"name": "温润手稿 · 云宣白卡 (默认)", "--paper": "#F3F1EA", "--surface": "#FFFFFF", "--surface-subtle": "#F9F8F3", "--ink": "#1F1C18", "--ink-solid": "#26221C", "--ink-soft": "#524C42", "--ink-mute": "#827B6E", "--ink-faint": "#ABA496", "--rule": "rgba(38, 33, 25, 0.08)", "--rule-strong": "#DED8CA", "--rule-soft": "#EFECE4", "--numeral": "#C4BDAE", "--mark": "#A64B38", "--mark-bg": "#F6E6E1", "--accent": "#26221C", "--accent-fg": "#FAF8F3", "--btn-border": "#D5CEBF", "--outer-bg": "#E5E1D6", "--glass-bg": "rgba(255, 255, 255, 0.55)", "--glass-strong": "rgba(255, 255, 255, 0.85)", "--glass-border": "rgba(255, 255, 255, 0.70)", "--glass-blur": "18px", "--glass-shadow": "0 8px 32px rgba(40, 36, 28, 0.10)"}, "lingshu": {"name": "灵枢青瓷 · 松石绿 (对标竞品)", "--paper": "#F4F5F0", "--surface": "#FFFFFF", "--surface-subtle": "#F8FAF7", "--ink": "#1A2421", "--ink-solid": "#1D5B50", "--ink-soft": "#42544E", "--ink-mute": "#73857E", "--ink-faint": "#9EB0A9", "--rule": "rgba(29, 91, 80, 0.09)", "--rule-strong": "#D5DFDC", "--rule-soft": "#EBF0EE", "--numeral": "#B5C4BF", "--mark": "#1D5B50", "--mark-bg": "#E1F0EC", "--accent": "#1D5B50", "--accent-fg": "#FFFFFF", "--btn-border": "#C4D4CE", "--outer-bg": "#E2E7E4", "--glass-bg": "rgba(255, 255, 255, 0.55)", "--glass-strong": "rgba(255, 255, 255, 0.85)", "--glass-border": "rgba(255, 255, 255, 0.70)", "--glass-blur": "18px", "--glass-shadow": "0 8px 32px rgba(40, 36, 28, 0.10)"}, "parchment": {"name": "古籍羊皮 · 暖杏护眼", "--paper": "#F3ECD8", "--surface": "#FCF8EE", "--surface-subtle": "#F7F1E1", "--ink": "#2B2318", "--ink-solid": "#30271B", "--ink-soft": "#5E513F", "--ink-mute": "#8A7D68", "--ink-faint": "#AFA28C", "--rule": "rgba(48, 39, 27, 0.09)", "--rule-strong": "#DDD3BC", "--rule-soft": "#EAE1CC", "--numeral": "#BFB399", "--mark": "#9E4735", "--mark-bg": "#F2DCD4", "--accent": "#382B1E", "--accent-fg": "#FCF8EE", "--btn-border": "#C8B99E", "--outer-bg": "#DFD5BE", "--glass-bg": "rgba(255, 255, 255, 0.55)", "--glass-strong": "rgba(255, 255, 255, 0.85)", "--glass-border": "rgba(255, 255, 255, 0.70)", "--glass-blur": "18px", "--glass-shadow": "0 8px 32px rgba(40, 36, 28, 0.10)"}, "celadon": {"name": "宋刻竹青 · 润眼茶白", "--paper": "#EBF0EA", "--surface": "#F9FBF9", "--surface-subtle": "#F1F5F0", "--ink": "#1F2821", "--ink-solid": "#232D25", "--ink-soft": "#4A594D", "--ink-mute": "#758578", "--ink-faint": "#9BA99E", "--rule": "rgba(35, 45, 37, 0.09)", "--rule-strong": "#CFDAD1", "--rule-soft": "#E1EAE2", "--numeral": "#B0C0B3", "--mark": "#8E4A3B", "--mark-bg": "#EFE0DC", "--accent": "#2B4738", "--accent-fg": "#F9FBF9", "--btn-border": "#B8C7BB", "--outer-bg": "#D8E2D9", "--glass-bg": "rgba(255, 255, 255, 0.55)", "--glass-strong": "rgba(255, 255, 255, 0.85)", "--glass-border": "rgba(255, 255, 255, 0.70)", "--glass-blur": "18px", "--glass-shadow": "0 8px 32px rgba(40, 36, 28, 0.10)"}, "stone": {"name": "澄心冷灰 · 碑拓质感", "--paper": "#EFECE6", "--surface": "#FAF9F6", "--surface-subtle": "#F4F2ED", "--ink": "#22201C", "--ink-solid": "#262420", "--ink-soft": "#54514B", "--ink-mute": "#827E76", "--ink-faint": "#A8A49C", "--rule": "rgba(38, 36, 32, 0.08)", "--rule-strong": "#D8D4CC", "--rule-soft": "#E6E2DA", "--numeral": "#BDB8AE", "--mark": "#964B3B", "--mark-bg": "#EFE0DC", "--accent": "#262420", "--accent-fg": "#FAF9F6", "--btn-border": "#C4BFB5", "--outer-bg": "#DAD6CE", "--glass-bg": "rgba(255, 255, 255, 0.55)", "--glass-strong": "rgba(255, 255, 255, 0.85)", "--glass-border": "rgba(255, 255, 255, 0.70)", "--glass-blur": "18px", "--glass-shadow": "0 8px 32px rgba(40, 36, 28, 0.10)"}, "pure": {"name": "素练极简 · 现代纯白", "--paper": "#F6F7F9", "--surface": "#FFFFFF", "--surface-subtle": "#F9FAFB", "--ink": "#111827", "--ink-solid": "#1E293B", "--ink-soft": "#4B5563", "--ink-mute": "#6B7280", "--ink-faint": "#9CA3AF", "--rule": "rgba(17, 24, 39, 0.07)", "--rule-strong": "#E5E7EB", "--rule-soft": "#F3F4F6", "--numeral": "#CBD5E1", "--mark": "#B93829", "--mark-bg": "#FEE2E2", "--accent": "#18181B", "--accent-fg": "#FFFFFF", "--btn-border": "#D1D5DB", "--outer-bg": "#E5E7EB", "--glass-bg": "rgba(255, 255, 255, 0.55)", "--glass-strong": "rgba(255, 255, 255, 0.85)", "--glass-border": "rgba(255, 255, 255, 0.70)", "--glass-blur": "18px", "--glass-shadow": "0 8px 32px rgba(40, 36, 28, 0.10)"}, "dark": {"name": "玄墨夜读 · 暗色纸感", "--paper": "#181614", "--surface": "#221F1C", "--surface-subtle": "#282420", "--ink": "#DDD5C7", "--ink-solid": "#E8E0D2", "--ink-soft": "#B0A797", "--ink-mute": "#857C6D", "--ink-faint": "#5E574B", "--rule": "rgba(255, 248, 235, 0.08)", "--rule-strong": "#36312A", "--rule-soft": "#2C2822", "--numeral": "#4A4339", "--mark": "#D47660", "--mark-bg": "#422822", "--accent": "#D47660", "--accent-fg": "#181614", "--btn-border": "#484138", "--outer-bg": "#0F0E0C", "--glass-bg": "rgba(34, 31, 28, 0.55)", "--glass-strong": "rgba(30, 28, 26, 0.86)", "--glass-border": "rgba(255, 255, 255, 0.10)", "--glass-blur": "18px", "--glass-shadow": "0 8px 32px rgba(0, 0, 0, 0.35)"}}/*S1-THEME-END*/;

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

  // S-10 3a-2：线条图标统一走 icons.js 的 sprite（每页都加载 icons.js，且先于本文件建好 sprite）
  function shellIcon(name) {
    return '<svg class="icon biyu-gicon" aria-hidden="true"><use href="#biyu-icon-' + name + '"/></svg>';
  }

  function schedulePersist() {
    cacheThemeTokens();
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
  // S-10 3a-2：玻璃令牌随主题写入；引擎不支持 backdrop-filter 时玻璃退 0.96（CSS 侧 @supports 同步兜底）
  function supportsBackdropFilter() {
    try {
      return CSS.supports('backdrop-filter', 'blur(1px)') || CSS.supports('-webkit-backdrop-filter', 'blur(1px)');
    } catch (_) { return true; }
  }

  function applyThemeTokens(key) {
    const preset = THEME_PRESETS[key] || THEME_PRESETS.default;
    const root = document.documentElement;
    Object.keys(preset).forEach((name) => {
      if (name.indexOf('--') === 0) root.style.setProperty(name, preset[name]);
    });
    if (!supportsBackdropFilter()) {
      const dark = key === 'dark';
      root.style.setProperty('--glass-bg', dark ? 'rgba(34, 31, 28, 0.96)' : 'rgba(255, 255, 255, 0.96)');
      root.style.setProperty('--glass-strong', dark ? 'rgba(30, 28, 26, 0.96)' : 'rgba(255, 255, 255, 0.96)');
    }
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
    // S-10 3a-2：背景类型进 data-bg 属性——glass.css 据此在无壁纸时隐藏纸感蒙层、露出柔彩渐变
    root.dataset.bg = state.background.type;
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

    // S-3 T7:快检一级入口在无书态同样可达
    // S-3B 走查修复:有书态下方已有朱砂胶囊(qcBtn),这里不再重复渲染,
    // 否则书页顶栏出现两个同文案同链接的「独立快检」入口(且 id 重复)。
    const book = state.book;
    if (!book) {
      const qcBtn0 = document.createElement('a');
      qcBtn0.className = 'biyu-nav-btn biyu-quickcheck-pill';
      qcBtn0.id = 'nav-quickcheck';
      qcBtn0.href = '/quickcheck.html';
      qcBtn0.textContent = '⚡ 独立快检 / 去AI味';
      if (currentPage() === 'quickcheck') qcBtn0.classList.add('current');
      nav.appendChild(qcBtn0);
    }

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
      // S-3 T7(P0-1A):顶栏一级快检入口(朱砂胶囊)
      const qcBtn = document.createElement('a');
      qcBtn.className = 'biyu-nav-btn biyu-quickcheck-pill';
      qcBtn.id = 'nav-quickcheck';
      qcBtn.href = '/quickcheck.html';
      qcBtn.title = '免建书免填设定，随手粘贴小说即刻查 AI 味词族密度';
      qcBtn.textContent = '⚡ 独立快检 / 去AI味';
      if (currentPage() === 'quickcheck') qcBtn.classList.add('current');
      nav.appendChild(qcBtn);
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

    // S-3 决策6B:全局顶栏「📥 导入向导」入口(三合一弹窗)
    const importWizard = document.createElement('button');
    importWizard.type = 'button';
    importWizard.className = 'biyu-import-wizard-btn';
    importWizard.title = '粘贴正文 / 本地 TXT 批量 / 旧版 biyu 数据根自动识别迁移';
    importWizard.textContent = '📥 导入向导';
    importWizard.addEventListener('click', openImportWizard);
    right.appendChild(importWizard);

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
    contactPill.innerHTML = shellIcon('chat') + '<span>内测 Q 群：892467108 · 反馈</span>';
    contactPill.addEventListener('click', openContactFeedback);
    rightGroup.appendChild(contactPill);
    const versionText = document.createElement('span');
    versionText.textContent = state.version ? '笔驭 v' + state.version : '';
    // S-3 T9 更新降级(工单 E 节):安装版不做壳内自动更新;点击版本区=下载指引。
    // checkout 形态的 git 落后红点机制保留在书架页版本徽章(app.js),此处不重复。
    versionText.style.cursor = 'pointer';
    versionText.title = '点击查看新版获取方式';
    versionText.addEventListener('click', () => {
      showToast('获取新版：请到内测 Q 群（892467108）或官网下载页获取最新安装包；本机数据不受影响。');
    });
    rightGroup.appendChild(versionText);
    bar.appendChild(leftGroup);
    bar.appendChild(rightGroup);
    return bar;
  }

  // 书架等页面上的导入入口按钮(决策6B 第二/三入口)统一接三合一弹窗
  function wireImportTriggers() {
    document.querySelectorAll('.biyu-import-wizard-trigger').forEach((el) => {
      el.addEventListener('click', (event) => {
        event.preventDefault();
        openImportWizard(el.dataset.importTab || 'paste');
      });
    });
  }

  /* ---------- S-3 决策6B:三合一导入向导弹窗(①粘贴 ②本地txt ③旧版数据根迁移) ---------- */
  function openImportWizard(defaultTab) {
    let overlay = document.getElementById('biyu-import-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.className = 'biyu-modal-overlay';
      overlay.id = 'biyu-import-overlay';
      overlay.innerHTML =
        '<div class="biyu-modal biyu-import-modal" role="dialog" aria-modal="true" aria-labelledby="biyu-import-title">' +
        '<h2 id="biyu-import-title">' + shellIcon('import') + ' 导入稿件与迁移向导</h2>' +
        '<p style="font-size:13px;color:var(--ink-mute);margin:0 0 12px">导入本身不花钱，也不会改动现有世界观和角色卡。支持三来源统一入口：</p>' +
        '<div class="row biyu-import-tabs" role="tablist">' +
        '<button type="button" class="b2 bs current" data-tab="paste">① 粘贴正文</button>' +
        '<button type="button" class="b2 bs" data-tab="txt">② 本地 .txt/.md 批量</button>' +
        '<button type="button" class="b2 bs" data-tab="legacy">③ 旧版 biyu 数据根迁移</button></div>' +
        '<div id="biyu-import-body"></div>' +
        '<div class="biyu-modal-actions"><button type="button" class="b3" id="biyu-import-close">取消</button></div>' +
        '</div>';
      document.body.appendChild(overlay);
      overlay.addEventListener('click', (event) => {
        if (event.target === overlay) overlay.hidden = true;
      });
      document.getElementById('biyu-import-close').addEventListener('click', () => { overlay.hidden = true; });
      overlay.querySelectorAll('.biyu-import-tabs button').forEach((btn) => {
        btn.addEventListener('click', () => renderImportTab(btn.dataset.tab));
      });
    }
    overlay.hidden = false;
    renderImportTab(defaultTab || 'paste');
  }

  function importState() {
    return { pending: null };
  }
  const importFlow = importState();

  async function importTargetSelect() {
    const books = await fetch('/api/books').then((r) => r.json()).catch(() => ({ books: [] }));
    const options = (books.books || [])
      .map((b) => '<option value="' + String(b.id).replace(/"/g, '&quot;') + '">' +
        (b.display_name || b.title || b.name) + '</option>')
      .join('');
    return '<label style="display:block;font-size:12px;font-weight:600;color:var(--ink-mute);margin-bottom:4px">导入到哪本书</label>' +
      '<select id="biyu-import-book" class="biyu-contact-textarea" style="height:34px;margin-bottom:10px">' + options + '</select>';
  }

  function importIdentityBlock() {
    return '<div style="background:var(--surface-subtle);border:1px solid var(--rule);border-radius:8px;padding:10px 14px;margin-bottom:12px">' +
      '<div style="font-size:12.5px;font-weight:600;margin-bottom:6px">这批稿件是什么身份？（必须选择）</div>' +
      '<label style="display:flex;gap:8px;align-items:center;font-size:13px;margin-bottom:4px">' +
      '<input type="radio" name="biyu-import-identity" value="candidate" checked><span><strong>作为候选稿</strong> —— 进入待定夺，可继续审读、批注和返修</span></label>' +
      '<label style="display:flex;gap:8px;align-items:center;font-size:13px">' +
      '<input type="radio" name="biyu-import-identity" value="official"><span><strong>作为正式稿</strong> —— 直接存为定稿；下一步可选是否建立本书记忆</span></label></div>';
  }

  async function renderImportTab(tab) {
    document.querySelectorAll('.biyu-import-tabs button').forEach((b) => {
      b.classList.toggle('current', b.dataset.tab === tab);
    });
    const body = document.getElementById('biyu-import-body');
    importFlow.pending = null;
    if (tab === 'legacy') {
      body.innerHTML =
        '<div style="background:var(--surface-subtle);border-radius:8px;padding:12px 14px;margin-bottom:12px">' +
        '<p style="font-weight:600;margin:0 0 8px">自动识别旧版 biyu 数据根目录并一键迁移（纯文件复制，不调模型、不改源目录）</p>' +
        '<div class="row" style="gap:8px;margin-bottom:8px">' +
        '<input id="biyu-legacy-root" class="biyu-contact-textarea" style="flex:1" placeholder="旧版数据根目录，例如 E:\\biyu_v1_data\\books">' +
        '<button type="button" class="b2 bs" id="biyu-legacy-scan">重新识别</button></div>' +
        '<div id="biyu-legacy-result" style="font-size:12.5px;color:var(--ink-soft)"></div></div>' +
        '<div class="biyu-modal-actions" style="justify-content:flex-end">' +
        '<button type="button" class="b1" id="biyu-legacy-commit" disabled>迁移所选到书架</button></div>';
      document.getElementById('biyu-legacy-scan').addEventListener('click', legacyScan);
      document.getElementById('biyu-legacy-commit').addEventListener('click', legacyCommit);
      return;
    }
    const targetSelect = await importTargetSelect();
    const isPaste = tab === 'paste';
    body.innerHTML = targetSelect +
      '<label style="display:block;font-size:12px;font-weight:600;color:var(--ink-mute);margin-bottom:4px">从第几章开始</label>' +
      '<input id="biyu-import-chapter" type="number" min="1" value="1" class="biyu-contact-textarea" style="width:90px;height:34px;margin-bottom:12px">' +
      (isPaste
        ? '<textarea id="biyu-import-text" class="biyu-contact-textarea" rows="6" placeholder="粘贴单章；多章请用「第N章」作为明确分隔"></textarea>'
        : '<input id="biyu-import-files" type="file" accept=".txt,.md" multiple class="biyu-contact-textarea" style="height:auto;padding:8px">') +
      importIdentityBlock() +
      '<div class="biyu-modal-actions" style="justify-content:space-between">' +
      '<span id="biyu-import-preview" style="font-size:12.5px;color:var(--ink-soft);white-space:pre-line"></span>' +
      '<button type="button" class="b1" id="biyu-import-next">预览落点 →</button></div>';
    document.getElementById('biyu-import-next').addEventListener('click', () => importPreview(isPaste));
  }

  async function collectItems(isPaste) {
    const start = Math.max(1, Number(document.getElementById('biyu-import-chapter').value || 1));
    const identity = document.querySelector('input[name="biyu-import-identity"]:checked');
    if (!identity) throw new Error('请选择稿件身份');
    if (isPaste) {
      const text = document.getElementById('biyu-import-text').value.trim();
      if (!text) throw new Error('请先粘贴正文');
      return [{ title: '', chapter: start, content: text, identity: identity.value }];
    }
    const files = [...document.getElementById('biyu-import-files').files];
    if (!files.length) throw new Error('请选择 .txt / .md 文件');
    const items = [];
    for (let i = 0; i < files.length; i++) {
      items.push({
        title: '', chapter: start + i,
        content: await files[i].text(), identity: identity.value,
      });
    }
    return items;
  }

  async function importPreview(isPaste) {
    const button = document.getElementById('biyu-import-next');
    const previewEl = document.getElementById('biyu-import-preview');
    try {
      const items = await collectItems(isPaste);
      const book = document.getElementById('biyu-import-book').value;
      const payload = { items };
      const resp = await fetch('/api/workbench/books/' + encodeURIComponent(book) + '/imports/preview', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.detail || '预览失败');
      importFlow.pending = { book, payload: { ...payload, confirmed: true } };
      previewEl.textContent = body.items.map((item) =>
        '第 ' + item.chapter + ' 章 · ' + (item.identity === 'official' ? '正式稿' : '候选稿') +
        (item.exists ? ' · 已有同身份内容，旧稿移入回收站保留' : '')).join('\n');
      button.textContent = '确认导入';
      button.onclick = () => importCommit();
    } catch (exc) {
      previewEl.textContent = '✗ ' + (exc.message || exc);
    }
  }

  async function importCommit() {
    const button = document.getElementById('biyu-import-next');
    if (!importFlow.pending) return;
    button.disabled = true;
    button.textContent = '导入中…';
    try {
      const { book, payload } = importFlow.pending;
      const resp = await fetch('/api/workbench/books/' + encodeURIComponent(book) + '/imports', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.detail || '导入失败');
      const officials = (body.imported || []).filter((i) => i.identity === 'official');
      document.getElementById('biyu-import-overlay').hidden = true;
      showToast('已导入 ' + (body.imported || []).length + ' 章' +
        (officials.length ? '；正式稿可在读稿页建立本书记忆' : '；候选稿记忆没有改变'));
      if (location.pathname === '/index.html' || location.pathname === '/') {
        setTimeout(() => location.reload(), 900);
      }
    } catch (exc) {
      document.getElementById('biyu-import-preview').textContent = '✗ ' + (exc.message || exc);
    } finally {
      button.disabled = false;
      button.textContent = '预览落点 →';
      button.onclick = () => importPreview(document.querySelector('.biyu-import-tabs .current').dataset.tab === 'paste');
    }
  }

  async function legacyScan() {
    const result = document.getElementById('biyu-legacy-result');
    const root = document.getElementById('biyu-legacy-root').value.trim();
    if (!root) { result.textContent = '请先填写旧版数据根目录。'; return; }
    result.textContent = '正在识别…';
    try {
      const resp = await fetch('/api/migrate/legacy/scan', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_root: root }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.detail || '识别失败');
      if (!body.count) {
        result.textContent = '✓ 识别完成：这个目录里没有旧版书籍（书籍目录需含 book.json）。';
        document.getElementById('biyu-legacy-commit').disabled = true;
        return;
      }
      result.innerHTML = '<div style="color:var(--ok);font-weight:600;margin-bottom:6px">✓ 已识别 ' + body.count + ' 本旧版作品：</div>' +
        body.books.map((b) =>
          '<label style="display:flex;gap:8px;align-items:center;font-size:13px;padding:2px 0">' +
          '<input type="checkbox" class="biyu-legacy-pick" value="' + b.id + '" checked>' +
          '<span><strong>' + b.title + '</strong>（' + b.chapter_count + ' 章）</span></label>').join('');
      document.getElementById('biyu-legacy-commit').disabled = false;
    } catch (exc) {
      result.textContent = '✗ ' + (exc.message || exc);
      document.getElementById('biyu-legacy-commit').disabled = true;
    }
  }

  async function legacyCommit() {
    const picks = [...document.querySelectorAll('.biyu-legacy-pick:checked')].map((el) => el.value);
    if (!picks.length) return;
    const button = document.getElementById('biyu-legacy-commit');
    button.disabled = true;
    button.textContent = '迁移中…';
    try {
      const resp = await fetch('/api/migrate/legacy/commit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_root: document.getElementById('biyu-legacy-root').value.trim(),
          ids: picks,
        }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.detail || '迁移失败');
      document.getElementById('biyu-import-overlay').hidden = true;
      showToast('已迁移 ' + body.imported.length + ' 本到书架：' +
        body.imported.map((b) => '《' + b.title + '》').join('、'));
      if (location.pathname === '/index.html' || location.pathname === '/') {
        setTimeout(() => location.reload(), 900);
      }
    } catch (exc) {
      document.getElementById('biyu-legacy-result').textContent = '✗ ' + (exc.message || exc);
    } finally {
      button.disabled = false;
      button.textContent = '迁移所选到书架';
    }
  }

  /* ---------- S-3 决策6A:联系与反馈弹窗(图纸 openContactFeedbackModal 搬运) ---------- */

  // S-7d:诊断包导出的公共逻辑——页脚弹窗、工作台失败卡、快检台失败条共用这一份,不复制粘贴
  async function exportDiagnostics(btn, statusEl) {
    const label = btn.textContent;
    const say = (msg) => { if (statusEl) statusEl.textContent = msg; };
    btn.disabled = true;
    if (statusEl) say('正在生成…'); else btn.textContent = '正在生成…';
    try {
      const resp = await fetch('/api/diagnostics/export', { method: 'POST' });
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok || !body.ok) throw new Error(body.detail || '生成失败');
      if (statusEl) {
        say('已生成：' + body.path + '。请把这个文件发到 Q 群 892467108。');
      } else {
        btn.textContent = '已生成 ✓ 发 Q 群 892467108';
        setTimeout(() => { btn.textContent = label; }, 2600);
      }
      const a = document.createElement('a'); a.href = body.download; a.download = body.name; document.body.appendChild(a); a.click(); a.remove();
    } catch (error) {
      if (statusEl) say('诊断包生成失败：' + error.message);
      else { btn.textContent = '生成失败，点此重试'; setTimeout(() => { btn.textContent = label; }, 2600); }
    } finally { btn.disabled = false; }
  }

  function mountDiagnosticsLink(container) {
    if (!container || container.querySelector('.diag-export-link')) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'diag-export-link';
    btn.textContent = '导出诊断包';
    const status = document.createElement('span');
    status.className = 'diag-export-status';
    container.appendChild(btn);
    container.appendChild(status);
    btn.addEventListener('click', () => { exportDiagnostics(btn, status); });
  }

  function openContactFeedback() {
    let overlay = document.getElementById('biyu-contact-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.className = 'biyu-modal-overlay';
      overlay.id = 'biyu-contact-overlay';
      overlay.innerHTML =
        '<div class="biyu-modal" role="dialog" aria-modal="true" aria-labelledby="biyu-contact-title">' +
        '<h2 id="biyu-contact-title">' + shellIcon('chat') + ' 笔驭 (biyu) 作者交流群与问题反馈</h2>' +
        '<div class="card" style="background:var(--surface-subtle);margin-bottom:14px">' +
        '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:8px">' +
        '<div><div style="font-size:15px;font-weight:600">官方内测作者交流 QQ 群：<code style="color:var(--mark);font-size:15px">892467108</code></div>' +
        '<div style="font-size:12.5px;color:var(--ink-mute)">群里交流用法、反馈问题，开发者会在群里答疑；使用资料会陆续在群里分享</div></div>' +
        '<button type="button" class="b2 bs" id="biyu-contact-copy">复制群号</button></div>' +
        '<div style="font-size:12px;color:var(--ink-soft);border-top:1px solid var(--rule);padding-top:8px">' +
        '· 反馈邮箱：<code>749814935@qq.com</code>；遇到报错可以先「导出诊断包」，连同问题描述一起发到群里或邮箱</div></div>' +
        '<p class="eyebrow" style="margin-bottom:6px">快速提交问题或建议</p>' +
        '<textarea class="biyu-contact-textarea" id="biyu-contact-text" rows="3" placeholder="写下你遇到的问题或功能建议…"></textarea>' +
        '<p class="eyebrow" style="margin:12px 0 6px">遇到报错？</p>' +
        '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">' +
        '<button type="button" class="b2 bs" id="biyu-diag-export">导出诊断包</button>' +
        '<span id="biyu-diag-status" style="font-size:12px;color:var(--ink-soft)">只含版本、花费和运行日志，不含 Key 和书稿正文</span></div>' +
        '<div class="biyu-modal-actions">' +
        '<button type="button" class="b3" id="biyu-contact-close">关闭</button>' +
        '<button type="button" class="b1" id="biyu-contact-send">提交反馈</button></div>' +
        '</div>';
      document.body.appendChild(overlay);
      overlay.addEventListener('click', (event) => {
        if (event.target === overlay) overlay.hidden = true;
      });
      document.getElementById('biyu-contact-close').addEventListener('click', () => { overlay.hidden = true; });
      document.getElementById('biyu-diag-export').addEventListener('click', (event) => {
        exportDiagnostics(event.target, document.getElementById('biyu-diag-status'));
      });
      document.getElementById('biyu-contact-copy').addEventListener('click', (event) => {
        if (navigator.clipboard) navigator.clipboard.writeText('892467108');
        event.target.textContent = '已复制 ✓';
        setTimeout(() => { event.target.textContent = '复制群号'; }, 1500);
      });
      document.getElementById('biyu-contact-send').addEventListener('click', () => {
        const text = document.getElementById('biyu-contact-text').value.trim();
        // S-7：反馈邮箱还没开通，先复制文字，请作者发到 Q 群
        const btn = document.getElementById('biyu-contact-send');
        if (navigator.clipboard && text) navigator.clipboard.writeText(text);
        btn.textContent = text ? '已复制，请发到 Q 群 892467108' : '先写几句再提交';
        setTimeout(() => { btn.textContent = '提交反馈'; }, 2500);
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

    // S-3 T5:工作台①设定步以 iframe 内嵌 settings 页(?embed=1)——
    // 嵌入态只保留主题令牌管线,不注入标题栏/状态栏/抽屉,避免双层壳。
    if (new URLSearchParams(location.search).get('embed') === '1') {
      document.body.classList.add('biyu-embedded');
      return;
    }

    const wallpaper = document.createElement('div');
    wallpaper.className = 'biyu-shell-bg-wallpaper';
    wallpaper.setAttribute('aria-hidden', 'true');
    const overlay = document.createElement('div');
    overlay.className = 'biyu-shell-bg-overlay';
    overlay.setAttribute('aria-hidden', 'true');
    document.body.insertBefore(overlay, document.body.firstChild);
    document.body.insertBefore(wallpaper, overlay);
    // S-10 3a-2：壳注入即声明当前背景类型（默认无壁纸→渐变）；偏好返回后 applyBackgroundTokens 修正
    document.documentElement.dataset.bg = state.background.type;

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
    wireImportTriggers();
    if (!oldNav) {
      console.warn('[biyu-shell] 本页没有旧导航容器，已按无壳降级处理：仅注入新壳。');
    }
  }

  // S-7f：缓存最终主题令牌，<head> 里的回放脚本据此在首帧就上色，不再先白后变
  const THEME_CACHE_KEY = 'biyu-theme-css';
  function cacheThemeTokens() {
    try { localStorage.setItem(THEME_CACHE_KEY, document.documentElement.style.cssText); } catch (_) { /* 隐私模式等 */ }
  }
  function hasCachedTheme() {
    try { return !!localStorage.getItem(THEME_CACHE_KEY); } catch (_) { return false; }
  }

  function boot() {
    mountShell();
    if (!hasCachedTheme()) {
      applyThemeTokens(state.themeKey);
      applyBackgroundTokens();
    }
    loadContext()
      .then(loadPrefs)
      .then(() => {
        refreshTitlebarNav();
        applyThemeTokens(state.themeKey);
        applyCustomColors();
        applyBackgroundTokens();
        syncThemeInputs();
        syncBackgroundInputs();
        cacheThemeTokens();
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
    WALLPAPER_PRESETS: WALLPAPER_PRESETS,
    exportDiagnostics: exportDiagnostics,
    mountDiagnosticsLink: mountDiagnosticsLink
  };
})();
