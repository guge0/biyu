/* icons.js — R5 T5.7 自建 SVG 图标集(Lucide/Feather 风格 stroke)。
 *
 * 设计:页面加载时注入一个隐藏的 <svg id="biyu-icon-sprite"> 含 <symbol> 定义,
 *       之后通过 <svg class="icon"><use href="#biyu-icon-X"/></use></svg> 引用。
 *       不引外部图标库,统一 stroke 24x24 viewBox。
 *
 * 来源参考:Lucide(ISC License,https://lucide.dev)icon paths。
 *
 * 用法:
 *   <script src="/icons.js"></script>
 *   <svg class="icon"><use href="#biyu-icon-review"/></svg>
 *   或 JS: '<svg class="icon"><use href="#biyu-icon-edit"/></svg>'
 */
(function () {
  "use strict";

  // 8 个入口卡图标(spec R5 T5.7)+ nav 用同套
  // S-10 段3a-2：全站 emoji 图标替换为线条 SVG，新增 12 个（路径照 lucide/样张 sample.js）
  var SYMBOLS = {
    "biyu-icon-shelf": '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',          // 书
    "biyu-icon-propose": '<path d="M9 18h6"/><path d="M10 22h4"/><path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .23 2.23 1.5 3.5A4.61 4.61 0 0 1 8.91 14"/>', // 灯泡
    "biyu-icon-editor": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',         // 对话泡
    "biyu-icon-prompts": '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',          // 代码 < >
    "biyu-icon-review": '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65" transform=""/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/>', // 放大镜+检查
    "biyu-icon-rename": '<path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>', // 铅笔
    "biyu-icon-summary": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="14" y2="17"/>', // 文档
    "biyu-icon-preference": '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',  // 滑块设置
    "biyu-icon-bolt": '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',                                              // ⚡ 快检
    "biyu-icon-import": '<path d="M12 3v12m0 0l-4-4m4 4l4-4"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>', // 📥 导入
    "biyu-icon-chat": '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>', // 💬 反馈群
    "biyu-icon-key": '<path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>', // 🔑 领 Key
    "biyu-icon-spark": '<path d="M12 3l1.9 5.8a2 2 0 0 0 1.3 1.3L21 12l-5.8 1.9a2 2 0 0 0-1.3 1.3L12 21l-1.9-5.8a2 2 0 0 0-1.3-1.3L3 12l5.8-1.9a2 2 0 0 0 1.3-1.3L12 3z"/>', // ✨ 去 AI 味
    "biyu-icon-gacha": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18"/>',              // 抽卡
    "biyu-icon-look": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4l1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>', // 外观
    "biyu-icon-gear": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z"/>', // 设置
    "biyu-icon-clipboard": '<rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>', // 📋 复制
    "biyu-icon-image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/>', // 🖼 海报
    "biyu-icon-award": '<circle cx="12" cy="8" r="6"/><path d="M15.5 13l1.5 8-5-3-5 3 1.5-8"/>'              // 💮 钤印
  };

  function buildSprite() {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("id", "biyu-icon-sprite");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("style", "position:absolute;width:0;height:0;overflow:hidden;");
    var ns = "http://www.w3.org/2000/svg";
    Object.keys(SYMBOLS).forEach(function (id) {
      var sym = document.createElementNS(ns, "symbol");
      sym.setAttribute("id", id);
      sym.setAttribute("viewBox", "0 0 24 24");
      sym.setAttribute("fill", "none");
      sym.setAttribute("stroke", "currentColor");
      sym.setAttribute("stroke-width", "2");
      sym.setAttribute("stroke-linecap", "round");
      sym.setAttribute("stroke-linejoin", "round");
      sym.innerHTML = SYMBOLS[id];
      svg.appendChild(sym);
    });
    document.body.appendChild(svg);
  }

  // 辅助:生成图标 HTML
  // iconHtml('review', 'entry-icon') → '<svg class="icon entry-icon"><use href="#biyu-icon-review"/></svg>'
  function iconHtml(name, extraClass) {
    var cls = "icon" + (extraClass ? " " + extraClass : "");
    return '<svg class="' + cls + '"><use href="#biyu-icon-' + name + '"/></svg>';
  }

  // 自动注入 sprite。S-10 3a-2：改为执行时立即建（本脚本总在 body 末尾，body 已存在），
  // 保证后执行的 deferred shell.js / 其它脚本拿得到 <use> 目标。
  if (document.body) {
    buildSprite();
  } else {
    document.addEventListener("DOMContentLoaded", buildSprite);
  }

  window.BiyuIcons = { iconHtml: iconHtml, buildSprite: buildSprite, NAMES: Object.keys(SYMBOLS).map(function (k) { return k.replace("biyu-icon-", ""); }) };
})();
