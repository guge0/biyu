"""
[DEPRECATED by Phase 1] Phase 0 实验脚本
已被 biyu/src/biyu/pipeline.py 替代,保留仅供 T-0.4 数据复现。
Phase 1 后续开发不得引用或修改本文件。
"""
"""T-0.4 三段式流水线 MVP 验证

三组实验:
  core: R1规划 → V3骨架 → Kimi润色 (三段式流水线) + V3/Kimi 单家对照
  a:    Kimi 字数硬约束 (4个变体)
  b:    V3 开场套路消除 (3题材 × 4变体)

用法:
    python tests/pipeline_lab.py --experiment core
    python tests/pipeline_lab.py --experiment a
    python tests/pipeline_lab.py --experiment b
    python tests/pipeline_lab.py --experiment all
    python tests/pipeline_lab.py --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rich.console import Console
from rich.panel import Panel

from biyu.llm import ModelRegistry

console = Console()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data" / "prompt_lab"
CONFIG_PATH = PROJECT_ROOT / "config" / "models.yaml"

# models.yaml keys
R1 = "deepseek-r1"
V3 = "deepseek-v3"
KIMI = "kimi-k2.5"

# ---------------------------------------------------------------------------
# 共享设定素材
# ---------------------------------------------------------------------------

ARENA_SETTING = """\
【人物卡片】
陈风：16岁，青石镇孤儿，炼气期。三天前在废墟密室获得《混沌诀》，
修炼后突破至炼气九层，但实战经验几乎为零。性格隐忍，不服输。
赵天行：19岁，赵家少主，筑基初期。镇上公认的天才，傲慢好斗，
多次当众羞辱陈风。

【已有剧情摘要】
陈风在废墟中获得《混沌诀》并突破炼气期，灵气波动引来赵天行。
赵天行威逼陈风交出宝物未果，反而当众向陈风发起擂台挑战，
定于三日后在镇中武斗场公开比武。三日来陈风疯狂修炼混沌诀第一重，
将灵气凝练到极致，但筑基与炼气之间的境界鸿沟仍难以逾越。

【本章目标】
擂台赛正式开始，陈风以炼气九层对阵筑基初期的赵天行。
目标2000字，要体现境界差距下的智慧对抗，以悬念结尾。"""

RUINS_SETTING = """\
【背景设定】
主角陈风，16岁，青石镇孤儿，被认为是毫无修炼天赋的废柴。
三天前，镇外的荒山突然崩塌，露出地下一片远古废墟。
镇长派人封锁了入口，但陈风趁夜色潜入。

【剧情要求】
第一部分（约600字）：陈风在废墟深处找到一间密室，
石台上放着一枚古朴玉简。他触碰玉简后，大量信息涌入脑海，
这是一部名为《混沌诀》的上古功法。详细描写玉简的纹理、
密室的环境、信息涌入时的感受。

第二部分（约800字）：陈风按照功法指引开始修炼。
详细描写灵气在经脉中运转的过程、突破炼气期的感受、
身体的变化（丹田中凝聚出第一个灵气漩涡）。
修炼过程中他回忆起小时候被人嘲笑的画面，形成情感驱动。

第三部分（约600字）：突破产生的灵气波动被外界感知。
镇上恶霸赵家的少主赵天行（筑基期修为）带人赶到废墟，
威逼陈风交出宝物。陈风虽然刚突破，但面对筑基期的赵天行
仍有巨大差距。结尾要在紧张的对峙中留下悬念。

【写作要求】
1. 玄幻网文的风格，节奏明快
2. 修炼体系的描写要有画面感
3. 人物情绪饱满，不要流水账
4. 结尾设悬念，让读者想继续看"""

# ---------------------------------------------------------------------------
# Core 实验 Prompt
# ---------------------------------------------------------------------------

PROMPT_PLANNING = f"""\
你是中文网文编辑,为作者规划下一章。

{ARENA_SETTING}

