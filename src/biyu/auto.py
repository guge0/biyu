"""全自动批量生成模式 — 循环调用 generate_chapter() 连续生成多章。

带焰断保护: 连续 N 章失败 / 单章 retry 超限 / 预算超硬停线 → 立即停止。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable

from biyu.config import BookConfig


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 焰断保护配置
# ---------------------------------------------------------------------------

CIRCUIT_BREAKER_DEFAULTS = {
    "consecutive_fail_threshold": 3,   # 连续失败章数阈值
    "per_chapter_retry_max": 5,        # 单章重试上限
    "budget_hard_stop": 50.0,          # ¥,超过硬停
}


def _load_auto_config() -> dict:
    """从 models.yaml 读取 auto 配置段,不存在则用默认值。

    models.yaml 中可选的 auto 段:
        auto:
          consecutive_fail_threshold: 3
          per_chapter_retry_max: 5
          budget_hard_stop: 50

    P7-5 改出声:加载失败时 log.warning 含原因,不许静默 fallback——
    与 editor.py _load_editor_max_tokens 同理由(静默会让 bug 长期潜伏)。
    """
    try:
        import yaml
        from biyu.config import get_config_path

        with open(get_config_path(), encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        auto_cfg = cfg.get("auto", {})
        merged = dict(CIRCUIT_BREAKER_DEFAULTS)
        merged.update(auto_cfg)
        return merged
    except Exception as e:
        logger.warning(
            "models.yaml 加载失败,fallback 到默认 auto 配置 %r。原因: %r。",
            dict(CIRCUIT_BREAKER_DEFAULTS), e,
        )
        return dict(CIRCUIT_BREAKER_DEFAULTS)


# ---------------------------------------------------------------------------
# 焰断保护异常
# ---------------------------------------------------------------------------

class CircuitBreakerTripped(Exception):
    """焰断保护触发。"""
    pass


# ---------------------------------------------------------------------------
# 失败判定
# ---------------------------------------------------------------------------

def _is_chapter_failed(result, book: BookConfig, ch: int) -> tuple[bool, str]:
    """判定章节是否失败(写入 _pending/)。

    Returns:
        (failed, reason) — failed=True 时 reason 说明原因。
    """
    pending_path = book.chapters_dir / "_pending" / f"ch{ch}.md"
    if not pending_path.exists():
        return False, ""

    # 从 warnings 中提取具体原因
    for w in result.warnings:
        if "BLOCK" in w:
            return True, w
    for w in result.warnings:
        if "_pending" in w or "质量" in w:
            return True, w
    return True, f"ch{ch} 写入 _pending/ (质量未达标)"


# ---------------------------------------------------------------------------
# 诊断报告
# ---------------------------------------------------------------------------

def _print_diagnostic(failure_log: list[tuple[int, str]], trigger_reason: str) -> None:
    """打印失败诊断报告。"""
    print(f"\n{'='*60}")
    print(f"[auto] 焰断保护触发: {trigger_reason}")
    print(f"{'='*60}")
    print("失败章节:")
    for ch, reason in failure_log:
        print(f"  ch{ch}: {reason}")
    print("\n建议人工介入:")
    if failure_log:
        first_fail_ch = failure_log[0][0]
        print(f"  - 从第 {first_fail_ch} 章开始失败,检查该章大纲和前文")
    print("  - 已生成章节保留在原位,未删除")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

async def auto_generate(
    book_dir: Path,
    from_ch: int,
    to_ch: int,
    on_progress: Callable[[int, int, object], None] | None = None,
    warning_threshold: float = 12.0,
) -> list:
    """批量生成章节,带焰断保护。

    Args:
        book_dir: 书目录。
        from_ch: 起始章节号。
        to_ch: 结束章节号(含)。
        on_progress: 可选回调 (chapter_num, total_done, ChapterResult)。
        warning_threshold: 累计成本报警线(元)。超过后 warning 但不中断。

    Returns:
        List of ChapterResult。

    Raises:
        CircuitBreakerTripped: 焰断保护触发时抛出。
    """
    from biyu.pipeline import generate_chapter

    book = BookConfig(book_dir)
    results: list = []
    total_cost = 0.0
    consecutive_failures = 0
    failure_log: list[tuple[int, str]] = []

    cfg = _load_auto_config()
    fail_threshold = cfg["consecutive_fail_threshold"]
    retry_max = cfg["per_chapter_retry_max"]
    budget_hard_stop = cfg["budget_hard_stop"]

    for ch in range(from_ch, to_ch + 1):
        # 检查大纲文件存在性
        outline_path = book.outline_path(ch)
        if not outline_path.exists():
            print(f"[auto] ch{ch} 大纲不存在: {outline_path},停止")
            break

        print(f"\n{'='*60}")
        print(f"[auto] 生成第 {ch} 章 ({ch - from_ch + 1}/{to_ch - from_ch + 1})")
        print(f"{'='*60}")

        # ---- 单章重试循环 ----
        result = None
        ch_failed = False
        ch_failure_reason = ""

        for attempt in range(1, retry_max + 1):
            if attempt > 1:
                print(f"  [auto] ch{ch} 第 {attempt}/{retry_max} 次重试...")

            try:
                result = await generate_chapter(book_dir, ch)
            except Exception as e:
                ch_failed = True
                ch_failure_reason = f"生成异常: {e}"
                print(f"  [auto] ch{ch} 异常: {e}")
                if attempt < retry_max:
                    await asyncio.sleep(5.0)
                    continue
                # 超过重试上限
                break

            total_cost += result.cost_cny

            # 预算硬停
            if total_cost >= budget_hard_stop:
                print(f"\n[auto] 焰断: 累计成本 ¥{total_cost:.2f} >= 硬停线 ¥{budget_hard_stop:.2f}")
                results.append(result)
                _print_diagnostic(failure_log, f"预算硬停 ¥{total_cost:.2f}")
                raise CircuitBreakerTripped(
                    f"预算硬停: ¥{total_cost:.2f} >= ¥{budget_hard_stop:.2f}"
                )

            # 检查是否失败(写入 _pending)
            failed, reason = _is_chapter_failed(result, book, ch)
            if failed:
                ch_failed = True
                ch_failure_reason = reason
                print(f"  [auto] ch{ch} 未达标: {reason}")
                if attempt < retry_max:
                    continue
                break
            else:
                ch_failed = False
                break

        if result is not None:
            results.append(result)
            if on_progress:
                on_progress(ch, len(results), result)

        # 更新连续失败计数
        if ch_failed:
            consecutive_failures += 1
            failure_log.append((ch, ch_failure_reason))
            print(f"  [auto] 连续失败: {consecutive_failures}/{fail_threshold}")
        else:
            consecutive_failures = 0

        # 连续失败焰断
        if consecutive_failures >= fail_threshold:
            print(f"\n[auto] 焰断: 连续 {consecutive_failures} 章失败")
            _print_diagnostic(failure_log, f"连续 {consecutive_failures} 章失败")
            raise CircuitBreakerTripped(
                f"连续 {consecutive_failures} 章失败 >= 阈值 {fail_threshold}"
            )

        # 预算警告(原有逻辑)
        if total_cost >= warning_threshold:
            print(f"  [auto] 累计成本 ¥{total_cost:.2f},超过报警线 ¥{warning_threshold:.2f}")

        if result is not None:
            print(f"  [auto] ch{ch} 完成: {result.word_count}字, ¥{result.cost_cny:.4f}, 累计 ¥{total_cost:.4f}")

    print(f"\n[auto] 批量生成完成: {len(results)}/{to_ch - from_ch + 1} 章, 总成本 ¥{total_cost:.4f}")
    return results
