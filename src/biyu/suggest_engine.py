"""biyu suggest 核心引擎 — 留白识别、选项生成、决策记录。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# 留白识别
# ---------------------------------------------------------------------------

# 显式占位符正则
_PLACEHOLDER_RE = re.compile(
    r"\[TBD\]|\[待定\]|\[TODO\]|\?\?\?|<([A-Z_][A-Z0-9_]*)>",
    re.IGNORECASE,
)

# frontmatter 中常见的"空值"模式
_BLANK_VALUE_RE = re.compile(r"^\s*$")


@dataclass
class BlankDecision:
    """一条留白决策。"""

    id: str  # e.g. "suggest_001"
    prompt: str  # 人类可读的描述，如"东黎国首都名称"
    context: str  # 来源上下文，如"CH28 提到'主角降落在东黎国都城'"
    raw_text: str  # 原始匹配文本
    location: str  # 文件中的位置（行号或字段名）
    source_file: str  # 来源文件名
    options: list[str] = field(default_factory=list)  # 3 个选项文本
    suggestion: str = ""  # LLM 生成的示例值
    chosen: int | None = None  # 用户选择 (1/2/3)
    chosen_value: str = ""  # 选中后的值


def scan_file(file_path: Path) -> list[BlankDecision]:
    """扫描单个 outline/sub-md 文件，识别所有留白。

    Args:
        file_path: outline 或 sub-md 文件的路径。

    Returns:
        按出现顺序排列的 BlankDecision 列表。
    """
    if not file_path.exists():
        return []

    text = file_path.read_text(encoding="utf-8")
    decisions: list[BlankDecision] = []
    counter = 0

    # 解析 frontmatter
    frontmatter, body = _split_frontmatter(text)
    file_name = file_path.name

    # 1) 扫描 frontmatter 空值
    if frontmatter:
        fm_decisions = _scan_frontmatter_blank(frontmatter, file_name)
        for d in fm_decisions:
            counter += 1
            d.id = f"suggest_{counter:03d}"
            decisions.append(d)

    # 2) 扫描 body 中的显式占位符
    body_decisions = _scan_body_placeholders(body, file_name)
    for d in body_decisions:
        counter += 1
        d.id = f"suggest_{counter:03d}"
        decisions.append(d)

    return decisions


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """将文件内容拆分为 frontmatter dict 和 body 文本。"""
    if not text.startswith("---"):
        return {}, text

    end = text.find("---", 3)
    if end == -1:
        return {}, text

    fm_text = text[3:end].strip()
    body = text[end + 3 :].strip()

    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        fm = {}

    return fm, body


def _scan_frontmatter_blank(
    frontmatter: dict[str, Any], file_name: str
) -> list[BlankDecision]:
    """扫描 frontmatter 中值为空字符串或 null 的字段。"""
    results: list[BlankDecision] = []

    for key, value in frontmatter.items():
        # 只处理字符串值或 null
        if value is None or (isinstance(value, str) and _BLANK_VALUE_RE.match(value)):
            prompt = f"{key}（frontmatter 字段留空）"
            context = f"文件 {file_name} 的 frontmatter 中 '{key}' 字段值为空"
            results.append(
                BlankDecision(
                    id="",
                    prompt=prompt,
                    context=context,
                    raw_text="",
                    location=f"frontmatter.{key}",
                    source_file=file_name,
                )
            )

    return results


def _scan_body_placeholders(body: str, file_name: str) -> list[BlankDecision]:
    """扫描 body 中的显式占位符标记。"""
    results: list[BlankDecision] = []
    lines = body.split("\n")

    for line_num, line in enumerate(lines, 1):
        for m in _PLACEHOLDER_RE.finditer(line):
            raw = m.group(0)
            # 命名占位符 <NAME> 提取出名字
            named = m.group(1)
            if named:
                prompt = f"{named}（占位符 <{named}>）"
            else:
                prompt = f"未定内容（{raw}）"

            # 取所在行的上下文（前后各取一些）
            context_line = line.strip()
            if len(context_line) > 100:
                context_line = context_line[:100] + "..."
            context = f"文件 {file_name} 第 {line_num} 行: {context_line}"

            results.append(
                BlankDecision(
                    id="",
                    prompt=prompt,
                    context=context,
                    raw_text=raw,
                    location=f"L{line_num}",
                    source_file=file_name,
                )
            )

    return results


# ---------------------------------------------------------------------------
# 选项生成
# ---------------------------------------------------------------------------

_SUGGEST_PROMPT_TEMPLATE = """\
你是中文网文设定顾问。以下是一条需要补充的创作细节：

决策点: {prompt}
上下文: {context}
现有设定参考:
{setting_context}

