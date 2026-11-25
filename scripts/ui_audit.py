"""S-10 段1 全页面 UI 走查：截图 + 自动检测显示问题。

矩阵：16 个静态页 × 视口 1366×768 / 1920×1080 / 2560×1440 × deviceScaleFactor 1 / 1.25 / 1.5
     × 主题 default / dark（经拦截 GET /api/ui/prefs 注入，不写服务端）。
自动检测：横向溢出、关键导航元素重叠、文字溢出容器、>96px 图标、未加样式裸元素、JS 异常。

安全：所有非 GET 的 /api 请求一律拦截（同 click_sweep.py），不触发模型调用、不写书。
用法：
  python scripts/ui_audit.py [base_url] [截图输出目录]
输出：<截图目录>/ui_audit.json + 走查清单.md；退出码 = P0 问题总数（封顶 125）。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090").rstrip("/")
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(r"E:\webnovel\_biyu交付记录\2026-11-25\S-10\截图")
OUT.mkdir(parents=True, exist_ok=True)

BOOK = "siwanghuisu"  # 标准测试书（死亡回归），ch1 有 11 个版本
VIEWPORTS = [(1366, 768), (1920, 1080), (2560, 1440)]
SCALES = [(1, "100"), (1.25, "125"), (1.5, "150")]
THEMES = ["default", "dark"]
# 书相关页带 ?book=；good-sentences / voiceprint / settings 也读 book 参数
BOOK_PAGES = {"book.html", "overview.html", "workbench.html", "memory.html", "summaries.html",
              "editor.html", "propose.html", "voiceprint.html", "good-sentences.html", "settings.html"}

# 检测脚本（在页面内执行）。返回原始发现，严重度分级在 Python 侧统一做。
DETECT_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 4 && r.height > 4 && s.display !== 'none' && s.visibility !== 'hidden'; };
  const name = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
    (el.classList.length ? '.' + String(el.classList[0]) : '');
  const out = { overflowX: 0, navOverlaps: [], textOverflows: [], bigIcons: [], naked: [], nakedLinks: 0 };

  // 1) 横向溢出
  const de = document.documentElement, bd = document.body;
  out.overflowX = Math.max(de.scrollWidth - de.clientWidth, bd ? bd.scrollWidth - bd.clientWidth : 0);

  // 2) 关键导航元素重叠（工单点名的三层：全局标题栏 / 回书·章节浮条 / 阶段条 / 顶栏按钮组）
  const NAV_SEL = ['.biyu-titlebar', '.biyu-win-left', '.biyu-win-right', 'nav.top-nav',
    '.workbench-header', '.workbench-chapter-nav', '.stage-bar', 'header .toolbar',
    'header nav', 'nav', '.top-bar', '.breadcrumb'].join(', ');
  const navs = [...document.querySelectorAll(NAV_SEL)].filter(vis)
    .filter(el => el.getBoundingClientRect().height < 220); // 导航条不会高过一屏三分之一
  for (let i = 0; i < navs.length; i++) for (let j = i + 1; j < navs.length; j++) {
    const a = navs[i], b = navs[j];
    if (a.contains(b) || b.contains(a)) continue;
    const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
    const ox = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
    const oy = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
    if (ox > 12 && oy > 12) out.navOverlaps.push({ a: name(a), b: name(b),
      overlap: [Math.round(ox), Math.round(oy)], where: [Math.round(Math.max(ra.left, rb.left)), Math.round(Math.max(ra.top, rb.top))] });
  }

  // 3) 文字/内容溢出容器（只报前 10 个最大的；滚动容器的溢出是设计，不计）
  const all = [...document.querySelectorAll('body *')].slice(0, 6000);
  for (const el of all) {
    if (!vis(el)) continue;
    const dx = el.scrollWidth - el.clientWidth, dy = el.scrollHeight - el.clientHeight;
    const s = getComputedStyle(el);
    const scrollable = axis => ['auto', 'scroll', 'overlay'].includes(axis);
    if ((dx > 0 && scrollable(s.overflowX)) || (dy > 0 && scrollable(s.overflowY))) continue;
    const d = Math.max(dx, dy);
    if (d <= 6) continue;
    if (el.children.length && !el.innerText.trim()) continue; // 纯容器撑开不算文字溢出
    out.textOverflows.push({ el: name(el), dx, dy, clip: s.overflowX !== 'visible' || s.overflowY !== 'visible',
      text: (el.innerText || '').replace(/\s+/g, ' ').slice(0, 40) });
  }
  out.textOverflows.sort((x, y) => Math.max(y.dx, y.dy) - Math.max(x.dx, x.dy));
  out.textOverflows = out.textOverflows.slice(0, 10);

  // 4) 卡片内过大图标（>96px 的 svg/img）
  for (const el of [...document.querySelectorAll('svg, img')]) {
    if (!vis(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width > 96 || r.height > 96) out.bigIcons.push({ el: name(el),
      w: Math.round(r.width), h: Math.round(r.height), src: (el.getAttribute('src') || '').slice(0, 60) });
  }

  // 5) 未加样式的裸元素（UA 默认样式特征）
  for (const el of [...document.querySelectorAll('a, button, select, input, textarea')]) {
    if (!vis(el)) continue;
    const s = getComputedStyle(el);
    if (el.tagName === 'A') {
      if (s.color === 'rgb(0, 0, 238)') { out.nakedLinks++; if (out.naked.length < 12)
        out.naked.push({ el: name(el), kind: '默认蓝紫链接', text: (el.innerText || '').slice(0, 24) }); }
    } else if (s.backgroundColor === 'rgb(240, 240, 240)' && /Arial/.test(s.fontFamily)) {
      if (out.naked.length < 12) out.naked.push({ el: name(el), kind: '默认系统按钮',
        text: (el.innerText || el.value || el.getAttribute('aria-label') || '').slice(0, 24) });
    }
  }
  return out;
}
"""


