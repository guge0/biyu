/* mini-md.js — 极简 markdown 渲染(P8-M3R R5 T5.1 抽公共)。
 *
 * 来源:prompts.js(更全版,含代码块 + 表格)+ propose.js 同源。
 * 设计:严格"先 esc 后 md"防 XSS;只支持 LLM 输出常见语法(标题/列表/引用/代码块/表格/加粗/行内码/水平线)。
 *
 * 用法:
 *   <script src="/mini-md.js"></script>
 *   element.innerHTML = window.MiniMd.render(markdownString);
 *   element.textContent = window.MiniMd.esc(unsafeString);  // 仅需转义时
 *
 * 不依赖任何外部库;不修改全局除 window.MiniMd 外的任何变量(IIFE)。
 */
(function () {
  "use strict";

  function esc(s) {
    if (s === null || s === undefined) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function inline(s) {
    // **bold** 和 `code`(注意:esc 后做替换,因此 < > " 已转义,正则只匹配字面量)
    return esc(s)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  function render(md) {
    if (!md) return "";
    var lines = String(md).split("\n");
    var html = "";
    var inList = false;
    var inTable = false;
    var tableRows = [];
    var inQuote = false;
    var inCode = false;

    function closeList() { if (inList) { html += "</ul>"; inList = false; } }
    function closeQuote() { if (inQuote) { html += "</blockquote>"; inQuote = false; } }
    function closeTable() {
      if (inTable) {
        html += "<table>" + tableRows.join("") + "</table>";
        inTable = false;
        tableRows = [];
      }
    }
    function flushAll() { closeList(); closeQuote(); closeTable(); }

    lines.forEach(function (raw) {
      var line = raw.replace(/\s+$/, "");  // trimEnd 兼容(避免 prototype pollution 风险)
      // ``` 代码块开闭
      if (line.indexOf("```") === 0) {
        if (inCode) { html += "</pre>"; inCode = false; }
        else { flushAll(); html += "<pre>"; inCode = true; }
        return;
      }
      if (inCode) { html += esc(line) + "\n"; return; }
      if (!line.trim()) { flushAll(); return; }

      // 表格:| ... | ... |
      if (/^\|.*\|$/.test(line)) {
        closeList(); closeQuote();
        // 分割行 | --- | --- | 跳过
        if (/^\|[\s\-:|]+\|$/.test(line)) return;
        var cells = line.slice(1, -1).split("|").map(function (c) { return c.trim(); });
        if (!inTable) { inTable = true; tableRows = []; }
        var tag = (tableRows.length === 0) ? "th" : "td";
        var row = "<tr>" + cells.map(function (c) { return "<" + tag + ">" + inline(c) + "</" + tag + ">"; }).join("") + "</tr>";
        tableRows.push(row);
        return;
      }
      closeTable();

      if (line.indexOf("### ") === 0) {
        closeList(); closeQuote();
        html += "<h3>" + inline(line.slice(4)) + "</h3>";
      } else if (line.indexOf("## ") === 0) {
        closeList(); closeQuote();
        html += "<h3>" + inline(line.slice(3)) + "</h3>";
      } else if (line.indexOf("# ") === 0) {
        closeList(); closeQuote();
        html += "<h3>" + inline(line.slice(2)) + "</h3>";
      } else if (line.indexOf("> ") === 0) {
        closeList();
        if (!inQuote) { html += "<blockquote>"; inQuote = true; }
        html += inline(line.slice(2)) + " ";
      } else if (line.indexOf("- ") === 0 || line.indexOf("* ") === 0) {
        closeQuote();
        if (!inList) { html += "<ul>"; inList = true; }
        html += "<li>" + inline(line.slice(2)) + "</li>";
      } else if (line === "---") {
        flushAll();
        html += "<hr>";
      } else {
        closeList(); closeQuote();
        html += "<p>" + inline(line) + "</p>";
      }
    });
    if (inCode) html += "</pre>";
    flushAll();
    return html;
  }

  // 暴露到全局(仅此一个命名空间)
  window.MiniMd = { render: render, esc: esc, inline: inline };
})();
