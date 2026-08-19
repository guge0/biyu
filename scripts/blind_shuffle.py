#!/usr/bin/env python
"""blind_shuffle.py — 盲测物料封装工具(P8-M3R-fix F4)。

用途:把 N 份 md 物料随机天干标签(甲-癸,最多 10)shuffle 后复制到 out-dir,
密封映射写到 seal-dir/<task>_mapping.json。stdout 只打物料路径(防揭盲前泄漏)。

典型用法:
    python scripts/blind_shuffle.py \\
        --task B5 \\
        --in alpha.md beta.md gamma.md \\
        --out-dir washed/ \\
        --seal-dir _mapping_sealed/

设计决策(spec §F4):
- 天干标签(甲乙丙丁戊己庚辛壬癸,10 个);超 10 报错不截断(防数据丢失)。
- shuffle 而非机械对应(随机双射)。
- 默认随机;可 --seed N 复现(审计/调试)。
- stdout 行为严格:每行一份 washed_label_path(可被管道消费);其他消息走 stderr。
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Windows 默认 cp936 输出会乱码天干字符;强制 UTF-8(跨平台一致)。
# Python 3.7+ 支持 reconfigure;旧版无此方法时静默跳过(无副作用)。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass

# 天干标签集(甲-癸,10 个)。超出报错。
HEAVENLY_STEMS = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]

# stdout 黑名单关键字(测试 + 文档双约束):stdout 永不含这些。
# 注:这是文档化约束,实际过滤靠"stdout 只打路径"的设计,不是事后过滤。


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析 CLI 参数。"""
    p = argparse.ArgumentParser(
        prog="blind_shuffle.py",
        description="盲测物料封装:随机天干标签 shuffle 复制 + 密封映射。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--task", required=True, help="任务标签(如 B5);用于 mapping.json 文件名")
    p.add_argument("--in", dest="inputs", nargs="+", required=True,
                   metavar="MD", help="输入 md 文件路径(1-10 份)")
    p.add_argument("--out-dir", required=True, help="物料输出目录(shuffle 后的 md 落此处)")
    p.add_argument("--seal-dir", required=True, help="密封目录(mapping.json 落此处)")
    p.add_argument("--seed", type=int, default=None,
                   help="随机种子(同 seed → 同映射;默认随机不复现)")
    return p.parse_args(argv)


def shuffle_labels(n: int, seed: int | None = None) -> list[str]:
    """从前 n 个天干标签随机抽 n 个 shuffle 返回。

    返回 list[str],长度 = n,元素取自 HEAVENLY_STEMS[:n],顺序随机。
    """
    if n > len(HEAVENLY_STEMS):
        raise ValueError(
            f"输入数量 {n} 超过天干标签上限 {len(HEAVENLY_STEMS)};盲测物料最多 10 份"
        )
    rng = random.Random(seed) if seed is not None else random.Random()
    labels = list(HEAVENLY_STEMS[:n])
    rng.shuffle(labels)
    return labels


def run(argv: list[str] | None = None) -> int:
    """主入口。返退出码(0 成功 / 非 0 失败)。"""
    args = parse_args(argv)

    # 收集输入路径(规范成绝对路径,便于 mapping 可追溯)
    input_paths: list[Path] = []
    for raw in args.inputs:
        p = Path(raw).resolve()
        if not p.exists():
            print(f"[blind_shuffle] 错误:输入文件不存在: {raw}", file=sys.stderr)
            return 2
        if p.suffix.lower() != ".md":
            print(f"[blind_shuffle] 警告:非 .md 文件仍接受: {raw}", file=sys.stderr)
        input_paths.append(p)

    n = len(input_paths)

    # 标签上限校验(超 10 → 友好报错 + 不写任何文件,原子性)
    if n > len(HEAVENLY_STEMS):
        print(
            f"[blind_shuffle] 错误:输入 {n} 份超过天干标签上限 {len(HEAVENLY_STEMS)};"
            "盲测物料最多 10 份。请减少输入或拆批。",
            file=sys.stderr,
        )
        return 2

    # shuffle 标签
    try:
        labels = shuffle_labels(n, seed=args.seed)
    except ValueError as e:
        print(f"[blind_shuffle] 错误:{e}", file=sys.stderr)
        return 2

    # 准备目录
    out_dir = Path(args.out_dir).resolve()
    seal_dir = Path(args.seal_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    seal_dir.mkdir(parents=True, exist_ok=True)

    # 逐份复制 + 构造映射条目
    mapping_labels: dict[str, dict] = {}
    washed_paths_for_stdout: list[Path] = []
    for src, label in zip(input_paths, labels):
        washed = out_dir / f"{label}.md"
        shutil.copy2(src, washed)
        mapping_labels[label] = {
            "source_path": str(src),
            "washed_label_path": str(washed),
        }
        washed_paths_for_stdout.append(washed)

    # 写 mapping.json(密封)
    mapping = {
        "task": args.task,
        "sealed_at": datetime.now().isoformat(timespec="seconds"),
        "labeling_scheme": "heavenly_stems_shuffle",
        "seed_used": args.seed,
        "reveal_rule": "老板判卷后揭盲,映射表不可在判卷前给老板看",
        "labels": mapping_labels,
    }
    mapping_file = seal_dir / f"{args.task}_mapping.json"
    mapping_file.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 日志(metadata/debug)走 stderr;stdout 只打物料路径
    print(
        f"[blind_shuffle] 完成:{n} 份 → {out_dir} | mapping → {mapping_file}",
        file=sys.stderr,
    )
    for washed in washed_paths_for_stdout:
        print(washed)

    return 0


if __name__ == "__main__":
    sys.exit(run())
