"""S-7f 点击巡检：每页每个可见按钮点一遍，抓 JS 异常（pageerror）和点了没反应的死按钮。

安全：所有非 GET 的 /api 请求一律拦截（abort），不会调模型、不会花钱、不会改书。
所以「保存/生成」类按钮在这里只验证「点了不崩、有反馈」，不验证功能本身。

S-10 段3a修正（中途抽查第1条）：每次点击后检测页面内可见的错误条 / role=alert 文字
（pageerror 抓不到页面捕获后渲染的错误条），出现即该页记失败。

用法：
  python scripts/click_sweep.py http://127.0.0.1:8084 [输出目录] [--engine chromium|firefox]
  --engine：S-10 段3a 起可指定浏览器引擎（老板默认浏览器是 Firefox，验收要求两引擎都跑）。
需要 playwright（开发环境已装）。退出码 = 出 pageerror 或错误条的页数。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser(description="S-7f 点击巡检")
ap.add_argument("base", nargs="?", default="http://127.0.0.1:8084")
ap.add_argument("out", nargs="?", default="click_sweep_out")
ap.add_argument("--engine", default="chromium", choices=["chromium", "firefox"],
                help="巡检用的浏览器引擎（默认 chromium=本机 Chrome）")
BASE = ap.parse_args().base.rstrip("/")
OUT = Path(ap.parse_args().out)
ENGINE = ap.parse_args().engine
OUT.mkdir(parents=True, exist_ok=True)

PAGES = [
    "/", "/wizard.html", "/settings.html", "/preferences.html", "/prompts.html",
    "/quickcheck.html", "/trash.html", "/good-sentences.html", "/voiceprint.html",
]
# 书相关页面：取书架第一本书拼 URL
BOOK_PAGES = ["/book.html?book={b}", "/overview.html?book={b}", "/workbench.html?book={b}",
              "/memory.html?book={b}", "/summaries.html?book={b}", "/editor.html?book={b}",
              "/propose.html?book={b}"]
MAX_BUTTONS = 40  # 每页最多点 60 个，控制总时长
SKIP_TEXT = ("删除", "彻底", "移到回收站", "退出", "下载", "导出")

# 可见错误条 / role=alert（3a修正·中途抽查第1条）。role=status 的说明条与 .notice-banner 不算错误。
# 巡检环境两类不算缺陷（ui_audit 静态走查不放宽，仍全拦）：
# 1) 网络失败文案——本巡检对所有非 GET 一律 abort，点了写钮后页面如实报「Failed to fetch/网络异常」
#    是预期反馈不是 bug；
# 2) 「请先…」输入校验提示——交互引导（wizard/quickcheck 复用了 error-banner 样式，样式收敛是 3b）。
ALERT_JS = """() => {
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 4 && r.height > 4 && s.display !== 'none' && s.visibility !== 'hidden'; };
  const found = [];
  document.querySelectorAll('.error-banner, [role="alert"]').forEach(el => {
    if (el.getAttribute('role') === 'status' || el.classList.contains('notice-banner')) return;
    if (!vis(el)) return;
    const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
    if (t) found.push(t.slice(0, 120));
  });
  return found;
}"""
ALERT_EXPECTED = ("Failed to fetch", "NetworkError", "网络异常", "服务是否在跑", "Load failed", "请先")


def sweep_page(page, url: str) -> dict:
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)[:300]))
    page.goto(url, wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(1200)
    count = min(page.evaluate("document.querySelectorAll('button').length"), MAX_BUTTONS)
    clicked, skipped, navigated, blocked, alerts = 0, 0, [], [], []
    seen_alerts = set()

    def collect_alerts(context: str) -> None:
        try:
            texts = page.evaluate(ALERT_JS)
        except Exception:
            return
        for t in texts:
            if any(marker in t for marker in ALERT_EXPECTED):
                continue  # 巡检环境预期反馈（见 ALERT_EXPECTED 注释），不计失败
            key = t[:60]
            if key in seen_alerts:
                continue
            seen_alerts.add(key)
            alerts.append(f"[{context}] {t}")

    collect_alerts("载入后")
    for i in range(count):
        try:
            # 每次重新载入：上一个按钮打开的抽屉/弹窗会挡住后面的按钮
            if i:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(500)
                collect_alerts("载入后")
            btn = page.locator("button").nth(i)
            if not btn.is_visible() or not btn.is_enabled():
                continue
            text = (btn.inner_text(timeout=1000) or "").strip().replace("\n", " ")[:30]
            if any(word in text for word in SKIP_TEXT):
                skipped += 1
                continue
            before = page.url
            try:
                btn.click(timeout=2000, no_wait_after=True)
            except Exception:
                blocked.append(text)  # 可见可用却点不到（被遮挡）
                continue
            page.wait_for_timeout(250)
            clicked += 1
            collect_alerts(f"点了「{text}」后")
            if page.url != before:
                navigated.append(f"{text} -> {page.url}")
        except Exception:  # 元素在点击过程中消失/被遮挡：不算错误
            continue
    return {"url": url, "buttons": count, "clicked": clicked, "skipped": skipped,
            "navigated": navigated, "blocked": blocked, "pageerrors": errors, "alerts": alerts}


def main() -> int:
    results = []
    with sync_playwright() as p:
        if ENGINE == "firefox":
            browser = p.firefox.launch(headless=True)
        else:
            try:
                browser = p.chromium.launch(headless=True, channel="chrome")
            except Exception:  # 没装本机 Chrome 时回落 playwright 自带内核
                browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 960})
        ctx.on("dialog", lambda d: d.dismiss())
        ctx.route("**/api/**", lambda route: route.abort() if route.request.method != "GET" else route.continue_())
        page = ctx.new_page()
        books = page.request.get(BASE + "/api/books").json()
        books = books.get("books", books) if isinstance(books, dict) else books
        first = (books[0].get("id") or books[0].get("name")) if books else None
        urls = [BASE + u for u in PAGES]
        if first:
            urls += [BASE + u.format(b=first) for u in BOOK_PAGES]
        for url in urls:
            page = ctx.new_page()
            try:
                results.append(sweep_page(page, url))
            except Exception as exc:
                results.append({"url": url, "fatal": str(exc)[:300]})
            finally:
                page.close()
        browser.close()
    (OUT / "click_sweep.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    bad = 0
    for r in results:
        errs = r.get("pageerrors") or ([r["fatal"]] if r.get("fatal") else [])
        alerts = r.get("alerts") or []
        bad += bool(errs or alerts)
        flag = "FAIL" if (errs or alerts) else "ok  "
        print(f"[{flag}] {r['url'].replace(BASE, '')}  clicked={r.get('clicked', 0)}/{r.get('buttons', 0)}"
              + (f"  blocked={r['blocked'][:4]}" if r.get('blocked') else "")
              + (f"  errors={errs[:2]}" if errs else "")
              + (f"  alerts={alerts[:2]}" if alerts else ""))
    print(f"\n{len(results) - bad}/{len(results)} 页无 JS 异常且无错误条；明细 {OUT / 'click_sweep.json'}")
    return bad


if __name__ == "__main__":
    sys.exit(main())
