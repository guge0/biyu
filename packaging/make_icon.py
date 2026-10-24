"""生成笔驭桌面图标:朱砂印「驭」(packaging/electron/icons/biyu.ico + png)。

只用标准库:Windows GDI(ctypes) 渲染楷体「驭」字 + PNG(zlib/struct) 编码 + ICO 容器。
颜色对齐图纸朱砂方印:#A63424 底 / #F7F1E3 字与内框线(cinnabar-seal-svg 同源)。
用法:.venv\\Scripts\\python.exe packaging\\make_icon.py
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import sys
import zlib
from pathlib import Path

GDI = ctypes.windll.gdi32
USER = ctypes.windll.user32


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]

# COLORREF 布局为 0x00BBGGRR
CINNABAR_REF = 0x24 << 16 | 0x34 << 8 | 0xA6  # #A63424
CREAM_REF = 0xE3 << 16 | 0xF1 << 8 | 0xF7  # #F7F1E3

SIZES = [256, 128, 64, 48, 32, 24, 16]
MASTER = 256


def _write_png(path: Path, width: int, height: int, rgba: bytes) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(
        b"\x00" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height)
    )
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def _render_master(size: int) -> bytes:
    """GDI 渲染朱砂印「驭」,返回自顶向下的 RGBA。"""
    hdc_screen = USER.GetDC(0)
    hdc = GDI.CreateCompatibleDC(hdc_screen)
    bmp = GDI.CreateCompatibleBitmap(hdc_screen, size, size)
    GDI.SelectObject(hdc, bmp)

    # 底:朱砂整面(方印直角;圆角在小尺寸下锯齿明显)
    brush = GDI.CreateSolidBrush(CINNABAR_REF)
    GDI.SelectObject(hdc, brush)
    GDI.PatBlt(hdc, 0, 0, size, size, 0x00F00021)  # PATCOPY
    GDI.DeleteObject(brush)

    # 内框线:奶油色细框,对齐图纸 seal 内圈
    pen = GDI.CreatePen(0, max(3, size // 64), CREAM_REF)
    GDI.SelectObject(hdc, pen)
    GDI.SelectObject(hdc, GDI.GetStockObject(5))  # NULL_BRUSH
    m = max(6, size // 14)
    GDI.Rectangle(hdc, m, m, size - m, size - m)
    GDI.DeleteObject(pen)

    # 字:楷体「驭」,奶油色,居中
    font = GDI.CreateFontW(
        -int(size * 0.62), 0, 0, 0,
        700, 0, 0, 0,
        1,  # DEFAULT_CHARSET
        0, 0, 5,  # PROOF_QUALITY
        0x30,  # GB2312_CHARSET
        "KaiTi",
    )
    old_font = GDI.SelectObject(hdc, font)
    GDI.SetBkMode(hdc, 1)  # TRANSPARENT
    GDI.SetTextColor(hdc, CREAM_REF)
    rect = wt.RECT(0, 0, size, size)
    USER.DrawTextW(hdc, "驭", 1, ctypes.byref(rect), 0x25)  # DT_CENTER|DT_VCENTER|DT_SINGLELINE
    GDI.SelectObject(hdc, old_font)
    GDI.DeleteObject(font)

    # 取回位图(负高=自顶向下 BGRA) → 转 RGBA,统一不透明
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = size
    bmi.biHeight = -size
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0
    buf = ctypes.create_string_buffer(size * size * 4)
    GDI.GetDIBits(hdc, bmp, 0, size, buf, ctypes.byref(bmi), 0)
    GDI.DeleteObject(bmp)
    GDI.DeleteDC(hdc)
    USER.ReleaseDC(0, hdc_screen)

    src = buf.raw
    out = bytearray(size * size * 4)
    for i in range(size * size):
        b, g, r = src[i * 4], src[i * 4 + 1], src[i * 4 + 2]
        out[i * 4] = r
        out[i * 4 + 1] = g
        out[i * 4 + 2] = b
        out[i * 4 + 3] = 0xFF
    return bytes(out)


def _scale(rgba: bytes, src: int, dst: int) -> bytes:
    if src == dst:
        return rgba
    out = bytearray(dst * dst * 4)
    for y in range(dst):
        sy = y * src // dst
        for x in range(dst):
            sx = x * src // dst
            si = (sy * src + sx) * 4
            di = (y * dst + x) * 4
            out[di:di + 4] = rgba[si:si + 4]
    return bytes(out)


def build(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    master = _render_master(MASTER)
    pngs: list[Path] = []
    blobs: list[tuple[int, bytes]] = []
    for s in SIZES:
        png = out_dir / f"biyu-{s}.png"
        _write_png(png, s, s, _scale(master, MASTER, s))
        pngs.append(png)
        blobs.append((s, png.read_bytes()))

    ico = out_dir / "biyu.ico"
    n = len(blobs)
    head = struct.pack("<HHH", 0, 1, n)
    entries = b""
    offset = 6 + 16 * n
    body = b""
    for s, blob in blobs:
        w = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(blob), offset)
        body += blob
        offset += len(blob)
    ico.write_bytes(head + entries + body)
    return [*pngs, ico]


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "electron" / "icons"
    for f in build(target):
        print(f"ok {f} ({f.stat().st_size} bytes)")