产出《本章规划清单》,包含:
1. 必须呈现的 3-5 个情节节点(按时序)
2. 必须避免的一致性陷阱
3. 爽点位置建议(在第几个段落爆发)
4. 关键台词候选(1-2 句)
5. 章末钩子建议

输出:Markdown 列表,200-400 字。只写规划,不写正文。"""


def build_skeleton_prompt(planning: str) -> str:
    return f"""\
你是中文网文作者,严格按以下规划生成本章正文。

【规划清单】
{planning}

硬性要求:
- 总字数 2000 ± 100 字
- 开篇第一句必须包含动作或对话或冲突,禁止"夜色如墨""暮色苍茫"等景物开场
- 禁用"仿佛""像是""犹如"的比喻频次 > 3 次/千字
- 严格遵守规划中的一致性约束
- 章末必须有明确钩子

只输出正文,不要输出字数统计、风格说明等元信息。"""


def build_polish_prompt(skeleton: str) -> str:
    return f"""\
你是资深网文文笔编辑。以下是一章正文,仅做局部润色:

{skeleton}

权限:
1. 重写开篇前 300 字以增强抓人度
2. 优化 1-2 句关键台词增加记忆点

禁区:
- 不得改动情节、设定、人物关系、修为层级
- 不得增删段落,字数波动限 ±50 字
- 不得引入原创前情、新角色、新物品
- 不得使用英文词、现代科学/法律梗、穿越梗

输出:完整润色后章节,保持原长度。"""


PROMPT_V3_ONLY = f"""\
请写一段2000字左右的玄幻小说章节。

{ARENA_SETTING}

【写作要求】
1. 玄幻网文风格,节奏明快
2. 修炼体系的描写要有画面感
3. 人物情绪饱满,不要流水账
4. 结尾设悬念,让读者想继续看

只输出正文,不要输出字数统计、风格说明等元信息。"""

PROMPT_KIMI_ONLY = PROMPT_V3_ONLY

# ---------------------------------------------------------------------------
# Experiment A: Kimi 字数硬约束
# ---------------------------------------------------------------------------

EXP_A_BASELINE = f"请写一段2000字左右的玄幻小说章节。\n\n{RUINS_SETTING}"
EXP_A_V1 = EXP_A_BASELINE + "\n\n必须严格控制在 2000 ± 100 字,超出部分不计入产出。"
EXP_A_V2 = EXP_A_V1 + '\n\n输出前先告诉我你计划如何分配字数(开篇 X 字、主体 Y 字、结尾 Z 字),再生成正文。'
EXP_A_V3 = EXP_A_V2  # v3 adds system prompt, handled separately

EXP_A_SYSTEM_V3 = "你是一个严格字数控制的网文作者,字数超标是你最大的缺点。"

EXP_A_VARIANTS = {
    "exp_a_baseline": {"prompt": EXP_A_BASELINE, "system": None},
    "exp_a_v1": {"prompt": EXP_A_V1, "system": None},
    "exp_a_v2": {"prompt": EXP_A_V2, "system": None},
    "exp_a_v3": {"prompt": EXP_A_V3, "system": EXP_A_SYSTEM_V3},
}

# ---------------------------------------------------------------------------
# Experiment B: V3 开场套路消除
# ---------------------------------------------------------------------------

GENRE_TOPICS = {
    "玄幻": "修仙宗门入门试炼的开篇，主角是一个被认为没有灵根的少年，意外激发了远古血脉",
    "都市": "都市重生文开篇，主角重生回到十年前，发现自己正站在改变命运的关键路口",
    "科幻": "星际探索文开篇，主角是深空探测船上唯一醒着的船员，飞船突然收到未知信号",
}

FEW_SHOT_OPENS = """\
以下是三个优秀开篇范例,供你参考风格:

【范例1-玄幻】"剑气破空的瞬间，陆沉就知道自己藏不住了。"——直接从动作切入,建立紧张感。

