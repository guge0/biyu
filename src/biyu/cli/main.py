import sys

import typer
from rich.console import Console
from rich.panel import Panel

app = typer.Typer(invoke_without_command=True, help="笔驭 BiYu — 专为中文网文连载设计的AI创作伙伴")

# R3-1：动作逻辑只在 CLI 家，工作台仅注册按钮并 spawn 子进程。
from biyu.cli.planning_cmd import planning_app
from biyu.cli.verdict_cmd import verdict_app
from biyu.cli.talk_cmd import talk
from biyu.cli.workbench_cmd import workbench_app
from biyu.cli.settings_bridge import settings_write_app

app.add_typer(planning_app, name="planning")
app.add_typer(verdict_app, name="verdict")
app.command()(talk)
app.add_typer(workbench_app, name="workbench")
app.add_typer(settings_write_app, name="settings-write")


@app.callback()
def callback():
    """笔驭 BiYu CLI"""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


@app.command()
def hello():
    """查看欢迎信息"""
    panel = Panel(
        "笔驭 BiYu v0.1.0\n"
        "专为中文网文连载设计的AI创作伙伴\n"
        "使用 biyu --help 查看所有命令",
        title="欢迎",
        border_style="cyan",
    )
    console = Console()
    console.print(panel)


@app.command()
def init(
    title: str = typer.Option(..., "--title", "-t", help="书名"),
    genre: str = typer.Option(..., "--genre", "-g", help="题材 (xuanhuan/dushi/kehuan)"),
):
    """初始化一本新书。"""
    from biyu.cli.init_cmd import init_command
    init_command(title=title, genre=genre)


