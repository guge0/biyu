"""S-10 段3a 全页面 UI 走查（升级版）：截图 + 自动检测显示问题。

矩阵（工单 3a-1）：
- 引擎：chromium(channel="chrome") + firefox（老板默认浏览器是 Firefox）
- 视口用真实 CSS 尺寸，不再用 deviceScaleFactor 模拟缩放：
  1280×665（DPR 2，老板 2560 屏 200% 缩放的真实形态）/ 1536×864 / 1920×1080 / 2560×1440
- 主题：default、dark 跑全部页面；其余 5 套各跑 index/book/workbench 的 1280 一档
- 书：中文 id 测试书「死亡回溯」（数据根副本 BiyuTestRoots/s10_audit_data，服务 8091）；
  workbench 带 &chapter=1（该书内容最全的一章，见交付说明）
自动检测：横向溢出、关键导航元素重叠、文字溢出容器、>96px 图标、未加样式裸元素、
          可见弹窗/抽屉超视口（底边/右边越界）、font-weight>500 文字元素计数(P2)、JS 异常、
          可见错误条 / role=alert 文字（3a修正·中途抽查第1条，P0）、
          可见文字与有效背景的对比度 <4.5（正文）/ <3（≥18px 大字，WCAG AA；3a修正第7条，P1）。
主题注入（3a修正）：不再依赖 shell.js 拉 /api/ui/prefs——那要等 /api/books（走查副本上首拉 2s+），
          截图早于主题应用，矩阵的主题维度会是假的。改为 add_init_script 预写
          localStorage['biyu-theme-css']（与 shell.js cacheThemeTokens 同格式），theme-boot 首帧回放；
          截图前再 wait --paper 等于该主题预设值，主题没落地不算过。

安全：所有非 GET 的 /api 请求一律拦截（同 click_sweep.py），不触发模型调用、不写书。
用法：
  python scripts/ui_audit.py [base_url] [截图输出目录] [--pages a.html,b.html] [--quick]
  --quick：只跑 1280 与 1920 两档、只 default 主题（两引擎都跑），每步快速自检用。
输出：<截图目录>/ui_audit.json；退出码 = P0 问题总数（封顶 125）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8090"
OUT = Path(r"E:\webnovel\_biyu交付记录\2026-11-25\S-10\截图")

BOOK = "死亡回溯"  # 中文 id 测试书（siwanghuisu 的副本），书相关页带 ?book=死亡回溯
WORKBENCH_CHAPTER = 1  # siwanghuisu 只有 ch1 有完整内容（候选稿+正式稿+方案），ch4 不存在
VIEWPORTS = [(1280, 665, 2), (1536, 864, 1), (1920, 1080, 1), (2560, 1440, 1)]
QUICK_VIEWPORTS = [(1280, 665, 2), (1920, 1080, 1)]
THEMES_ALL = ["default", "dark"]
THEMES_EXTRA = ["lingshu", "parchment", "celadon", "stone", "pure"]
THEME_EXTRA_PAGES = {"index.html", "book.html", "workbench.html"}
ENGINES = ("chromium", "firefox")
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
  const de = document.documentElement, bd = document.body;
  const vw = de.clientWidth, vh = de.clientHeight;
  const out = { overflowX: 0, navOverlaps: [], textOverflows: [], bigIcons: [], naked: [], nakedLinks: 0,
    dialogOverflows: [], heavyFontCount: 0, heavyFonts: [] };

  // 1) 横向溢出
  out.overflowX = Math.max(de.scrollWidth - de.clientWidth, bd ? bd.scrollWidth - bd.clientWidth : 0);

  // 2) 关键导航元素重叠（全局栏 / 书内栏 / 阶段条 / 各页自带导航条）
  const NAV_SEL = ['.biyu-titlebar', '.biyu-win-left', '.biyu-win-right', '.biyu-bookbar',
    'nav.top-nav', '.workbench-header', '.workbench-chapter-nav', '.stage-bar', 'header .toolbar',
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
    // 行内元素 clientWidth 恒为 0，量不出溢出；line-clamp 截断在 Firefox 的 scrollHeight 是全文高
    if (s.display === 'inline' || parseInt(s.webkitLineClamp) > 0) continue;
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

  // 6) 可见弹窗/抽屉超视口（工单 3a-1 新增）：底边 ≤ 视口高、右边 ≤ 视口宽。
  //    全屏遮罩层（≈视口大小）不算弹窗本体，量的是它里面那张对话框；
  //    文档流内的元素（position static/relative）随页面滚动，不算浮层。
  const DLG_SEL = '[class*="overlay"],[class*="modal"],[class*="dialog"],[class*="drawer"],[role="dialog"]';
  for (const el of document.querySelectorAll(DLG_SEL)) {
    if (!vis(el)) continue;
    const ps = getComputedStyle(el).position;
    if (ps === 'static' || ps === 'relative') continue;
    const r = el.getBoundingClientRect();
    if (r.width >= vw * 0.98 && r.height >= vh * 0.98) continue; // 全屏遮罩
    const bottomOver = Math.round(r.bottom - vh), rightOver = Math.round(r.right - vw);
    if (bottomOver > 2 || rightOver > 2) out.dialogOverflows.push({ el: name(el),
      bottomOver, rightOver, rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)] });
  }

  // 6b) 可见错误条 / role=alert 文字（3a修正·中途抽查第1条，P0）：
  //     页面内被捕获后渲染出的错误条，pageerror 抓不到。role=status 的提示条（记忆未更新等
  //     一次性说明）不算错误，.notice-banner 同理。
  out.alerts = [];
  for (const el of document.querySelectorAll('.error-banner, [role="alert"]')) {
    if (el.getAttribute('role') === 'status' || el.classList.contains('notice-banner')) continue;
    if (!vis(el)) continue;
    const t = (el.innerText || '').replace(/\s+/g, ' ').trim();
    if (t) out.alerts.push({ el: name(el), text: t.slice(0, 90) });
  }

  // 6c) 对比度（3a修正第7条，P1）：可见文字 vs 有效背景 <4.5（正文）/ <3（≥18px）。
  //     有效背景 = 自身起沿祖先链把半透明底色逐层合成，直到不透明层；带背景图/渐变的元素算不了，跳过。
  const parseC = c => { const m = /rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/.exec(c || '');
    return m ? { r: +m[1], g: +m[2], b: +m[3], a: m[4] === undefined ? 1 : +m[4] } : null; };
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const over = (top, bot) => ({ r: top.r * top.a + bot.r * (1 - top.a),
    g: top.g * top.a + bot.g * (1 - top.a), b: top.b * top.a + bot.b * (1 - top.a), a: 1 });
  const effBg = el => {
    const layers = [];
    let node = el;
    while (node && node.nodeType === 1) {
      const bs = getComputedStyle(node);
      const bi = bs.backgroundImage;
      if (bi && bi !== 'none' && !/^linear-gradient\(rgba\(0, 0, 0, 0\)/.test(bi)) return null; // 图/渐变底，算不了
      const b = parseC(bs.backgroundColor);
      if (b && b.a > 0) { layers.push(b); if (b.a >= 1) break; }
      node = node.parentElement;
    }
    if (!layers.length) return null;
    let bg = layers.pop(); // 最深一层
    while (layers.length) bg = over(layers.pop(), bg);
    return bg;
  };
  out.lowContrast = [];
  const reported = new Set();
  for (const el of all) {
    if (!vis(el)) continue;
    if (!el.childNodes.length || ![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    const s = getComputedStyle(el);
    const fg = parseC(s.color), bg = effBg(el);
    if (!fg || !bg) continue;
    const l1 = lum(fg), l2 = lum(bg);
    const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    const px = parseFloat(s.fontSize), big = px >= 18;
    const floor = big ? 3 : 4.5;
    if (ratio >= floor) continue;
    const key = s.color + '|' + s.fontSize + '|' + (el.innerText || '').trim().slice(0, 12);
    if (reported.has(key)) continue;
    reported.add(key);
    if (out.lowContrast.length < 14) out.lowContrast.push({ el: name(el),
      text: (el.innerText || '').replace(/\s+/g, ' ').slice(0, 24), px, ratio: +ratio.toFixed(2),
      fg: s.color, bg: `rgb(${Math.round(bg.r)},${Math.round(bg.g)},${Math.round(bg.b)})` });
  }
  out.lowContrast.sort((a, b) => a.ratio - b.ratio);

  // 7) 字重 >500 的文字元素计数（工单 3a-1 新增，P2）：字重锁 400/500，只统计带直接文字的元素
  for (const el of document.querySelectorAll('body *')) {
    if (!vis(el)) continue;
    const w = parseFloat(getComputedStyle(el).fontWeight);
    if (!(w > 500)) continue;
    const hasText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!hasText) continue;
    out.heavyFontCount++;
    if (out.heavyFonts.length < 10) out.heavyFonts.push({ el: name(el), w,
      text: (el.textContent || '').trim().slice(0, 20) });
  }
  return out;
}
"""


