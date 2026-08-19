"""T-0.3.5 五模型网文生成质量评估工具 (v2)

扩展 T-0.3 测试，新增 Kimi K2.5 和 Doubao-1.6。
测试用例与 T-0.3 完全一致，结果保存到 data/eval_v2/。

用法:
    python tests/model_eval_v2.py --all
    python tests/model_eval_v2.py --test 1
    python tests/model_eval_v2.py --model kimi
    python tests/model_eval_v2.py --dry-run
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
from rich.table import Table

from biyu.llm import ModelRegistry

console = Console()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = PROJECT_ROOT / "data" / "eval_v2"
CONFIG_PATH = PROJECT_ROOT / "config" / "models.yaml"

# models.yaml key -> (alias for CLI/file, display provider)
MODEL_MAP = {
    "glm": "glm-4.6",
    "deepseek_v3": "deepseek-v3",
    "deepseek_r1": "deepseek-r1",
    "kimi": "kimi-k2.5",
    "doubao": "doubao-1.6",
}
FILE_SUFFIX = {
    "glm": "glm",
    "deepseek_v3": "deepseek_v3",
    "deepseek_r1": "deepseek_r1",
    "kimi": "kimi",
    "doubao": "doubao",
}
PROVIDER = {
    "glm": "glm",
    "deepseek_v3": "deepseek",
    "deepseek_r1": "deepseek",
    "kimi": "kimi",
    "doubao": "doubao",
}

TEST_MATRIX = {
    1: ["glm", "deepseek_v3", "kimi", "doubao"],
    2: ["glm", "deepseek_v3", "kimi", "doubao"],
    3: ["glm", "deepseek_v3", "kimi", "doubao"],
    4: ["glm", "deepseek_v3", "kimi", "doubao"],
    5: ["glm", "deepseek_v3", "kimi", "doubao", "deepseek_r1"],
}

# ---------------------------------------------------------------------------
# Test prompts (identical to T-0.3)
# ---------------------------------------------------------------------------
TESTS = {
    1: {
        "name": "基础章节生成",
        "id": "test1",
        "prompt": (
            "请写一段2000字左右的玄幻小说章节，要求如下：\n\n"
            "【背景设定】\n"
            "主角陈风，16岁，青石镇孤儿，被认为是毫无修炼天赋的废柴。"
            "三天前，镇外的荒山突然崩塌，露出地下一片远古废墟。"
            "镇长派人封锁了入口，但陈风趁夜色潜入。\n\n"
            "【剧情要求】\n"
            "第一部分（约600字）：陈风在废墟深处找到一间密室，"
            "石台上放着一枚古朴玉简。他触碰玉简后，大量信息涌入脑海，"
            "这是一部名为《混沌诀》的上古功法。详细描写玉简的纹理、"
            "密室的环境、信息涌入时的感受。\n\n"
            "第二部分（约800字）：陈风按照功法指引开始修炼。"
            "详细描写灵气在经脉中运转的过程、突破炼气期的感受、"
            "身体的变化（丹田中凝聚出第一个灵气漩涡）。"
            "修炼过程中他回忆起小时候被人嘲笑的画面，形成情感驱动。\n\n"
            "第三部分（约600字）：突破产生的灵气波动被外界感知。"
            "镇上恶霸赵家的少主赵天行（筑基期修为）带人赶到废墟，"
            "威逼陈风交出宝物。陈风虽然刚突破，但面对筑基期的赵天行"
            "仍有巨大差距。结尾要在紧张的对峙中留下悬念。\n\n"
            "【写作要求】\n"
            "1. 玄幻网文的风格，节奏明快\n"
            "2. 修炼体系的描写要有画面感\n"
            "3. 人物情绪饱满，不要流水账\n"
            "4. 结尾设悬念，让读者想继续看"
        ),
    },
    2: {
        "name": "角色区分度",
        "id": "test2",
        "prompt": (
            "请写一段800字左右的茶馆对话场景。三个角色讨论一份藏宝图的真伪，"
            "要求每个角色的说话风格截然不同。\n\n"
            "【角色设定】\n"
            "陈风（男，20岁）：沉稳冷静，经历过很多生死磨难。"
            "说话简洁有力，从不多说废话。偶尔冒出一句深沉的感慨。"
            "他不会用感叹号，语气总是平静的。"
            "典型台词风格：「这份图，有问题。」——短、直、不留余地。\n\n"
            "林小月（女，18岁）：活泼开朗，话多且快。"
            "爱用感叹号和问号，思维跳跃，经常跑题。"
            "喜欢吐槽和自言自语，偶尔会蹦出奇怪的想法。"
            "典型台词风格：「哇哇哇你们快看这个！不对等等我想想……"
            "啊不管了先吃再说！」\n\n"
            "老赵（男，55岁）：老江湖，城府极深。"
            "说话永远客气，但话里有话。喜欢用比喻和典故，"
            "表面是在闲聊，实际每句话都在试探。"
            "典型台词风格：「年轻人啊，这世上的宝贝，"
            "哪有白捡的？老朽活了半辈子，只信一个道理——"
            "越是送上门的好事，越要多留个心眼呐。」\n\n"
            "【场景】\n"
            "地点：青云城「醉仙楼」二楼雅间\n"
            "桌上摊着一份泛黄的羊皮藏宝图\n"
            "三人在此碰面，讨论图的真伪\n\n"
            "【要求】\n"
            "1. 三个角色的台词风格必须有明显区分\n"
            "2. 对话自然推进，不是轮流发言\n"
            "3. 通过对话暗示三人各自的立场和目的\n"
            "4. 注意对话节奏：紧张→缓和→再紧张"
        ),
    },
    3: {
        "name": "风格控制",
        "id": "test3",
        "prompt": (
            "同一个擂台比武场景，请分别用三种截然不同的风格各写一段"
            "（每段400字左右，总共约1200字）。"
            "三种风格之间用分隔线隔开。\n\n"
            "【场景设定】\n"
            "地点：天武宗年度大比的擂台\n"
            "人物：陈风 vs 赵天行\n"
            "背景：赵天行是夺冠热门，陈风是无名小卒\n\n"
            "━━━━━━━━━━━━━━━━\n"
            "【风格一：热血燃烧】\n"
            "要燃烧、要澎湃、要让人看得热血沸腾！\n"
            "陈风被打得遍体鳞伤但永不言弃，在绝境中爆发出惊人力量。\n"
            "使用大量短句、感叹号、力量感词汇。\n"
            "比喻要宏大：燃烧的火焰、咆哮的巨龙、冲破天际的光芒。\n"
            "节奏要快，像一首激昂的战歌。\n"
            "关键句风格：「我不会倒下！只要还有一口气——我就要站着！」\n\n"
            "━━━━━━━━━━━━━━━━\n"
            "【风格二：搞笑无厘头】\n"
            "同样的擂台场景，但陈风是个怕疼的逗比。\n"
            "他用各种奇葩手段糊弄对手：嘴遁、装死、偷袭、拖延时间。\n"
            "要搞笑、要无厘头、要让读者笑出声。\n"
            "可以打破第四面墙，加入现代梗和吐槽。\n"
            "关键句风格：「不是，你说打就打也太不讲武德了吧？"
            "要不咱们石头剪刀布？公平公正！」\n\n"
            "━━━━━━━━━━━━━━━━\n"
            "【风格三：暗黑压抑】\n"
            "同样的擂台场景，但氛围阴暗冰冷。\n"
            "陈风不是热血少年，而是一个冷酷的猎手。"
            "他不急于进攻，而是耐心观察对手的每一个动作、每一个破绽。\n"
            "描写要冰冷、残忍、有画面感。血腥细节不用回避。\n"
            "色调偏冷：灰色的天、冰冷的雨、金属的光泽。\n"
            "关键句风格：「……你已经死了，只是你的身体还没意识到。」\n\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "【要求】\n"
            "1. 三种风格的差异必须极其明显\n"
            "2. 同一个场景，但读起来像三个不同作者写的\n"
            "3. 每种风格都要贯彻到底，不能串味"
        ),
    },
    4: {
        "name": "扩写能力",
        "id": "test4",
        "prompt": (
            "请将下面500字的梗概扩写为2000字左右的完整章节。\n\n"
            "在保持原有剧情走向的基础上，补充：场景描写、心理活动、"
            "动作细节、环境氛围、情感变化、五感体验。\n\n"
            "━━━━ 以下为梗概 ━━━━\n\n"
            "陈风站在悬崖边，身后是追杀了他三天三夜的黑衣人。\n"
            "悬崖下是万丈深渊，云雾缭绕看不到底。\n\n"
            "黑衣人首领冷笑道：「交出混沌玉简，饶你不死。」\n\n"
            "陈风看了看手中的玉简，这是他在废墟中用命换来的东西，"
            "里面记载着改变命运的秘密。他回头看了一眼悬崖，深不见底。"
            "又看了一眼黑衣人，至少二十个，全是筑基期以上。\n"
            "跑不了了。\n\n"
            "陈风深吸一口气，嘴角却勾起一丝笑意。\n"
            "「想要？那就来拿。」\n\n"
            "说完，他纵身跃下悬崖。\n"
            "黑衣人们面面相觑，首领脸色铁青。\n\n"
            "悬崖下，狂风呼啸。陈风在自由落体中紧握玉简。"
            "突然，玉简发出一道柔和的光芒，一股温暖的力量包裹住了他。"
            "他的下坠速度开始减缓……\n\n"
            "━━━━ 梗概结束 ━━━━\n\n"
            "【扩写要求】\n"
            "1. 扩写要自然流畅，不能生硬堆砌\n"
            "2. 补充悬崖边的环境描写：风声、温度、光线\n"
            "3. 补充陈风的心理活动：回忆、挣扎、决断\n"
            "4. 补充黑衣人的描写：装备、站位、杀意\n"
            "5. 跳崖后的感官描写要细腻：失重感、风的触感、恐惧与平静\n"
            "6. 保持原梗概的节奏和悬念感\n"
            "7. 字数达到2000字左右"
        ),
    },
    5: {
        "name": "前文一致性",
        "id": "test5",
        "prompt": (
            "请根据以下前文设定，续写1500字左右的章节。\n"
            "续写必须严格遵守前文设定，不得出现任何矛盾。\n\n"
            "━━━━ 前文设定（不可违反） ━━━━\n\n"
            "【世界观】\n"
            "天玄大陆，修炼体系：炼气→筑基→金丹→元婴→化神。\n"
            "当前时间线：第42章。\n\n"
            "【角色状态】\n"
            "陈风：筑基初期修为。性格沉稳，话少，但内心情感丰富。\n"
            "林小月：炼气九层修为。性格活泼，话多，但关键时刻靠得住。\n\n"
            "【关键设定 — 老赵已死】\n"
            "老赵（赵德海）已在第37章「血月之夜」中死亡。\n"
            "死因：为掩护陈风撤退，被暗影门长老一掌击中心脉，当场身亡。\n"
            "陈风亲眼目睹了老赵的死亡，并将老赵的遗物——"
            "一枚刻有「赵」字的铜钱——贴身收好。\n"
            "老赵的死是陈风心中最大的痛，他对此怀有深深的愧疚和自责。\n"
            "老赵绝不可能复活、不可能以任何活人的方式出现。\n"
            "老赵只能以以下方式出现：\n"
            "  - 陈风的回忆或闪回\n"
            "  - 老赵的遗物触发的情感\n"
            "  - 其他角色提及老赵\n\n"
            "【当前剧情】\n"
            "第42章。陈风和林小月来到青云城，"
            "寻找老赵生前提到的一份秘密情报的藏匿地点。\n"
            "据老赵生前所说，情报藏在青云城醉仙楼地下的密室中。\n"
            "这份情报关系到暗影门的真正目的。\n"
            "两人到达醉仙楼附近，发现这里已经被人监视。\n\n"
            "【暗影门】\n"
            "敌对势力，组织严密，成员穿黑衣。"
            "正是暗影门杀害了老赵。\n\n"
            "【续写要求】\n"
            "1. 两人进入醉仙楼，寻找密室入口\n"
            "2. 过程中可能会遇到暗影门的追兵或陷阱\n"
            "3. 老赵已死，绝对不能让老赵「复活」"
            "或以任何活着的方式出现\n"
            "4. 陈风和林小月的修为不能突然升级\n"
            "5. 两人性格保持一致\n"
            "6. 1500字左右"
        ),
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def setup_logging() -> logging.Logger:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("model_eval_v2")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fh = logging.FileHandler(EVAL_DIR / "run.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(fh)
    return logger


def check_api_keys(registry: ModelRegistry, required_aliases: list[str]) -> bool:
    missing = []
    for alias in required_aliases:
        config_key = MODEL_MAP[alias]
        try:
            registry.get_adapter(config_key)
        except (KeyError, ValueError) as e:
            missing.append(f"{config_key}: {e}")
    if missing:
        for m in missing:
            console.print(f"[red][X] {m}[/red]")
        return False
    console.print(f"[green][OK] {len(required_aliases)} model(s) ready[/green]")
    return True


async def call_with_retry(
    registry: ModelRegistry,
    model_alias: str,
    prompt: str,
    logger: logging.Logger,
    max_retries: int = 3,
    retry_delay: float = 5.0,
) -> tuple:
    config_key = MODEL_MAP[model_alias]
    adapter = registry.get_adapter(config_key)
    messages = [{"role": "user", "content": prompt}]

    for attempt in range(1, max_retries + 1):
        try:
            resp = await adapter.generate(messages)
            logger.info(
                f"model={config_key} attempt={attempt} | "
                f"input={resp.prompt_tokens} output={resp.completion_tokens} | "
                f"cost={resp.cost:.4f}"
            )
            return resp, None
        except Exception as e:
            logger.warning(f"model={config_key} attempt={attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                await asyncio.sleep(retry_delay)
    return None, f"failed after {max_retries} retries"


def save_result(test_id: str, model_alias: str, text: str, reasoning: str | None = None):
    suffix = FILE_SUFFIX[model_alias]
    (EVAL_DIR / f"{test_id}_{suffix}.md").write_text(text, encoding="utf-8")
    if reasoning:
        (EVAL_DIR / f"{test_id}_{suffix}_reasoning.md").write_text(reasoning, encoding="utf-8")


def log_cost(writer, test_id: str, model_alias: str, resp, error: str | None):
    config_key = MODEL_MAP[model_alias]
    provider = PROVIDER[model_alias]
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if error:
        writer.writerow([ts, test_id, config_key, provider, 0, 0, 0, "failed"])
    else:
        reasoning_tokens = 0
        if resp.raw:
            details = resp.raw.get("usage", {}).get("completion_tokens_details", {})
            reasoning_tokens = details.get("reasoning_tokens", 0)
        writer.writerow([
            ts, test_id, config_key, provider,
            resp.prompt_tokens,
            resp.completion_tokens,
            reasoning_tokens,
            f"{resp.cost:.4f}",
        ])


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

async def run_single_test(
    test_id: int,
    models: list[str],
    registry: ModelRegistry,
    cost_writer,
    logger: logging.Logger,
    dry_run: bool,
) -> list[dict]:
    test = TESTS[test_id]
    results = []

    for idx, model_alias in enumerate(models):
        config_key = MODEL_MAP[model_alias]
        label = f"Test{test_id} [{test['name']}] -> {config_key}"

        if dry_run:
            console.print(f"  [dim][DRY-RUN] {label}[/dim]")
            results.append({"test": test_id, "model": model_alias, "status": "dry_run"})
            continue

        start = time.time()
        console.print(f"  >> {label}")
        resp, error = await call_with_retry(registry, model_alias, test["prompt"], logger)
        elapsed = time.time() - start

        if error:
            console.print(f"  [red][X] {label} -- {error} ({elapsed:.1f}s)[/red]")
            log_cost(cost_writer, test["id"], model_alias, None, error)
            results.append({
                "test": test_id, "model": model_alias, "status": "failed",
                "error": error, "time": elapsed,
            })
        else:
            save_result(test["id"], model_alias, resp.text, resp.reasoning_content)
            log_cost(cost_writer, test["id"], model_alias, resp, None)

            tok = f"{resp.prompt_tokens}+{resp.completion_tokens}"
            extra = f" | reasoning: {len(resp.reasoning_content)} chars" if resp.reasoning_content else ""
            console.print(
                f"  [green][OK] {label}[/green] "
                f"[dim]({elapsed:.1f}s | tokens: {tok} | cost={resp.cost:.4f}CNY{extra})[/dim]"
            )
            results.append({
                "test": test_id, "model": model_alias, "status": "ok",
                "tokens": resp.completion_tokens, "cost": resp.cost, "time": elapsed,
                "reasoning_len": len(resp.reasoning_content) if resp.reasoning_content else 0,
            })

        if not dry_run and idx < len(models) - 1:
            await asyncio.sleep(2)

    return results


def print_summary(all_results: list[dict], elapsed_total: float, dry_run: bool):
    """Print per-model comparison table."""
    if dry_run or not all_results:
        return

    ok = [r for r in all_results if r["status"] == "ok"]
    failed = [r for r in all_results if r["status"] == "failed"]

    # Per-model aggregation
    model_stats: dict[str, dict] = {}
    for r in ok:
        m = r["model"]
        if m not in model_stats:
            model_stats[m] = {"calls": 0, "time": 0.0, "cost": 0.0}
        model_stats[m]["calls"] += 1
        model_stats[m]["time"] += r.get("time", 0)
        model_stats[m]["cost"] += r.get("cost", 0)

    table = Table(title="Per-Model Comparison")
    table.add_column("Model", style="cyan")
    table.add_column("Calls", justify="right")
    table.add_column("Total Time", justify="right", style="green")
    table.add_column("Total Cost", justify="right", style="yellow")
    table.add_column("Avg Time/Call", justify="right")

    for alias in ["glm", "deepseek_v3", "kimi", "doubao", "deepseek_r1"]:
        s = model_stats.get(alias)
        if s:
            avg_time = s["time"] / s["calls"] if s["calls"] else 0
            table.add_row(
                MODEL_MAP[alias],
                str(s["calls"]),
                f"{s['time']:.1f}s",
                f"{s['cost']:.4f} CNY",
                f"{avg_time:.1f}s",
            )

    console.print(table)

    # Find fastest and cheapest
    if model_stats:
        fastest = min(model_stats, key=lambda k: model_stats[k]["time"] / max(model_stats[k]["calls"], 1))
        cheapest = min(model_stats, key=lambda k: model_stats[k]["cost"])
        console.print(f"\nFastest: [green]{MODEL_MAP[fastest]}[/green] | Cheapest: [yellow]{MODEL_MAP[cheapest]}[/yellow]")

    total_cost = sum(s["cost"] for s in model_stats.values())
    console.print(f"\nTotal time: [bold]{elapsed_total:.1f}s[/bold]")
    console.print(f"Success: [green]{len(ok)}[/green] | Failed: [red]{len(failed)}[/red]")
    console.print(f"Total cost: [bold yellow]{total_cost:.4f} CNY[/bold yellow]")


async def run_eval(
    test_ids: list[int],
    model_filter: str | None,
    registry: ModelRegistry,
    dry_run: bool = False,
):
    logger = setup_logging()
    logger.info(f"v2 eval start: tests={test_ids}, model_filter={model_filter}, dry_run={dry_run}")

    EVAL_DIR.mkdir(parents=True, exist_ok=True)

    cost_path = EVAL_DIR / "cost_log.csv"
    is_new = not cost_path.exists()
    cost_file = open(cost_path, "a", encoding="utf-8", newline="")
    cost_writer = csv.writer(cost_file)
    if is_new:
        cost_writer.writerow([
            "timestamp", "test_id", "model", "provider",
            "input_tokens", "output_tokens", "reasoning_tokens", "cost_cny",
        ])

    all_results: list[dict] = []
    total_start = time.time()

    try:
        console.print(Panel(
            "[bold]T-0.3.5 Five-Model Quality Eval (v2)[/bold]\n"
            f"Tests: {test_ids}  Filter: {model_filter or 'all'}  Mode: {'DRY-RUN' if dry_run else 'live'}",
            border_style="blue",
        ))

        # Determine which aliases we need to check
        needed_aliases = set()
        for tid in test_ids:
            models = TEST_MATRIX.get(tid, [])
            if model_filter:
                models = [m for m in models if m == model_filter]
            needed_aliases.update(models)

        if not dry_run and needed_aliases:
            if not check_api_keys(registry, sorted(needed_aliases)):
                console.print("[red]API Key check failed. Please configure config/models.yaml[/red]")
                return

        if dry_run:
            console.print("[yellow]DRY-RUN -- printing plan only[/yellow]\n")

        for test_id in test_ids:
            models = TEST_MATRIX[test_id]
            if model_filter:
                models = [m for m in models if m == model_filter]
                if not models:
                    console.print(f"  [dim]Test{test_id}: model {model_filter} not in matrix, skip[/dim]")
                    continue

            console.rule(f"[bold cyan]Test{test_id} -- {TESTS[test_id]['name']}[/bold cyan]")
            results = await run_single_test(test_id, models, registry, cost_writer, logger, dry_run)
            all_results.extend(results)
            console.print("")

        elapsed_total = time.time() - total_start
        console.rule("[bold green]Eval Complete[/bold green]\n")
        print_summary(all_results, elapsed_total, dry_run)

        if dry_run:
            total_calls = sum(
                len([m for m in TEST_MATRIX[t] if not model_filter or m == model_filter])
                for t in test_ids
            )
            console.print(f"\nPlanned API calls: [bold]{total_calls}[/bold]")
            console.print(f"Output dir: [dim]{EVAL_DIR}[/dim]")

        logger.info(f"v2 eval done: {elapsed_total:.1f}s | results={len(all_results)}")

    finally:
        cost_file.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="T-0.3.5 Five-Model Quality Eval (v2)")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    parser.add_argument("--test", type=int, choices=[1, 2, 3, 4, 5], help="Run specific test")
    parser.add_argument("--model", type=str,
                        choices=["glm", "deepseek_v3", "deepseek_r1", "kimi", "doubao"],
                        help="Run specific model only")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without calling APIs")
    args = parser.parse_args()

    if not any([args.all, args.test is not None, args.model, args.dry_run]):
        parser.print_help()
        sys.exit(1)

    return args


def main():
    args = parse_args()
    registry = ModelRegistry(CONFIG_PATH)

    if args.test is not None:
        test_ids = [args.test]
    else:
        test_ids = [1, 2, 3, 4, 5]

    model_filter = args.model
    dry_run = args.dry_run

    asyncio.run(run_eval(test_ids, model_filter, registry, dry_run))


if __name__ == "__main__":
    main()