请给出一个具体的示例值（一句话以内），要求：
- 符合已有的世界观和调性
- 具有网文的辨识度
- 不要过长（控制在 10 字以内为佳）

只输出示例值本身，不要解释。"""


async def generate_suggestion(
    decision: BlankDecision,
    book_dir: Path,
    adapter: Any,
) -> str:
    """为一条留白生成示例值（选项 1）。

    调用 LLM，使用 look_up_setting 获取上下文来辅助生成。

    Args:
        decision: 留白决策。
        book_dir: 书目录。
        adapter: LLMAdapter 实例。

    Returns:
        LLM 生成的示例值字符串。
    """
    from biyu.editor.tools import look_up_setting

    # 尝试从 prompt 中提取关键词查设定
    keywords = _extract_keywords(decision.prompt)
    setting_parts: list[str] = []
    for kw in keywords:
        result = look_up_setting(kw, book_dir)
        if "未找到" not in result:
            setting_parts.append(result)

    setting_context = "\n".join(setting_parts) if setting_parts else "（无相关现有设定）"

    prompt_text = _SUGGEST_PROMPT_TEMPLATE.format(
        prompt=decision.prompt,
        context=decision.context,
        setting_context=setting_context,
    )

    messages = [{"role": "user", "content": prompt_text}]
    resp = await adapter.generate(
        messages,
        temperature=0.7,
        max_tokens=128,
    )

    suggestion = (resp.text or "").strip()
    # 清理可能的多余输出
    suggestion = suggestion.split("\n")[0].strip()
    return suggestion


def _extract_keywords(text: str) -> list[str]:
    """从 prompt 中提取可能的地名/实体名作为关键词。

    简单启发式：取中文字符序列（2-4 字）作为候选。
    """
    # 找连续中文字符序列
    candidates = re.findall(r"[\u4e00-\u9fff]{2,4}", text)
    # 去掉太通用的词
    stop_words = {"未定", "内容", "占位", "字段", "留空", "待定", "名称", "名字"}
    return [c for c in candidates if c not in stop_words]


def build_options(decision: BlankDecision, suggestion: str = "") -> list[str]:
    """构建 3 个选项文本。

    Args:
        decision: 留白决策。
        suggestion: LLM 生成的示例值（可能为空表示生成失败）。

    Returns:
        长度为 3 的选项列表。
    """
    if suggestion:
        opt1 = f"示例值:{suggestion}"
    else:
        opt1 = "示例值:（生成失败，请自行输入）"
    opt2 = "auto:让 AI 在写作时自由发挥"
    opt3 = "skip:本批不定，后续再说"
    return [opt1, opt2, opt3]


# ---------------------------------------------------------------------------
# 决策记录
# ---------------------------------------------------------------------------

def record_decision(
    decision: BlankDecision,
    book_dir: Path,
) -> Path:
    """将用户的选择记录到 decisions/suggest_log.yaml。

    Args:
        decision: 已填充 chosen 和 chosen_value 的决策。
        book_dir: 书目录。

    Returns:
        写入的 log 文件路径。
    """
    decisions_dir = book_dir / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    log_path = decisions_dir / "suggest_log.yaml"

    # 读取已有记录
    existing: list[dict] = []
    if log_path.exists():
        with open(log_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if isinstance(data, list):
                existing = data

    # 构建新记录
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "decision_id": decision.id,
        "prompt": decision.prompt,
        "context": decision.context,
        "options": decision.options,
        "chosen": decision.chosen,
        "chosen_value": decision.chosen_value,
        "source_file": decision.source_file,
        "location": decision.location,
        "applied_to": None,
    }

    existing.append(record)

    with open(log_path, "w", encoding="utf-8") as f:
        yaml.dump(existing, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return log_path


# ---------------------------------------------------------------------------
# 辅助: 文件路径解析
# ---------------------------------------------------------------------------

def resolve_outline_path(
    book_dir: Path,
    chapter: int | None = None,
    outline: str | None = None,
    sub_md: str | None = None,
) -> Path | None:
    """根据参数解析出要扫描的文件路径。

    三种输入方式优先级: outline > sub_md > chapter
    """
    if outline:
        p = Path(outline)
        if p.exists():
            return p
        # 尝试相对于 book_dir
        p2 = book_dir / outline
        if p2.exists():
            return p2
        return None

    if sub_md:
        p = Path(sub_md)
        if p.exists():
            return p
        p2 = book_dir / sub_md
        if p2.exists():
            return p2
        return None

    if chapter is not None:
        outline_path = book_dir / "outlines" / f"ch{chapter}.md"
        if outline_path.exists():
            return outline_path
        return None

    return None
