"""构造 distractor-replacement 夹具(P6-A2 收尾验证)。

把 T1_clean.md 里若干锚的 canonical 值替换成结构同形但数值/取值不同的 distractor,
产出 T1_distractor_replaced.md,供验证 B1 引擎在"纯 distractor 触发"场景的表现。

替换清单(每条注明 anchor id + 是否在 mismatch_aliases 中声明):
  - T1-H05(设定 黑色手套, mismatch_aliases 已声明): 黑色手套 → 白手套
  - T1-H10(数字 四十一分钟, slot 41|分钟, mismatch_aliases 未声明): 四十一分钟 → 四十二分钟
  - T1-H13(时间 三天后上午十点, slot 10:00, mismatch_aliases 未声明):
      上午十点 → 上午十一点  (line 281)
      到十点   → 到十一点    (line 253,因 normalize_time_hm 会从此处抽出 "10:00")
  - T1-H14(地点 市档案馆三楼, mismatch_aliases 已声明): 市档案馆三楼 → 市档案馆二楼
  - T1-H16(数字 A-113, mismatch_aliases 已声明): A-113 → A-131(两处)

目的:观察 declared distractor(3 条)与 undeclared slot distractor(2 条)分别被引擎怎么判。
零成本:纯文本替换,不调 LLM。
"""
from __future__ import annotations

from pathlib import Path

EVAL_SET = Path("eval_set_v0")
SRC = EVAL_SET / "baseline" / "T1_clean.md"
DST_DIR = EVAL_SET / "distractor_replacement"
DST = DST_DIR / "T1_distractor_replaced.md"

REPLACEMENTS: list[tuple[str, str, str]] = [
    ("黑色手套", "白手套", "T1-H05 (declared)"),
    ("四十一分钟", "四十二分钟", "T1-H10 (undeclared slot)"),
    ("上午十点", "上午十一点", "T1-H13 (undeclared slot)"),
    ("到十点", "到十一点", "T1-H13 (undeclared slot, line 253 抽 10:00)"),
    ("市档案馆三楼", "市档案馆二楼", "T1-H14 (declared)"),
    ("A-113", "A-131", "T1-H16 (declared)"),
]


def main() -> None:
    DST_DIR.mkdir(parents=True, exist_ok=True)
    text = SRC.read_text(encoding="utf-8")
    print(f"源: {SRC} ({len(text)} chars)")
    print("替换:")
    for old, new, note in REPLACEMENTS:
        count = text.count(old)
        text = text.replace(old, new)
        print(f"  {old} → {new}  [{count} 处]  {note}")
    DST.write_text(text, encoding="utf-8")
    print(f"\n-> 写 {DST} ({len(text)} chars)")


if __name__ == "__main__":
    main()
