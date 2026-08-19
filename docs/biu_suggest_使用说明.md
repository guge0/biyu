# biyu suggest 使用说明

## 功能概述

`biyu suggest` 是笔驭的轻量决策面板，用于在写章节之前批量处理 outline / sub-md 中的"留白未定的小创作决策"。

典型场景：
- outline 中某地名写的是 `[TBD]`
- frontmatter 里某字段值留空（如 `首都: `）
- 占位符 `<NAME>` / `???` / `[待定]` 标记的未定内容

`biyu suggest` 扫描这些留白，为每条生成 3 个选项，老板逐条选择后记录到决策日志。

## 用法

```bash
# 按章节号扫描（查 outlines/ch{N}.md）
biyu suggest --chapter 28

# 直接指定 outline 文件
biyu suggest --outline outlines/ch28.md

# 指定 sub-md 文件
biyu suggest --sub-md outlines/sub_md_ch28-30.md

# 指定书名（多本书时需要）
biyu suggest --chapter 28 --book 张今空_T-P3-A验证
```

## 输出格式

```
[biyu suggest] 扫描 outlines/ch28.md
============================================
发现 5 条留白决策:

[1/5] 未定内容（[TBD]）
  上下文:文件 ch28.md 第 10 行: 张今空和周大龙降落在东黎国都城，但首都名称 [TBD]

  1) 示例值:东都临安
  2) auto:让 AI 在写作时自由发挥
  3) skip:本批不定，后续再说

  请选择 [1-3]: _
```

## 决策记录

选择后自动追加到 `data/<book>/decisions/suggest_log.yaml`：

```yaml
- timestamp: "2026-05-09T10:23:00"
  decision_id: suggest_001
  prompt: 未定内容（[TBD]）
  context: 文件 ch28.md 第 10 行: ...
  options:
    - 示例值:东都临安
    - auto:让 AI 在写作时自由发挥
    - skip:本批不定，后续再说
  chosen: 1
  chosen_value: 东都临安
  source_file: ch28.md
  location: L10
  applied_to: null
```

## 三个选项说明

| 选项 | 含义 | 后续行为 |
|------|------|---------|
| 1) 示例值 | LLM 基于现有设定生成的具体建议 | 记录到日志，由 TL 决定是否写入 worldbook |
| 2) auto | 放权给 AI 在写作时自由发挥 | pipeline 写作时不受约束 |
| 3) skip | 本批不定，后续再说 | 跳过，不在本批处理 |

## 支持的留白标记

| 标记类型 | 示例 | 说明 |
|---------|------|------|
| `[TBD]` | `首都名称 [TBD]` | 最常用 |
| `[待定]` | `种类 [待定]` | 中文等价 |
| `[TODO]` | `内容 [TODO]` | 通用待办 |
| `???` | `秘境名称 ???` | 三问号 |
| `<NAME>` | `<ELDER_NAME>` | 命名占位符 |
| frontmatter 空值 | `首都: ` | YAML 中值为空 |

## 技术架构

```
biyu/cli/suggest_cmd.py    CLI 入口 + 交互逻辑
biyu/suggest_engine.py     核心引擎（扫描、生成、记录）
biyu/editor/tools.py       只读复用：look_up_setting 等查询工具
```

LLM 调用使用 V4-Pro 模型，每条留白 ≤ 1 次调用，单次 `biyu suggest` 总成本 ≤ ¥0.05。

## 注意事项

- `biyu suggest` **只记录决策，不写入** outline 或 worldbook
- 是否将决策同步到 worldbook 由老板/TL 后续决定
- CLI 入口注册（在 `__main__.py` 添加 suggest 命令）留给整合阶段
