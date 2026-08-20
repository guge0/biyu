/* genre.js — R5 T5.5 题材代号 → 中文标签映射 + chip HTML。
 *
 * 用法:
 *   <script src="/genre.js"></script>
 *   el.innerHTML = window.genreChipHtml("xuanhuan");
 *   // → '<span class="genre-chip genre-chip-xuanhuan">玄幻</span>'
 *
 *   var label = window.genreLabel("dushi");  // "都市"
 *   var label2 = window.genreLabel("未知代号");  // "未知题材"
 */
(function () {
  "use strict";

  var GENRE_MAP = {
    xuanhuan: "玄幻",
    qihuan: "奇幻",
    dushi: "都市",
    xianxia: "仙侠",
    kehuan: "科幻",
    lishi: "历史",
    xuanyi: "悬疑",
    qingxiaoshuo: "轻小说",
    // 兼容其他可能出现的代号
    yanqing: "言情",
    wuxia: "武侠",
    junshi: "军事",
    youxi: "游戏",
    jingji: "竞技",
    lingyizhentan: "灵异侦探",
    tongren: "同人",
    erciyuan: "二次元",
    historical: "历史",
    scifi: "科幻",
    fantasy: "玄幻",
    urban: "都市"
  };

  function genreLabel(code) {
    if (!code) return "";
    var key = String(code).toLowerCase().trim();
    return GENRE_MAP[key] || "未知题材";
  }

  function genreChipHtml(code) {
    var label = genreLabel(code);
    if (!label) return "";
    var key = String(code || "").toLowerCase().trim();
    // 未知代号不挂特定颜色 class,统一灰
    var cls = GENRE_MAP[key] ? "genre-chip genre-chip-" + key : "genre-chip genre-chip-unknown";
    // escape label(防 XSS,label 来自我们自己的 map 不太可能含特殊字符,但 code 未知)
    var safe = String(label).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
    return '<span class="' + cls + '">' + safe + '</span>';
  }

  window.genreLabel = genreLabel;
  window.genreChipHtml = genreChipHtml;
})();