def parse_args():
    ap = argparse.ArgumentParser(description="S-10 段3a UI 走查")
    ap.add_argument("base", nargs="?", default=BASE, help="服务地址，走查用 8091")
    ap.add_argument("out", nargs="?", default=str(OUT), help="截图输出目录")
    ap.add_argument("--pages", default="", help="只跑这些页（逗号分隔文件名，如 index.html,book.html）")
    ap.add_argument("--quick", action="store_true", help="只跑 1280 与 1920、只 default 主题")
    return ap.parse_args()


def combo_label(page_file: str, vw: int, vh: int, dpr: int, theme: str) -> str:
    return f"{page_file.removesuffix('.html')}_{vw}x{vh}_dpr{dpr}_{theme}"


def page_url(page_file: str) -> str:
    url = f"/{page_file}"
    if page_file in BOOK_PAGES:
        url += f"?book={quote(BOOK)}"
        if page_file == "workbench.html":
            url += f"&chapter={WORKBENCH_CHAPTER}"
    return url


def launch_engine(p, engine: str):
    if engine == "chromium":
        try:
            return p.chromium.launch(headless=True, channel="chrome")
        except Exception:
            return p.chromium.launch(headless=True)
    return p.firefox.launch(headless=True)


def theme_tokens_css(theme: str) -> str:
    """从 shell.js 的 THEME_PRESETS（S1 标记段）拼出与 cacheThemeTokens 同格式的 cssText。

    3a修正（工单第8条）：走查矩阵的主题此前经 /api/ui/prefs 注入，但 shell.js 的 boot 要先等
    /api/books（走查副本上首拉 2s+）才应用主题，截图早于应用——主题维度是假的。
    现改为直接预写 localStorage['biyu-theme-css']，theme-boot 在 <head> 首帧同步回放。
    """
    global _THEME_PRESETS
    if _THEME_PRESETS is None:
        shell = (Path(__file__).resolve().parent.parent / "src" / "biyu" / "ui" / "static" / "shell.js") \
            .read_text(encoding="utf-8")
        m = re.search(r"/\*S1-THEME-BEGIN\*/(.*?)/\*S1-THEME-END\*/", shell, re.S)
        if not m:
            raise RuntimeError("shell.js 里找不到 THEME_PRESETS 标记段")
        _THEME_PRESETS = json.loads(m.group(1))
    preset = _THEME_PRESETS.get(theme) or _THEME_PRESETS["default"]
    css = "".join(f"{k}: {v}; " for k, v in preset.items() if k.startswith("--"))
    # applyBackgroundTokens 的默认背景（无壁纸）：与 shell.js 无壁纸分支一致
    css += "--bg-image: none; --bg-overlay-alpha: 0.90; --bg-blur: 0px;"
    return css