@app.command()
def write(
    chapter: int = typer.Option(..., "--chapter", "-c", help="章节号"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
    planner: str = typer.Option(None, "--planner", help="规划阶段模型别名(覆盖yaml)"),
    writer: str = typer.Option(None, "--writer", help="写作阶段模型别名(覆盖yaml)"),
    polisher: str = typer.Option(None, "--polisher", help="润色阶段模型别名(覆盖yaml)"),
    prompt_version: str = typer.Option("v4", "--prompt-version", help="v3=旧 prompt,v4=新三层 prompt"),
    replan: bool = typer.Option(False, "--replan", help="无视已有规划件,强制走内置 Architect 重出"),
    force_pending: bool = typer.Option(False, "--force-pending", hidden=True),
):
    """生成一章小说。可通过 --planner/--writer/--polisher 临时覆盖模型。"""
    from biyu.cli.write_cmd import write_command
    write_command(
        chapter=chapter,
        book=book,
        planner=planner,
        writer=writer,
        polisher=polisher,
        prompt_version=prompt_version,
        replan=replan,
        force_pending=force_pending,
    )


@app.command()
def check(
    chapter: int = typer.Option(..., "--chapter", "-c", help="章节号"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
):
    """检查章节一致性。"""
    from biyu.cli.check_cmd import check_command
    check_command(chapter=chapter, book=book)


@app.command()
def cost(
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
):
    """显示成本汇总。"""
    from biyu.cli.cost_cmd import cost_command
    cost_command(book=book)


@app.command()
def auto(
    book: str = typer.Option(..., "--book", "-b", help="书名"),
    from_ch: int = typer.Option(..., "--from", help="起始章节号"),
    to_ch: int = typer.Option(..., "--to", help="结束章节号(含)"),
    warning: float = typer.Option(12.0, "--warning", help="累计成本报警线(元)"),
):
    """全自动批量生成章节。"""
    from biyu.cli.auto_cmd import auto_command
    auto_command(book=book, from_ch=from_ch, to_ch=to_ch, warning=warning)


@app.command()
def refresh(
    chapter: int = typer.Option(None, "--chapter", "-c", help="单章刷新"),
    from_ch: int = typer.Option(None, "--from", help="起始章节(范围刷新)"),
    to_ch: int = typer.Option(None, "--to", help="结束章节(范围刷新)"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
):
    """重跑 Observer 刷新设定文件。"""
    from biyu.cli.refresh_cmd import refresh_command
    refresh_command(chapter=chapter, from_ch=from_ch, to_ch=to_ch, book=book)


@app.command(name="rebuild-memory")
def rebuild_memory(
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="确认产生真实 LLM 费用"),
):
    """从正式正文全量重算长期记忆，并输出 diff。"""
    from biyu.cli.refresh_cmd import rebuild_memory_command
    rebuild_memory_command(book=book, yes=yes)


@app.command()
def rollback(
    to_chapter: int = typer.Option(..., "--to-chapter", "-t", help="回退到的目标章节号"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
):
    """回退 truth_files 到指定章节的历史状态。"""
    from biyu.cli.refresh_cmd import rollback_command
    rollback_command(to_chapter=to_chapter, book=book)


@app.command()
def serve(
    port: int = typer.Option(8080, "--port", "-p", help="监听端口"),
):
    """启动笔驭 Web UI。"""
    from biyu.cli.serve_cmd import serve_command
    serve_command(port=port)


# ---------------------------------------------------------------------------
# T-P3-C P0: 回流闭环命令集（8 个）
# ---------------------------------------------------------------------------

@app.command()
def status(
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
):
    """查看项目当前状态：已签章节、待处理、最近修改、成本。"""
    from biyu.cli.status_cmd import status_command
    status_command(book=book)


@app.command()
def review(
    chapter: int = typer.Argument(..., help="章节号"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
):
    """查看章节审稿信息：audit report + 评分 + 修改历史。"""
    from biyu.cli.review_cmd import review_command
    review_command(chapter=chapter, book=book)


@app.command()
def accept(
    chapter: int = typer.Argument(..., help="章节号"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
    message: str = typer.Option("", "--message", "-m", help="修改说明"),
):
    """老板手改完后接受章节：_pending/ → chapters/ + git commit。"""
    from biyu.cli.accept_cmd import accept_command
    accept_command(chapter=chapter, book=book, message=message)


@app.command()
def approve(
    chapter: int = typer.Argument(..., help="章节号"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
):
    """老板看了不改放过：_pending/ → chapters/ + git commit。"""
    from biyu.cli.approve_cmd import approve_command
    approve_command(chapter=chapter, book=book)


@app.command(name="rewrite")
def rewrite_cmd(
    chapter: int = typer.Argument(..., help="章节号"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
):
    """重生成章节（提示运行 biyu write）。"""
    from biyu.cli.rewrite_cmd import rewrite_command
    rewrite_command(chapter=chapter, book=book)


@app.command(name="ch-rollback")
def ch_rollback_cmd(
    chapter: int = typer.Argument(..., help="章节号"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
    target_hash: str = typer.Option(None, "--to", "-t", help="目标 commit hash"),
):
    """回滚章节到上一个 git 版本（或指定版本）。"""
    from biyu.cli.rollback_cmd import rollback_ch_command
    rollback_ch_command(chapter=chapter, book=book, target_hash=target_hash)


@app.command(name="rollback-full")
def rollback_full_cmd(
    to_chapter: int = typer.Option(..., "--to-chapter", "-t", help="整退到的目标章节号"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
):
    """整退:章文件 + truth_files 一次退到第 N 章后状态。"""
    from biyu.cli.refresh_cmd import rollback_full_command
    rollback_full_command(to_chapter=to_chapter, book=book)


@app.command()
def diff(
    chapter: int = typer.Argument(..., help="章节号"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
    from_ref: str = typer.Option(None, "--from", help="起始 commit hash"),
    to_ref: str = typer.Option(None, "--to", help="结束 commit hash"),
):
    """查看章节修改历史（git diff）。"""
    from biyu.cli.diff_cmd import diff_command
    diff_command(chapter=chapter, book=book, from_ref=from_ref, to_ref=to_ref)


@app.command()
def history(
    chapter: int = typer.Argument(..., help="章节号"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
):
    """查看章节完整修改时间线（生成→自动修→老板修→接受）。"""
    from biyu.cli.history_cmd import history_command
    history_command(chapter=chapter, book=book)


# ---------------------------------------------------------------------------
# T-P3-C P1 第三批: 角色管理 + ask 命令
# ---------------------------------------------------------------------------

from biyu.cli.character_cmd import character_app
app.add_typer(character_app, name="character")


@app.command()
def ask(
    question: str = typer.Argument(..., help="你的问题"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
):
    """和书对话查询。"""
    from biyu.cli.ask_cmd import ask_command
    ask_command(question=question, book=book)


# ---------------------------------------------------------------------------
# T-P3-C P2: lint / wb-impact / suggest 命令
# ---------------------------------------------------------------------------

@app.command()
def lint(
    target: str = typer.Argument(..., help="outline/sub-md 文件路径"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
):
    """扫描 outline / sub-md 工程冲突。"""
    from biyu.cli.lint_cmd import lint_command
    lint_command(target=target, book=book)


@app.command(name="wb-impact")
def wb_impact(
    worldbook_path: str = typer.Argument(..., help="worldbook.yaml 路径"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
    since: str = typer.Option(None, "--since", help="对比基准 (git ref)"),
    diff: str = typer.Option(None, "--diff", help="对比范围 (commit..commit)"),
):
    """扫描 worldbook 改动影响。"""
    from biyu.cli.wb_impact_cmd import wb_impact_command
    wb_impact_command(worldbook_path=worldbook_path, book=book, since=since, diff=diff)


@app.command()
def suggest(
    chapter: int = typer.Option(None, "--chapter", "-c", help="章节号"),
    outline: str = typer.Option(None, "--outline", help="outline 文件路径"),
    sub_md: str = typer.Option(None, "--sub-md", help="sub-md 文件路径"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
):
    """扫描 outline/sub-md 中的留白决策，逐条提供选项。"""
    from biyu.cli.suggest_cmd import suggest_command
    suggest_command(chapter=chapter, outline=outline, sub_md=sub_md, book=book)


# ---------------------------------------------------------------------------
# T-P3-D-3: revise 命令 — Editor issue 追踪 + Reviser 改写
# ---------------------------------------------------------------------------

@app.command()
def revise(
    chapter: int = typer.Option(0, "--chapter", "-c", help="章节号"),
    issue: str = typer.Option("", "--issue", "-i", help="Issue ID (如 ch27-001)"),
    apply: bool = typer.Option(False, "--apply", help="应用 Reviser 改写"),
    regen: bool = typer.Option(False, "--regen", help="重新生成建议"),
    resolve_self: bool = typer.Option(False, "--resolve-self", help="标记自行解决"),
    dismiss: bool = typer.Option(False, "--dismiss", help="忽略 issue"),
    sync: bool = typer.Option(False, "--sync", help="MD checkbox → JSON 同步"),
    reason: str = typer.Option("", "--reason", help="regen 时的补充要求"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
):
    """管理 Editor issue：应用/重生成/解决/忽略。无参数进入交互模式。"""
    from biyu.cli.revise_cmd import revise_command
    revise_command(
        chapter=chapter, issue=issue, apply=apply, regen=regen,
        resolve_self=resolve_self, dismiss=dismiss, sync=sync,
        reason=reason, book=book,
    )


# ---------------------------------------------------------------------------
# Phase5-RE1: fingerprint 声纹学习
# ---------------------------------------------------------------------------

from biyu.cli.fingerprint_cmd import fingerprint_app
app.add_typer(fingerprint_app, name="fingerprint")


# ---------------------------------------------------------------------------
# P7-1: propose 开书前立项书
# ---------------------------------------------------------------------------

@app.command()
def propose(
    idea: str = typer.Option("", "--idea", help="作者设想(题材+一句话,自由文本,可空 → 走纯市场归纳路径)"),
    name: str = typer.Option(None, "--name", help="书名或临时名(不填则从 idea 派生)"),
    platforms: str = typer.Option("qidian,fanqie", "--platforms", help="关注哪些榜单,逗号分隔"),
    model: str = typer.Option(None, "--model", help="覆盖 LLM 模型别名(默认 pipeline.writer)"),
):
    """开书前立项书(P7-2 三路径):扫榜 + 路径判断 + 套路归纳 + (条件性)红蓝海 + 创作规律。"""
    from biyu.cli.propose_cmd import propose_command
    propose_command(idea=idea, name=name, platforms=platforms, model=model)


# ---------------------------------------------------------------------------
# P8-M1: 作者工作台(立项屏)
# ---------------------------------------------------------------------------

@app.command()
def ui(
    port: int = typer.Option(8080, "--port", "-p", help="监听端口"),
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址(默认 127.0.0.1,不暴露外网)"),
):
    """启动作者工作台(立项屏)— 网页壳形态,复用 P7-2 propose 逻辑。"""
    from biyu.cli.ui_cmd import ui_command
    ui_command(port=port, host=host)


# ---------------------------------------------------------------------------
# P8-M2: Editor 独立审读入口
# ---------------------------------------------------------------------------

@app.command(name="review-standalone")
def review_standalone(
    chapter: int = typer.Option(..., "--chapter", "-c", help="章节号"),
    book: str = typer.Option(None, "--book", "-b", help="书名(省略则自动检测)"),
    output: str = typer.Option(
        None, "--output", "-o",
        help="输出 Markdown 路径(默认 data/<book>/reviews/standalone/chN.md)",
    ),
    model: str = typer.Option(
        None, "--model",
        help="覆盖 LLM 模型别名(默认 pipeline.writer 配的别名)",
    ),
    print_md: bool = typer.Option(
        False, "--print-md",
        help="额外把 Markdown 全文打到 stdout(默认只保存文件)",
    ),
    no_save: bool = typer.Option(
        False, "--no-save",
        help="不保存文件,只返回结果(配合 --print-md 用)",
    ),
):
    """对指定章独立跑 Editor 审读,产出问题卡 Markdown(P8-M2 T3)。"""
    from biyu.cli.review_standalone_cmd import review_standalone_command
    review_standalone_command(
        chapter=chapter, book=book, output=output,
        model=model, print_md=print_md, no_save=no_save,
    )
