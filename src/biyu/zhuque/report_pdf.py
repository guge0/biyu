"""朱雀网页报告 PDF 解析与窗口映射。

产品化自 _s6_ref/pdf_extract.py(已验证原型,原型用 PyMuPDF;本仓无 PDF 库,
改用纯 Python 的 pypdf,见 pyproject 依赖)。解析逻辑拆成两层:
- extract_pdf_text(bytes): pypdf 抽出整页文本(薄封装,可选依赖)
- parse_fragments(raw) / map_scores_to_windows(...): 对「已抽出的文本行」的纯函数,可离线单测
"""
from __future__ import annotations

import io
import re
from typing import Any

# 报告里的页眉页脚/表头/图例等家具行(照原型 DROP 表,补了无小数位的百分比)
_DROP = [
    r"^\d{4}/\d{1,2}/\d{1,2} \d{1,2}:\d{2}$", r"^朱雀AI生成检测报告单", r"^https://matrix\.tencent",
    r"^\d+/\d+$", r"^第\d+页 共\d+页$", r"^NO\. \d+$", r"^\s*片段\d+ AIGC值", r"^序号$", r"^片段$",
    r"^占全文比例$", r"^占字符数$", r"^AIGC值$", r"^\d+$", r"^片段\d+$",
    r"^\d+\.\d+%$", r"^\d+%$", r"^[01]\.\d{4}$", r"^检测时间", r"^检测结果$", r"^AI分布图$",
    r"^人工特征 \(", r"^疑似AI \(", r"^AI特征 \(", r"^片段解析$", r"^\s*检测片段详情$",
]
_DROP = [re.compile(p) for p in _DROP]
_FRAGMENT_MARK = re.compile(r"片段(\d+) AIGC值 ([01]\.\d{4})")


class ReportPdfError(Exception):
    """报告解析失败,message 面向作者。"""


def extract_pdf_text(data: bytes) -> str:
    """用 pypdf 抽出 PDF 全文(各页文本以换行拼接)。"""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ReportPdfError("解析报告 PDF 需要 pypdf 组件(pip install pypdf)后再试。") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise ReportPdfError(f"这份 PDF 读不出来({type(exc).__name__}),确认导出的是朱雀报告单。") from exc


def _reassemble(lines: list[str]) -> str:
    """把 PDF 抽出的行拼回段落(照原型:短于最长行-3 的行收段)。"""
    lines = [l for l in lines if l.strip() and not any(p.search(l) for p in _DROP)]
    if not lines:
        return ""
    width = max(len(l) for l in lines)
    out: list[str] = []
    buf = ""
    for line in lines:
        buf += line
        if len(line) < width - 3:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return "\n".join(out)


def parse_fragments(raw: str) -> list[dict[str, Any]]:
    """从报告全文抽出片段:[{no, score, text}]。

    「片段N AIGC值 0.xxxx」标记行之间的正文行就是该片段的文本。
    """
    raw_lines = raw.split("\n")
    markers: list[tuple[int, int, float]] = []
    for i, line in enumerate(raw_lines):
        m = _FRAGMENT_MARK.search(line)
        if m:
            markers.append((i, int(m.group(1)), float(m.group(2))))
    fragments: list[dict[str, Any]] = []
    for k, (line_index, no, score) in enumerate(markers):
        end = markers[k + 1][0] if k + 1 < len(markers) else len(raw_lines)
        fragments.append({"no": no, "score": score, "text": _reassemble(raw_lines[line_index + 1:end])})
    return fragments


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text)


def map_scores_to_windows(fragments: list[dict[str, Any]],
                          windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把报告片段分数映射回当前稿的窗口(文本归一化后按顺序匹配)。

    返回与 windows 等长的列表,每项 {score, fragment}:
    - score: 覆盖该窗口的所有片段里最差(最高)的 AIGC 值;映射不上为 None
    - fragment: 覆盖的最后一个片段编号;映射不上为 None
    """
    if not windows:
        return []
    if not fragments:
        return [{"score": None, "fragment": None}] * len(windows)

    stream = ""
    owner: list[int] = []  # stream 里每个字符属于第几个片段
    for fi, frag in enumerate(fragments):
        norm = _normalize(frag.get("text") or "")
        stream += norm
        owner.extend([fi] * len(norm))

    mapped: list[dict[str, Any]] = []
    cursor = 0
    for w in windows:
        norm = _normalize(w.get("text") or "")
        pos = stream.find(norm, cursor) if norm else -1
        if pos < 0:
            pos = stream.find(norm)  # 作者改动导致错位时再从头找一次
        if pos < 0:
            mapped.append({"score": None, "fragment": None})
            continue
        cursor = pos + len(norm)
        touched = set(owner[pos:pos + len(norm)]) if norm else set()
        if not touched:
            mapped.append({"score": None, "fragment": None})
            continue
        scores = [fragments[i]["score"] for i in touched]
        mapped.append({"score": max(scores), "fragment": fragments[max(touched)]["no"]})
    return mapped