_THEME_PRESETS: dict | None = None


def audit_page(ctx, url: str, label: str, theme_paper: str | None = None) -> dict:
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)[:200]))
    try:
        page.goto(url, wait_until="load", timeout=25000)
        page.wait_for_timeout(1800 if "book=" in url else 1200)
        theme_late = False
        if theme_paper:  # 主题必须真的落到 :root 才算数（不再只信 prefs 注入）
            try:
                page.wait_for_function(
                    "expected => getComputedStyle(document.documentElement).getPropertyValue('--paper').trim() === expected",
                    arg=theme_paper, timeout=6000)
            except Exception:
                theme_late = True
        if "workbench" in url:  # 3a修正：正文没到就截图会拍到 17px 纸面条——等候选稿渲染出来
            try:
                page.wait_for_function(
                    "() => { const el = document.getElementById('chapter-read');"
                    " return el && el.innerText.trim().length > 50; }", timeout=8000)
            except Exception:
                pass
        found = page.evaluate(DETECT_JS)
        shot = OUT / f"{label}.jpg"
        page.screenshot(path=str(shot), type="jpeg", quality=80)
        found.update(url=url, shot=str(shot), pageerrors=errors, theme_late=theme_late)
        return found
    except Exception as exc:
        return {"url": url, "shot": str(OUT / f"{label}.jpg"), "fatal": str(exc)[:200], "pageerrors": errors,
                "overflowX": 0, "navOverlaps": [], "textOverflows": [], "bigIcons": [], "naked": [],
                "nakedLinks": 0, "dialogOverflows": [], "heavyFontCount": 0, "heavyFonts": [],
                "alerts": [], "lowContrast": []}
    finally:
        page.close()