def combo_label(page_file: str, vw: int, vh: int, dsf: float, theme: str) -> str:
    return f"{page_file.removesuffix('.html')}_{vw}x{vh}_z{int(dsf * 100)}_{theme}"


def audit_page(ctx, url: str, page_file: str, vw: int, vh: int, dsf: float, theme: str) -> dict:
    label = combo_label(page_file, vw, vh, dsf, theme)
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)[:200]))
    try:
        page.goto(url, wait_until="load", timeout=25000)
        page.wait_for_timeout(1800 if "book=" in url else 1200)
        found = page.evaluate(DETECT_JS)
        shot = OUT / f"{label}.jpg"
        page.screenshot(path=str(shot), type="jpeg", quality=80)
        found.update(url=url, shot=str(shot), pageerrors=errors)
        return found
    except Exception as exc:
        return {"url": url, "shot": str(OUT / f"{label}.jpg"), "fatal": str(exc)[:200], "pageerrors": errors,
                "overflowX": 0, "navOverlaps": [], "textOverflows": [], "bigIcons": [], "naked": [], "nakedLinks": 0}
    finally:
        page.close()


def severity(page_file: str, finding: dict) -> str:
    """P0=影响可用性/就是老板截图里那类问题；P1=明显碍眼或伤交互；P2=小瑕疵。"""
    if finding.get("fatal"):
        return "P0"
    if finding["overflowX"] > 8:
        return "P0"
    if finding["pageerrors"]:
        return "P0"
    if finding["navOverlaps"]:
        return "P0"
    if finding["bigIcons"]:
        return "P1"
    if finding["overflowX"] > 0:
        return "P1"
    if any(t["el"].split(".")[0].lstrip("#") in ("button", "a", "select", "input", "label") or
           t["el"].startswith(("button", "a#", "select", "input")) for t in finding["textOverflows"]):
        return "P1"
    if finding["textOverflows"] or finding["naked"]:
        return "P2"
    return ""


def main() -> int:
    pages = sorted(p.name for p in (Path(__file__).resolve().parent.parent / "src" / "biyu" / "ui" / "static").glob("*.html"))
    print(f"页面 {len(pages)} 个 × 视口 {len(VIEWPORTS)} × 缩放 {len(SCALES)} × 主题 {len(THEMES)}"
          f" = {len(pages) * len(VIEWPORTS) * len(SCALES) * len(THEMES)} 组合；输出 {OUT}")
    results = []
    t0 = time.time()
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True, channel="chrome")
        for page_file in pages:
            url = BASE + "/" + page_file
            if page_file in BOOK_PAGES:
                url += f"?book={BOOK}"
            for vw, vh in VIEWPORTS:
                for dsf, _ in SCALES:
                    for theme in THEMES:
                        # 每组合全新 context：主题经拦截 GET /api/ui/prefs 注入，非 GET 一律拦（不写服务端）
                        ctx = browser.new_context(viewport={"width": vw, "height": vh}, device_scale_factor=dsf)
                        ctx.on("dialog", lambda d: d.dismiss())
                        prefs = {"theme": theme, "custom": None,
                                 "background": {"type": "none", "preset": None, "file": None, "overlay": 90.0, "blur": 0}}

                        def route(rule):
                            req = rule.request
                            if req.method != "GET":
                                return rule.abort()
                            if "/api/ui/prefs" in req.url:
                                return rule.fulfill(status=200, content_type="application/json",
                                                    body=json.dumps(prefs))
                            return rule.continue_()

                        ctx.route("**/api/**", route)
                        r = audit_page(ctx, url, page_file, vw, vh, dsf, theme)
                        r.update(page=page_file, vw=vw, vh=vh, dsf=dsf, theme=theme)
                        results.append(r)
                        ctx.close()
                        sev = severity(page_file, r)
                        print(f"[{sev or 'ok'}] {combo_label(page_file, vw, vh, dsf, theme)}"
                              f" ofX={r['overflowX']} nav={len(r['navOverlaps'])} txt={len(r['textOverflows'])}"
                              f" icon={len(r['bigIcons'])} naked={r['nakedLinks'] + len(r['naked'])}"
                              f" err={len(r['pageerrors'])} ({time.time() - t0:.0f}s)", flush=True)
        browser.close()

    (OUT / "ui_audit.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    p0 = sum(1 for r in results if severity(r["page"], r) == "P0")
    print(f"\n完成 {len(results)} 组合，P0 {p0}；明细 {OUT / 'ui_audit.json'}")
    return min(p0, 125)


if __name__ == "__main__":
    sys.exit(main())
