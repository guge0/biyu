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
  var SYMBOLS = {
    "biyu-icon-shelf": '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',          // 书
    "biyu-icon-propose": '<path d="M9 18h6"/><path d="M10 22h4"/><path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .23 2.23 1.5 3.5A4.61 4.61 0 0 1 8.91 14"/>', // 灯泡
    "biyu-icon-editor": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',         // 对话泡
    "biyu-icon-prompts": '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',          // 代码 < >
    "biyu-icon-review": '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65" transform=""/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/>', // 放大镜+检查
    "biyu-icon-rename": '<path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>', // 铅笔
    "biyu-icon-summary": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="14" y2="17"/>', // 文档
    "biyu-icon-preference": '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>'  // 滑块设置
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

  // 自动在 DOMContentLoaded 注入 sprite
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", buildSprite);
  } else {
    buildSprite();
  }

  window.BiyuIcons = { iconHtml: iconHtml, buildSprite: buildSprite, NAMES: Object.keys(SYMBOLS).map(function (k) { return k.replace("biyu-icon-", ""); }) };
})();