def severity(finding: dict) -> str:
    """P0=影响可用性/就是老板截图里那类问题；P1=明显碍眼或伤交互；P2=小瑕疵。"""
    if finding.get("fatal"):
        return "P0"
    if finding["overflowX"] > 8:
        return "P0"
    if finding["pageerrors"]:
        return "P0"
    if finding["navOverlaps"]:
        return "P0"
    if finding["dialogOverflows"]:
        return "P0"
    if finding.get("alerts"):
        return "P0"  # 3a修正·中途抽查第1条：页面内可见错误条 = P0
    if finding.get("theme_late"):
        return "P0"  # 3a修正第8条：等了 6s 主题还没落到 :root，矩阵主题维度不可信
    if finding.get("lowContrast"):
        return "P1"  # 3a修正第7条：对比度不足 WCAG AA
    if finding["bigIcons"]:
        return "P1"
    if finding["overflowX"] > 0:
        return "P1"
    if any(t["el"].split(".")[0].lstrip("#") in ("button", "a", "select", "input", "label") or
           t["el"].startswith(("button", "a#", "select", "input")) for t in finding["textOverflows"]):
        return "P1"
    if finding["textOverflows"] or finding["naked"] or finding["heavyFontCount"]:
        return "P2"
    return ""


def build_combos(pages: list[str], quick: bool) -> list[dict]:
    combos = []
    viewports = QUICK_VIEWPORTS if quick else VIEWPORTS
    for page_file in pages:
        for engine in ENGINES:
            for vw, vh, dpr in viewports:
                themes = ["default"] if quick else THEMES_ALL
                for theme in themes:
                    combos.append({"page": page_file, "engine": engine, "vw": vw, "vh": vh,
                                   "dpr": dpr, "theme": theme})
            # 其余 5 套主题各跑 index/book/workbench 的 1280 一档（quick 不跑）
            if not quick and page_file in THEME_EXTRA_PAGES:
                for theme in THEMES_EXTRA:
                    combos.append({"page": page_file, "engine": engine, "vw": 1280, "vh": 665,
                                   "dpr": 2, "theme": theme})
    return combos


