# biyu lint 使用说明

## 概述

`biyu lint` 是笔驭的 outline / sub-md 工程冲突扫描工具。在 `biyu write` 启动前自动扫描 outline，发现潜在的角色缺失、视觉符号撞色、forbidden 违规、伏笔遗漏等问题。

**核心原则**：lint 只报告，不修复。修复是人工/TL/代码的下一步动作。

## 用法

```bash
# 扫单个 outline
biyu lint outlines/ch28.md

# 扫 sub-md（评审产出）
biyu lint outlines/sub_md_ch28-30.md

# 指定书名
biyu lint outlines/ch28.md --book 张今空_T-P3-A验证
```

## 检测项（8 项）

| # | 检测项 | 规则文件 | 说明 |
|---|--------|----------|------|
| 1 | 在场角色清单提取 | `character_check.py` | 从 frontmatter `present_characters` 字段提取 |
| 2 | 与 characters.yaml 比对 | `character_check.py` | 标记新角色：必补 / 可豁免 / Phase 5 推迟 |
| 3 | NPC 比对 | `character_check.py` | 原 worldbook NPC 豁免 |
| 4 | 视觉符号撞色 | `symbol_collision.py` | 从 worldbook.visual_symbols 读取 |
| 5 | forbidden 条款 | `forbidden_check.py` | D-24 豁免检测 + 破折号密度 |
| 6 | 伏笔追踪 | `hook_tracking.py` | 与 pending_hooks.md 对账 |
| 7 | 字数密度估算 | `character_check.py` | 事件数 × 800 字 |
| 8 | 引用校验 | `worldbook_check.py` | outline 引用的设定是否在 worldbook 存在 |

## 输出格式

```
[biyu lint] 扫描 ch20.md
==================================================
⚠️ 视觉符号撞色: '金色光晕'在 outline 中出现，但已分配给外部观察者（CH12-15）
   建议: 建议改用其他颜色/描述
❌ 引用校验: outline 提到'时空断裂'，但 worldbook/characters 中未找到
✅ 字数密度估算: 5200 字（目标 ≥3500）
==================================================
扫描完成: 1 ℹ️  1 ⚠️  1 ❌
```

## 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 全部通过（可能有 info） |
| 1 | 有 warning |
| 2 | 有 error |

## worldbook 配置

### visual_symbols（可选）

在 `worldbook.yaml` 中添加视觉符号注册表：

```yaml
visual_symbols:
  - symbol: "金色光晕"
    assigned_to: "外部观察者"
    chapters: "CH12-15"
  - symbol: "青铜色"
    assigned_to: "命甲"
    chapters: "CH3+"
```

### pending_hooks

伏笔数据从 `truth_files/pending_hooks.md` 解析，格式为 markdown 表格：

```markdown
| hook_id | 起始章节 | 类型 | 状态 | 最近推进 | 预期回收 | 备注 |
|---------|---------|------|------|---------|---------|------|
| hook_01 | 1 | 设定伏笔 | closed | 已回收 | CH10 | ... |
| hook_02 | 5 | 角色伏笔 | open | 无 | CH20 | ... |
```

## 实测样例

### ch20（回家）

```
biyu lint outlines/ch20.md
==================================================
⚠️ [forbidden_check] 破折号密度过高: 12 个/千字 ≈ 9.5 个/千字（限制 ≤3 个/千字）
   建议: 用句号+短句替代破折号，或独立成段
==================================================
扫描完成: 0 ℹ️  1 ⚠️  0 ❌
```

说明：ch20 outline 是给人看的格式，破折号使用较自由。实际写作时由 auditor 检查正文。

### ch16（国际线开始）

```
biyu lint outlines/ch16.md
==================================================
ℹ️ [forbidden_check] D-24 白色空间结算豁免相关情节，涉及: 意识。worldbook 已有豁免条款
⚠️ [forbidden_check] 破折号密度过高: 10 个/千字 ≈ 9.4 个/千字
==================================================
扫描完成: 1 ℹ️  1 ⚠️  0 ❌
```

## 限制

- 纯规则扫描，不依赖 LLM 调用（成本 ¥0）
- 引用校验基于关键词匹配，可能存在误报/漏报
- 字数密度为粗估（事件数 × 800），实际字数取决于写作展开程度
- 伏笔追踪依赖 pending_hooks.md 的表格格式
