/* S-1 中文数字工具：留白栏与章号专用（视觉规范第八节 5）。
 * cnNum(n)    普通中文数字：3→三、10→十、12→十二、29→二十九
 * cnChapter(n) 章号专用：30→卅、31→卅一…39→卅九；其余同 cnNum
 */
(function () {
  "use strict";
  const DIGITS = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"];

  function cnNum(n) {
    n = Number(n) || 0;
    if (n <= 0) return "零";
    if (n < 10) return DIGITS[n];
    if (n < 20) return "十" + (n % 10 ? DIGITS[n % 10] : "");
    if (n < 100) {
      const tens = Math.floor(n / 10);
      const ones = n % 10;
      return DIGITS[tens] + "十" + (ones ? DIGITS[ones] : "");
    }
    return String(n);
  }

  function cnChapter(n) {
    n = Number(n) || 0;
    if (n <= 0) return "零";
    if (n >= 30 && n < 40) return "卅" + (n % 10 ? DIGITS[n % 10] : "");
    return cnNum(n);
  }

  window.cnNum = cnNum;
  window.cnChapter = cnChapter;
})();