【范例2-都市】"'你确定要签？'律师把笔推过来的时候,林晚的手一点都没抖。"——以对话开场,制造悬念。

【范例3-科幻】"警报响第三遍的时候,苏铭终于承认——飞船上不止他一个人。"——冲突先行,立刻勾起好奇心。"""


def build_exp_b_prompt(genre: str, variant: str) -> str:
    topic = GENRE_TOPICS[genre]
    base = f"请写一段500字左右的{genre}小说开篇。\n\n【题材】{topic}\n"

    if variant == "baseline":
        return base + "只输出正文。"
    elif variant == "v1":
        return base + '开篇第一句必须是动作或对话,禁止景物描写。\n\n只输出正文。'
    elif variant == "v2":
        return base + '开篇第一句必须是动作或对话,禁止景物描写。\n\n' + FEW_SHOT_OPENS + "\n只输出正文。"
    elif variant == "v3":
        return (base + '开篇第一句必须是动作或对话,禁止景物描写。\n\n' + FEW_SHOT_OPENS
                + "\n\n如果想写景物描写,放到第三段之后。\n\n只输出正文。")
    raise ValueError(f"Unknown variant: {variant}")


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------

def setup_logging() -> logging.Logger:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("pipeline_lab")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fh = logging.FileHandler(OUTPUT_DIR / "run.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(fh)
    return logger


def check_api_keys(registry: ModelRegistry) -> bool:
    missing = []
    for key in [R1, V3, KIMI]:
        try:
            registry.get_adapter(key)
        except (KeyError, ValueError) as e:
            missing.append(f"{key}: {e}")
    if missing:
        for m in missing:
            console.print(f"[red][X] {m}[/red]")
        return False
    console.print("[green][OK] 3 models ready (R1, V3, Kimi)[/green]")
    return True


async def call_model(
    registry: ModelRegistry,
    model_key: str,
    prompt: str,
    logger: logging.Logger,
    *,
    system: str | None = None,
    temperature: float | None = None,
    max_retries: int = 3,
    retry_delay: float = 5.0,
) -> tuple:
    """Call a model with retry. Returns (LLMResponse | None, error_str | None)."""
    adapter = registry.get_adapter(model_key)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict = {}
    if temperature is not None:
        kwargs["temperature"] = temperature

    for attempt in range(1, max_retries + 1):
        try:
            resp = await adapter.generate(messages, **kwargs)
            logger.info(
                f"model={model_key} attempt={attempt} | "
                f"input={resp.prompt_tokens} output={resp.completion_tokens} | "
                f"cost={resp.cost:.4f}"
            )
            return resp, None
        except Exception as e:
            logger.warning(f"model={model_key} attempt={attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                await asyncio.sleep(retry_delay)
    return None, f"failed after {max_retries} retries"


def get_reasoning_tokens(resp) -> int:
    if resp.raw:
        details = resp.raw.get("usage", {}).get("completion_tokens_details", {})
        return details.get("reasoning_tokens", 0)
    return 0


def write_cost_row(writer, experiment: str, variant: str, stage: str,
                   model: str, resp, error: str | None, latency_ms: int):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if error:
        writer.writerow([
            ts, experiment, variant, stage, model,
            0, 0, 0, latency_ms, 0.0, "failed",
        ])
    else:
        writer.writerow([
            ts, experiment, variant, stage, model,
            resp.prompt_tokens,
            resp.completion_tokens,
            get_reasoning_tokens(resp),
            latency_ms,
            f"{resp.cost:.4f}",
            "ok",
        ])


def save_output(subdir: str, filename: str, text: str):
    d = OUTPUT_DIR / subdir
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Core 实验
# ---------------------------------------------------------------------------

async def run_core(
    registry: ModelRegistry,
    cost_writer,
    logger: logging.Logger,
    dry_run: bool,
) -> list[dict]:
    results = []
    pipeline_start = None
    pipeline_stages_ok = 0

    # Stage 1: R1 Planning
    console.print("  >> [1/5] R1 规划...")
    if dry_run:
        console.print("  [dim][DRY-RUN] R1 规划 | model=deepseek-r1 | -> core/core_planning.md[/dim]")
        results.append({"experiment": "core", "variant": "core_planning", "status": "dry_run"})
    else:
        t0 = time.time()
        resp, err = await call_model(registry, R1, PROMPT_PLANNING, logger)
        latency_ms = int((time.time() - t0) * 1000)
        if err:
            console.print(f"  [red][X] R1 规划 failed: {err}[/red]")
            write_cost_row(cost_writer, "core", "core_planning", "1", R1, None, err, latency_ms)
            results.append({"experiment": "core", "variant": "core_planning", "status": "failed"})
        else:
            planning_text = resp.text
            save_output("core", "core_planning.md", planning_text)
            write_cost_row(cost_writer, "core", "core_planning", "1", R1, resp, None, latency_ms)
            console.print(f"  [green][OK] R1 规划 ({latency_ms}ms, {resp.completion_tokens}tok)[/green]")
            results.append({"experiment": "core", "variant": "core_planning", "status": "ok",
                           "latency_ms": latency_ms, "cost": resp.cost})
            pipeline_start = time.time()
            pipeline_stages_ok += 1

        await asyncio.sleep(2)

    # Stage 2: V3 Skeleton (depends on stage 1)
    planning_available = not dry_run and any(
        r["variant"] == "core_planning" and r["status"] == "ok" for r in results
    )
    planning_text = ""
    if not dry_run and planning_available:
        # read back saved planning
        planning_text = (OUTPUT_DIR / "core" / "core_planning.md").read_text(encoding="utf-8")

    console.print("  >> [2/5] V3 骨架...")
    if dry_run:
        console.print("  [dim][DRY-RUN] V3 骨架 | model=deepseek-v3 temp=0.8 | -> core/core_skeleton.md[/dim]")
        results.append({"experiment": "core", "variant": "core_skeleton", "status": "dry_run"})
    elif planning_available:
        t0 = time.time()
        resp, err = await call_model(registry, V3, build_skeleton_prompt(planning_text), logger, temperature=0.8)
        latency_ms = int((time.time() - t0) * 1000)
        if err:
            console.print(f"  [red][X] V3 骨架 failed: {err}[/red]")
            write_cost_row(cost_writer, "core", "core_skeleton", "2", V3, None, err, latency_ms)
            results.append({"experiment": "core", "variant": "core_skeleton", "status": "failed"})
        else:
            save_output("core", "core_skeleton.md", resp.text)
            write_cost_row(cost_writer, "core", "core_skeleton", "2", V3, resp, None, latency_ms)
            console.print(f"  [green][OK] V3 骨架 ({latency_ms}ms, {resp.completion_tokens}tok)[/green]")
            results.append({"experiment": "core", "variant": "core_skeleton", "status": "ok",
                           "latency_ms": latency_ms, "cost": resp.cost})
            pipeline_stages_ok += 1
        await asyncio.sleep(2)
    else:
        console.print("  [yellow][SKIP] V3 骨架 — 上游 R1 规划失败[/yellow]")

    # Stage 3: Kimi Polish (depends on stage 2)
    skeleton_available = not dry_run and any(
        r["variant"] == "core_skeleton" and r["status"] == "ok" for r in results
    )
    skeleton_text = ""
    if skeleton_available:
        skeleton_text = (OUTPUT_DIR / "core" / "core_skeleton.md").read_text(encoding="utf-8")

    console.print("  >> [3/5] Kimi 润色...")
    if dry_run:
        console.print("  [dim][DRY-RUN] Kimi 润色 | model=kimi-k2.5 | -> core/core_polished.md[/dim]")
        results.append({"experiment": "core", "variant": "core_polished", "status": "dry_run"})
    elif skeleton_available:
        t0 = time.time()
        resp, err = await call_model(registry, KIMI, build_polish_prompt(skeleton_text), logger)
        latency_ms = int((time.time() - t0) * 1000)
        if err:
            console.print(f"  [red][X] Kimi 润色 failed: {err}[/red]")
            write_cost_row(cost_writer, "core", "core_polished", "3", KIMI, None, err, latency_ms)
            results.append({"experiment": "core", "variant": "core_polished", "status": "failed"})
        else:
            save_output("core", "core_polished.md", resp.text)
            write_cost_row(cost_writer, "core", "core_polished", "3", KIMI, resp, None, latency_ms)
            console.print(f"  [green][OK] Kimi 润色 ({latency_ms}ms, {resp.completion_tokens}tok)[/green]")
            results.append({"experiment": "core", "variant": "core_polished", "status": "ok",
                           "latency_ms": latency_ms, "cost": resp.cost})
            pipeline_stages_ok += 1

            # 端到端延迟
            if pipeline_start:
                e2e_ms = int((time.time() - pipeline_start) * 1000)
                results.append({"experiment": "core", "variant": "pipeline_e2e",
                               "status": "ok", "latency_ms": e2e_ms})
                console.print(f"  [bold cyan]三段式端到端延迟: {e2e_ms / 1000:.1f}s[/bold cyan]")
        await asyncio.sleep(2)
    else:
        console.print("  [yellow][SKIP] Kimi 润色 — 上游 V3 骨架失败[/yellow]")

    # Stage 4: V3 单家对照
    console.print("  >> [4/5] V3 单家对照...")
    if dry_run:
        console.print("  [dim][DRY-RUN] V3 单家对照 | model=deepseek-v3 temp=0.8 | -> core/core_v3_only.md[/dim]")
        results.append({"experiment": "core", "variant": "core_v3_only", "status": "dry_run"})
    else:
        t0 = time.time()
        resp, err = await call_model(registry, V3, PROMPT_V3_ONLY, logger, temperature=0.8)
        latency_ms = int((time.time() - t0) * 1000)
        if err:
            console.print(f"  [red][X] V3 单家对照 failed: {err}[/red]")
            write_cost_row(cost_writer, "core", "core_v3_only", "", V3, None, err, latency_ms)
            results.append({"experiment": "core", "variant": "core_v3_only", "status": "failed"})
        else:
            save_output("core", "core_v3_only.md", resp.text)
            write_cost_row(cost_writer, "core", "core_v3_only", "", V3, resp, None, latency_ms)
            console.print(f"  [green][OK] V3 单家对照 ({latency_ms}ms, {resp.completion_tokens}tok)[/green]")
            results.append({"experiment": "core", "variant": "core_v3_only", "status": "ok",
                           "latency_ms": latency_ms, "cost": resp.cost})
        await asyncio.sleep(2)

    # Stage 5: Kimi 单家对照
    console.print("  >> [5/5] Kimi 单家对照...")
    if dry_run:
        console.print("  [dim][DRY-RUN] Kimi 单家对照 | model=kimi-k2.5 | -> core/core_kimi_only.md[/dim]")
        results.append({"experiment": "core", "variant": "core_kimi_only", "status": "dry_run"})
    else:
        t0 = time.time()
        resp, err = await call_model(registry, KIMI, PROMPT_KIMI_ONLY, logger)
        latency_ms = int((time.time() - t0) * 1000)
        if err:
            console.print(f"  [red][X] Kimi 单家对照 failed: {err}[/red]")
            write_cost_row(cost_writer, "core", "core_kimi_only", "", KIMI, None, err, latency_ms)
            results.append({"experiment": "core", "variant": "core_kimi_only", "status": "failed"})
        else:
            save_output("core", "core_kimi_only.md", resp.text)
            write_cost_row(cost_writer, "core", "core_kimi_only", "", KIMI, resp, None, latency_ms)
            console.print(f"  [green][OK] Kimi 单家对照 ({latency_ms}ms, {resp.completion_tokens}tok)[/green]")
            results.append({"experiment": "core", "variant": "core_kimi_only", "status": "ok",
                           "latency_ms": latency_ms, "cost": resp.cost})
        await asyncio.sleep(2)

    return results


# ---------------------------------------------------------------------------
# Experiment A: Kimi 字数硬约束
# ---------------------------------------------------------------------------

async def run_exp_a(
    registry: ModelRegistry,
    cost_writer,
    logger: logging.Logger,
    dry_run: bool,
) -> list[dict]:
    results = []
    variants = list(EXP_A_VARIANTS.items())

    for idx, (name, cfg) in enumerate(variants):
        console.print(f"  >> [{idx+1}/4] {name}...")
        if dry_run:
            sys_line = f" system={cfg['system'][:30]}..." if cfg["system"] else ""
            console.print(f"  [dim][DRY-RUN] {name} | model=kimi-k2.5{sys_line} | -> exp_a/{name}.md[/dim]")
            results.append({"experiment": "a", "variant": name, "status": "dry_run"})
            continue

        t0 = time.time()
        resp, err = await call_model(
            registry, KIMI, cfg["prompt"], logger,
            system=cfg["system"],
        )
        latency_ms = int((time.time() - t0) * 1000)

        if err:
            console.print(f"  [red][X] {name} failed: {err}[/red]")
            write_cost_row(cost_writer, "a", name, "", KIMI, None, err, latency_ms)
            results.append({"experiment": "a", "variant": name, "status": "failed"})
        else:
            save_output("exp_a", f"{name}.md", resp.text)
            write_cost_row(cost_writer, "a", name, "", KIMI, resp, None, latency_ms)
            console.print(f"  [green][OK] {name} ({latency_ms}ms, {resp.completion_tokens}tok)[/green]")
            results.append({"experiment": "a", "variant": name, "status": "ok",
                           "latency_ms": latency_ms, "cost": resp.cost})

        if idx < len(variants) - 1:
            await asyncio.sleep(2)

    return results


# ---------------------------------------------------------------------------
# Experiment B: V3 开场套路消除
# ---------------------------------------------------------------------------

async def run_exp_b(
    registry: ModelRegistry,
    cost_writer,
    logger: logging.Logger,
    dry_run: bool,
) -> list[dict]:
    results = []
    genres = list(GENRE_TOPICS.keys())
    variants = ["baseline", "v1", "v2", "v3"]
    call_idx = 0
    total = len(genres) * len(variants)

    for genre in genres:
        for variant in variants:
            call_idx += 1
            name = f"exp_b_{genre}_{variant}"
            filename = f"{name}.md"
            prompt = build_exp_b_prompt(genre, variant)

            console.print(f"  >> [{call_idx}/{total}] {name}...")
            if dry_run:
                console.print(f"  [dim][DRY-RUN] {name} | model=deepseek-v3 temp=0.8 | -> exp_b/{filename}[/dim]")
                results.append({"experiment": "b", "variant": name, "status": "dry_run"})
                continue

            t0 = time.time()
            resp, err = await call_model(registry, V3, prompt, logger, temperature=0.8)
            latency_ms = int((time.time() - t0) * 1000)

            if err:
                console.print(f"  [red][X] {name} failed: {err}[/red]")
                write_cost_row(cost_writer, "b", name, "", V3, None, err, latency_ms)
                results.append({"experiment": "b", "variant": name, "status": "failed"})
            else:
                save_output("exp_b", filename, resp.text)
                write_cost_row(cost_writer, "b", name, "", V3, resp, None, latency_ms)
                console.print(f"  [green][OK] {name} ({latency_ms}ms, {resp.completion_tokens}tok)[/green]")
                results.append({"experiment": "b", "variant": name, "status": "ok",
                               "latency_ms": latency_ms, "cost": resp.cost})

            if call_idx < total:
                await asyncio.sleep(2)

    return results


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def write_summary(all_results: list[dict], elapsed_total: float):
    ok = [r for r in all_results if r["status"] == "ok"]
    failed = [r for r in all_results if r["status"] == "failed"]
    total_cost = sum(r.get("cost", 0) for r in ok)

    # Pipeline E2E latency
    e2e_results = [r for r in all_results if r.get("variant") == "pipeline_e2e"]
    e2e_line = ""
    if e2e_results:
        e2e_ms = e2e_results[0]["latency_ms"]
        e2e_line = f"\n三段式端到端延迟: {e2e_ms / 1000:.1f}s"

    summary = f"""\
