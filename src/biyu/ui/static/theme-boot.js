/* S-7f 主题首帧回放：在 <head> 里同步执行，先把上次的主题令牌写回 :root，避免先白后变。
   令牌由 shell.js 的 cacheThemeTokens() 写入。 */
try { var c = window.localStorage.getItem('biyu-theme-css'); if (c) document.documentElement.style.cssText = c; } catch (e) { /* ignore */ }
