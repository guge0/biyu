# biyu wb-impact 使用说明

## 概述

`biyu wb-impact` 扫描 worldbook.yaml 改动对已生成章节和 outline 的影响。**只列报告不自动改**，等老板/TL 决策。

## 用法

```bash
# 扫描当前 worldbook 与 HEAD 版本的差异
biyu wb-impact worldbook.yaml

# 指定对比基准
biyu wb-impact worldbook.yaml --since HEAD~1

# 指定对比范围
biyu wb-impact worldbook.yaml --diff abc123..def456

# 指定书名
biyu wb-impact worldbook.yaml --book 张今空_T-P3-A验证
```

## 工作原理

1. 加载新旧两个版本的 worldbook.yaml
2. 逐字段对比（facts / forbidden / geography / factions / timeline / narrative_anchors / power_system）
3. 对每条变动，提取专有名词（冒号前名称、引号内术语、3字以上中文词）
4. 在所有章节（`chapters/ch*.md`）和 outline（`outlines/ch*.md`）中搜索这些关键词
5. 输出受影响章节列表

## 输出格式

```
[biyu wb-impact] 扫描 worldbook 改动
==================================================
变动 1: facts.+
  新增: 华国与周边小国存在秘境产出归属协议...
  受影响章节: CH1, CH10, CH12, CH15, CH16... (共14章)
  建议: 新增设定，检查受影响章节是否一致

变动 2: geography.+
  新增: 东黎国：华国西南边境小国...
  受影响章节: CH16, CH17, CH18, CH20, CH21... (共10章)
  建议: 新增设定，检查受影响章节是否一致
==================================================
共 3 项变动, 涉及 14 章节
```

## 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 无变动 |
| 1 | 有变动需要审核 |

## 关键词匹配策略

为了避免通用词误匹配，采用以下策略：
- **冒号前名称**：如"东黎国："提取"东黎国"
- **引号内术语**：如『奖励变异』提取完整术语
- **3字以上专有名词**：提取连续3-6个中文字符
- **开头2-3字名称**：提取值开头的中文名（人名/地名）
- **通用词过滤**：排除"不得"、"世界"、"能力"等高频通用词

## 实测样例

### worldbook v5 → v6 变动扫描

模拟 worldbook v5（无东黎国/情绪共振体）到 v6（新增）的差异：

```
变动 1: facts.+
  新增: 华国与周边小国存在秘境产出归属协议...
  受影响章节: CH1, CH10, CH12, CH15, CH16... (共14章)

变动 2: facts.+
  新增: 情绪共振体：在白色空间中被消化的意识碎片...
  受影响章节: CH11, CH14, CH16, CH17, CH21... (共8章)

变动 3: geography.+
  新增: 东黎国：华国西南边境小国...
  受影响章节: CH16, CH17, CH18, CH20, CH21... (共10章)
```

## 限制

- 基于关键词匹配，可能存在漏报（术语被改写/同义词）
- git 历史依赖：需要 worldbook.yaml 在 git 中被追踪
- 不依赖 LLM 调用（成本 ¥0）
- 纯报告，不自动修改任何文件
