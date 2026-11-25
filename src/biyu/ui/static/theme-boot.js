/* S-7f 主题首帧回放：在 <head> 里同步执行，先把上次的主题令牌写回 :root，避免先白后变。
   令牌由 shell.js 的 cacheThemeTokens() 写入 localStorage。
   S-10 3a修正·工单第8条：localStorage 没有缓存时（冷启动/全新浏览器档案），退回
   服务端随 HTML 内联的 window.__BIYU_THEME_BOOT__（app.py render_static_html 注入），
   保证首帧就是用户的主题（含玻璃令牌与背景）。 */
try {
  var c = window.localStorage.getItem('biyu-theme-css') || window.__BIYU_THEME_BOOT__;
  if (c) document.documentElement.style.cssText = c;
  var k = window.localStorage.getItem('biyu-theme-key');
  if (k) document.documentElement.dataset.theme = (k === 'dark') ? 'dark' : 'light';
} catch (e) { /* ignore */ }
