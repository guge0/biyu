"""3b 第0条配套：玻璃「壁纸态」三件验证（壁纸图 / 遮罩 / 模糊照旧生效）。

ui_audit.py 的玻璃断言跑在无壁纸渐变态（走查矩阵 prefs background.type=none）；
工单第0条另要求有壁纸时壁纸、遮罩、模糊照旧生效——本脚本对 4 套主题 ×
宣纸壁纸（overlay 84%、blur 8px）量 computed 值与真实像素，打印结果。
无壁纸渐变态的三条 P0 断言见 ui_audit.py 的 glass 检测。

用法：python scripts/check_glass_wallpaper.py [base_url]（默认走查服务 8091）。"""
import json, re, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8091"
shell = (Path(__file__).resolve().parent.parent / "src" / "biyu" / "ui" / "static" / "shell.js").read_text(encoding="utf-8")
PRESETS = json.loads(re.search(r"/\*S1-THEME-BEGIN\*/(.*?)/\*S1-THEME-END\*/", shell, re.S).group(1))

def decode_png_rgb(png: bytes):
    import struct, zlib
    pos = 8; idat = b""; meta = None
    while pos + 8 <= len(png):
        ln = struct.unpack(">I", png[pos:pos+4])[0]
        typ = png[pos+4:pos+8]; data = png[pos+8:pos+8+ln]
        if typ == b"IHDR": meta = struct.unpack(">IIBBBBB", data[:13])
        elif typ == b"IDAT": idat += data
        elif typ == b"IEND": break
        pos += 12 + ln
    if not meta: return None
    w, h, depth, ctype, _comp, _filt, interlace = meta
    if depth != 8 or interlace != 0 or ctype not in (2, 6): return None
    ch = 3 if ctype == 2 else 4
    raw = zlib.decompress(idat)
    stride = w * ch
    out = bytearray(h * stride)
    prev = bytearray(stride)
    pos = 0
    for row in range(h):
        f = raw[pos]; pos += 1
        line = bytearray(raw[pos:pos+stride]); pos += stride
        if f == 1:
            for i in range(ch, stride): line[i] = (line[i] + line[i-ch]) & 255
        elif f == 2:
            for i in range(stride): line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                left = line[i-ch] if i >= ch else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i-ch] if i >= ch else 0
                b = prev[i]; c = prev[i-ch] if i >= ch else 0
                pp = a + b - c
                pa, pb, pc = abs(pp-a), abs(pp-b), abs(pp-c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        out[row*stride:(row+1)*stride] = line
        prev = line
    px = bytes(out[0:ch])
    return (px[0], px[1], px[2])

def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, channel="chrome")
    for theme in ("default", "dark", "parchment", "celadon"):
        for mode in ("none", "xuan"):
            ctx = b.new_context(viewport={"width": 1280, "height": 665}, device_scale_factor=2)
            css = "".join(f"{k}: {v}; " for k, v in PRESETS[theme].items() if k.startswith("--"))
            css += "--bg-image: none; --bg-overlay-alpha: 0.90; --bg-blur: 0px;"
            ctx.add_init_script("try{localStorage.setItem('biyu-theme-css'," + json.dumps(css) + ")}catch(e){}")
            prefs_cell = {"v": {"theme": theme, "custom": None,
                                "background": {"type": "preset" if mode == "xuan" else "none",
                                               "preset": "xuan" if mode == "xuan" else None,
                                               "file": None, "overlay": 84.0 if mode == "xuan" else 90.0, "blur": 8 if mode == "xuan" else 0}}}

            def route(rule, _req=None):
                req = rule.request
                if req.method != "GET":
                    return rule.abort()
                if "/api/ui/prefs" in req.url:
                    return rule.fulfill(status=200, content_type="application/json", body=json.dumps(prefs_cell["v"]))
                return rule.continue_()

            ctx.route("**/api/**", route)
            page = ctx.new_page()
            page.goto(BASE + "/", wait_until="load", timeout=25000)
            page.wait_for_timeout(2000)
            info = page.evaluate("""() => {
              const wp = document.querySelector('.biyu-shell-bg-wallpaper');
              const tb = document.querySelector('.biyu-titlebar');
              const card = document.querySelector('.card, .book-card');
              return {
                wpBg: wp ? getComputedStyle(wp).backgroundImage.slice(0, 80) : null,
                tbBg: tb ? getComputedStyle(tb).backgroundColor : null,
                tbBf: tb ? getComputedStyle(tb).backdropFilter : null,
                cardBg: card ? getComputedStyle(card).backgroundColor : null,
                cardBf: card ? getComputedStyle(card).backdropFilter : null,
                htmlBg: getComputedStyle(document.documentElement).backgroundColor,
                bodyBg: getComputedStyle(document.body).backgroundColor,
                dataBg: document.documentElement.dataset.bg,
                themeAttr: document.documentElement.dataset.theme,
                wpFilter: wp ? getComputedStyle(wp).filter : null,
                wpOpacity: document.querySelector('.biyu-shell-bg-overlay') ? getComputedStyle(document.querySelector('.biyu-shell-bg-overlay')).opacity : null,
              };
            }""")
            paper = hex_rgb(PRESETS[theme]["--paper"])
            dists = []
            for (x, y) in ((6, 6), (1274, 6), (640, 613)):
                rgb = decode_png_rgb(page.screenshot(clip={"x": x, "y": y, "width": 1, "height": 1}, type="png"))
                if rgb:
                    d = sum((a-b)**2 for a, b in zip(rgb, paper)) ** 0.5
                    dists.append((f"({x},{y})", rgb, round(d, 1)))
            print(f"== {theme}/{mode} theme={info['themeAttr']} dataBg={info['dataBg']} paper={paper}")
            print("  wallpaper:", info["wpBg"])
            print("  html/body bg:", info["htmlBg"], "/", info["bodyBg"])
            print("  titlebar:", info["tbBg"], "bf:", info["tbBf"])
            print("  wallpaper filter:", info.get("wpFilter"), "overlay opacity:", info.get("wpOpacity"))
            print("  card:", info["cardBg"], "bf:", info["cardBf"])
            print("  pixels:", dists, "max:", max((d[2] for d in dists), default=0))
            ctx.close()
    b.close()
