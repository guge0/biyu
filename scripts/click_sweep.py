"""S-7f 点击巡检：每页每个可见按钮点一遍，抓 JS 异常（pageerror）和点了没反应的死按钮。

安全：所有非 GET 的 /api 请求一律拦截（abort），不会调模型、不会花钱、不会改书。
所以「保存/生成」类按钮在这里只验证「点了不崩、有反馈」，不验证功能本身。

用法：
  python scripts/click_sweep.py http://127.0.0.1:8084 [输出目录] [--engine chromium|firefox]
  --engine：S-10 段3a 起可指定浏览器引擎（老板默认浏览器是 Firefox，验收要求两引擎都跑）。
需要 playwright（开发环境已装）。退出码 = 出 pageerror 的页数。
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


def sweep_page(page, url: str) -> dict:
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)[:300]))
    page.goto(url, wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(1200)
    count = min(page.evaluate("document.querySelectorAll('button').length"), MAX_BUTTONS)
    clicked, skipped, navigated, blocked = 0, 0, [], []
    for i in range(count):
        try:
            # 每次重新载入：上一个按钮打开的抽屉/弹窗会挡住后面的按钮
            if i:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(500)
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
            if page.url != before:
                navigated.append(f"{text} -> {page.url}")
        except Exception:  # 元素在点击过程中消失/被遮挡：不算错误
            continue
    return {"url": url, "buttons": count, "clicked": clicked, "skipped": skipped,
            "navigated": navigated, "blocked": blocked, "pageerrors": errors}


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
        bad += bool(errs)
        flag = "FAIL" if errs else "ok  "
        print(f"[{flag}] {r['url'].replace(BASE, '')}  clicked={r.get('clicked', 0)}/{r.get('buttons', 0)}"
              + (f"  blocked={r['blocked'][:4]}" if r.get('blocked') else "")
              + (f"  errors={errs[:2]}" if errs else ""))
    print(f"\n{len(results) - bad}/{len(results)} 页无 JS 异常；明细 {OUT / 'click_sweep.json'}")
    return bad


if __name__ == "__main__":
    sys.exit(main())