# T-0.4 执行汇总

生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 总览

- 总耗时: {elapsed_total:.1f}s
- 总成本: {total_cost:.4f} CNY
- 成功: {len(ok)} 次
- 失败: {len(failed)} 次{e2e_line}

## 各实验详情

### Core: 三段式流水线

"""
    core = [r for r in all_results if r.get("experiment") == "core" and r.get("variant") != "pipeline_e2e"]
    for r in core:
        status = r["status"]
        extra = ""
        if status == "ok":
            extra = f" | {r.get('latency_ms', 0)}ms | ¥{r.get('cost', 0):.4f}"
        summary += f"- {r['variant']}: {status}{extra}\n"

    summary += "\n### Experiment A: Kimi 字数硬约束\n\n"
    exp_a = [r for r in all_results if r.get("experiment") == "a"]
    for r in exp_a:
        status = r["status"]
        extra = ""
        if status == "ok":
            extra = f" | {r.get('latency_ms', 0)}ms | ¥{r.get('cost', 0):.4f}"
        summary += f"- {r['variant']}: {status}{extra}\n"

    summary += "\n### Experiment B: V3 开场套路消除\n\n"
    exp_b = [r for r in all_results if r.get("experiment") == "b"]
    for r in exp_b:
        status = r["status"]
        extra = ""
        if status == "ok":
            extra = f" | {r.get('latency_ms', 0)}ms | ¥{r.get('cost', 0):.4f}"
        summary += f"- {r['variant']}: {status}{extra}\n"

    if failed:
        summary += "\n## 失败详情\n\n"
        for r in failed:
            summary += f"- {r.get('experiment', '')}/{r.get('variant', '')}: {r.get('error', 'unknown')}\n"

    (OUTPUT_DIR / "summary.md").write_text(summary, encoding="utf-8")


def estimate_cost() -> float:
    """粗估总 token 消耗成本"""
    # Core: 5 calls
    # R1: ~1k in, ~0.5k out → ¥0.004*1 + ¥0.016*0.5 = ¥0.012
    # V3: ~2k in, ~2.5k out x2 → ¥0.002*4 + ¥0.008*5 = ¥0.048
    # Kimi: ~2.5k in, ~2.5k out x2 → ¥0.004*5 + ¥0.021*5 = ¥0.125
    core = 0.012 + 0.048 + 0.125
    # Exp A: 4 Kimi calls, ~1.5k in, ~2.5k out each → ¥0.004*6 + ¥0.021*10 = ¥0.234
    exp_a = 0.234
    # Exp B: 12 V3 calls, ~0.5k in, ~0.7k out each → ¥0.002*6 + ¥0.008*8.4 = ¥0.079
    exp_b = 0.079
    return core + exp_a + exp_b


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

async def run_experiments(which: str, dry_run: bool):
    logger = setup_logging()
    logger.info(f"T-0.4 start: experiment={which}, dry_run={dry_run}")

    registry = ModelRegistry(CONFIG_PATH)

    if not dry_run:
        if not check_api_keys(registry):
            console.print("[red]API Key check failed.[/red]")
            return

    # Cost log
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cost_path = OUTPUT_DIR / "cost_log.csv"
    is_new = not cost_path.exists()
    cost_file = open(cost_path, "a", encoding="utf-8", newline="")
    cost_writer = csv.writer(cost_file)
    if is_new:
        cost_writer.writerow([
            "timestamp", "experiment", "variant", "stage", "model",
            "input_tokens", "output_tokens", "reasoning_tokens",
            "latency_ms", "cost_cny", "status",
        ])

    all_results: list[dict] = []
    total_start = time.time()

    try:
        est = estimate_cost()
        console.print(Panel(
            "[bold]T-0.4 三段式流水线 MVP 验证[/bold]\n"
            f"Experiment: {which}  Mode: {'DRY-RUN' if dry_run else 'live'}\n"
            f"预估成本: ~¥{est:.2f}",
            border_style="blue",
        ))

        if est > 20:
            console.print(f"[red][WARN] 预估成本 ¥{est:.2f} 超过 ¥20 上限！请确认后继续。[/red]")
            if not dry_run:
                return

        if dry_run:
            console.print("[yellow]DRY-RUN -- 打印调用计划[/yellow]\n")

        # Run experiments
        if which in ("core", "all"):
            console.rule("[bold cyan]Experiment Core: 三段式流水线[/bold cyan]")
            all_results.extend(await run_core(registry, cost_writer, logger, dry_run))
            console.print("")

        if which in ("a", "all"):
            console.rule("[bold cyan]Experiment A: Kimi 字数硬约束[/bold cyan]")
            all_results.extend(await run_exp_a(registry, cost_writer, logger, dry_run))
            console.print("")

        if which in ("b", "all"):
            console.rule("[bold cyan]Experiment B: V3 开场套路消除[/bold cyan]")
            all_results.extend(await run_exp_b(registry, cost_writer, logger, dry_run))
            console.print("")

        elapsed_total = time.time() - total_start
        console.rule("[bold green]All Experiments Complete[/bold green]\n")

        if not dry_run:
            write_summary(all_results, elapsed_total)
            ok = [r for r in all_results if r["status"] == "ok"]
            failed = [r for r in all_results if r["status"] == "failed"]
            total_cost = sum(r.get("cost", 0) for r in ok)
            e2e = [r for r in all_results if r.get("variant") == "pipeline_e2e"]
            e2e_str = f"\n三段式端到端延迟: {e2e[0]['latency_ms']/1000:.1f}s" if e2e else ""

            console.print(f"总耗时: [bold]{elapsed_total:.1f}s[/bold]")
            console.print(f"总成本: [bold yellow]¥{total_cost:.4f}[/bold yellow]")
            console.print(f"成功/失败: [green]{len(ok)}[/green]/[red]{len(failed)}[/red]")
            if e2e_str:
                console.print(f"[cyan]{e2e_str}[/cyan]")
            console.print(f"\n输出目录: [dim]{OUTPUT_DIR}[/dim]")
            console.print(f"汇总: [dim]{OUTPUT_DIR / 'summary.md'}[/dim]")

            logger.info(f"T-0.4 done: {elapsed_total:.1f}s | cost={total_cost:.4f} | ok={len(ok)} fail={len(failed)}")

        if dry_run:
            # Count planned calls
            calls = 0
            if which in ("core", "all"):
                calls += 5
            if which in ("a", "all"):
                calls += 4
            if which in ("b", "all"):
                calls += 12
            console.print(f"\n计划 API 调用: [bold]{calls}[/bold] 次")
            console.print(f"输出目录: [dim]{OUTPUT_DIR}[/dim]")

    finally:
        cost_file.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="T-0.4 三段式流水线 MVP 验证")
    parser.add_argument("--experiment", choices=["core", "a", "b", "all"], default="all")
    parser.add_argument("--dry-run", action="store_true", help="打印计划不调用API")
    return parser.parse_args()


def main():
    args = parse_args()
    asyncio.run(run_experiments(args.experiment, args.dry_run))


if __name__ == "__main__":
    main()