def main() -> int:
    args = parse_args()
    global BASE, OUT
    BASE = args.base.rstrip("/")
    OUT = Path(args.out)
    OUT.mkdir(parents=True, exist_ok=True)

    static_dir = Path(__file__).resolve().parent.parent / "src" / "biyu" / "ui" / "static"
    pages = sorted(p.name for p in static_dir.glob("*.html"))
    if args.pages:
        wanted = [p.strip() for p in args.pages.split(",") if p.strip()]
        missing = [p for p in wanted if p not in pages]
        if missing:
            print(f"--pages 里有静态目录不存在的页：{missing}"); return 2
        pages = sorted(wanted)

    combos = build_combos(pages, args.quick)
    print(f"页面 {len(pages)} 个 × 引擎 {len(ENGINES)} × 视口 {len(set((c['vw'], c['vh']) for c in combos))}"
          f" × 主题（含 5 套附加主题三页档）= {len(combos)} 组合；输出 {OUT}")
    results = []
    t0 = time.time()
    with sync_playwright() as p:
        browsers = {name: launch_engine(p, name) for name in ENGINES}
        try:
            for c in combos:
                page_file, engine = c["page"], c["engine"]
                vw, vh, dpr, theme = c["vw"], c["vh"], c["dpr"], c["theme"]
                label = combo_label(page_file, vw, vh, dpr, theme)
                if engine != ENGINES[0]:
                    label = f"{engine[:1]}_{label}"
                # 每组合全新 context：主题靠预写 localStorage（theme-boot 首帧回放）+ prefs 注入双保险；
                # 非 GET 一律拦（不写服务端）
                ctx = browsers[engine].new_context(viewport={"width": vw, "height": vh},
                                                   device_scale_factor=dpr)
                ctx.on("dialog", lambda d: d.dismiss())
                prefs = {"theme": theme, "custom": None,
                         "background": {"type": "none", "preset": None, "file": None, "overlay": 90.0, "blur": 0}}
                ctx.add_init_script(
                    "try{localStorage.setItem('biyu-theme-css'," + json.dumps(theme_tokens_css(theme))
                    + ");localStorage.setItem('biyu-theme-key'," + json.dumps(theme) + ")}catch(e){}")

                def route(rule):
                    req = rule.request
                    if req.method != "GET":
                        return rule.abort()
                    if "/api/ui/prefs" in req.url:
                        return rule.fulfill(status=200, content_type="application/json",
                                            body=json.dumps(prefs))
                    return rule.continue_()

                ctx.route("**/api/**", route)
                r = audit_page(ctx, BASE + page_url(page_file), label,
                               theme_paper=(_THEME_PRESETS or {}).get(theme, {}).get("--paper"))
                r.update(page=page_file, engine=engine, vw=vw, vh=vh, dpr=dpr, theme=theme)
                results.append(r)
                ctx.close()
                sev = severity(r)
                print(f"[{sev or 'ok'}] {label}"
                      f" ofX={r['overflowX']} nav={len(r['navOverlaps'])} txt={len(r['textOverflows'])}"
                      f" icon={len(r['bigIcons'])} dlg={len(r['dialogOverflows'])}"
                      f" alert={len(r.get('alerts', []))} contrast={len(r.get('lowContrast', []))}"
                      f" fw500={r['heavyFontCount']} naked={r['nakedLinks'] + len(r['naked'])}"
                      f" err={len(r['pageerrors'])}"
                      f"{' THEME-LATE' if r.get('theme_late') else ''} ({time.time() - t0:.0f}s)", flush=True)
        finally:
            for b in browsers.values():
                b.close()

    (OUT / "ui_audit.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    p0 = sum(1 for r in results if severity(r) == "P0")
    p1 = sum(1 for r in results if severity(r) == "P1")
    print(f"\n完成 {len(results)} 组合，P0 {p0} / P1 {p1}；明细 {OUT / 'ui_audit.json'}")
    return min(p0, 125)


if __name__ == "__main__":
    sys.exit(main())
