# 代码结构摘要(codebase-structure)

> 本文是给"新接手的开发者 / 中枢 / 老板"快速建立代码心智模型用的。只读不动的全景,具体实现细节看源码。
> 维护时机:管线阶段拆/合、主要模块搬位置、新增加密区时回填。日常小改动不需要更新本文。

---

## 1. `src/biyu/` 目录树

### 顶层模块(管线核心,直接在 `src/biyu/*.py`)

| 文件 | 一句话职责 |
|---|---|
| `pipeline.py` | **主管线**。`generate_chapter()` 编排 Architect→Writer→WordGuard→Editor→Polish→Observer 全流程 |
| `anchor_check.py` | anchor value-match 引擎(纯子串匹配,零 LLM)。被管线细纲层早闸 + Auditor 审稿层共用 |
| `truth_inject.py` | truth 注入块构建。双模式:`filter_enabled=False`(全量,基线)/ `True`(按出场实体过滤) |
| `truth_files.py` | truth_files YAML/MD 读写(角色/线索/钩子的真相文件) |
| `observer.py` | Observer 阶段:读正文 → 让 LLM 提取事实 → 更新 truth_files |
| `polish.py` | Polish 阶段:Kimi/QG 模型润色(可关闭) |
| `auto.py` | 批量自动模式:`biyu auto` 调用,循环跑多章 + 报警线 |
| `refresh.py` | `biyu refresh`/`biyu rollback`:重跑 Observer / 回退 truth_files |
| `config.py` | 配置加载(`config/*.yaml` + 环境变量) |
| `consistency.py` | 跨章一致性检查 |
| `context_retriever.py` | 上下文检索(为 Writer 拼 prev_chapter_tail 等) |
| `wordguard.py` | WordGuard 阶段:字数守护,不够则触发 writer_continuation 自续 |
| `worldbook.py` | 世界书加载/解析 |
| `suggest_engine.py` | `biyu suggest`:扫 outline/sub-md 留白决策,给选项 |
| `git_helper.py` | git 操作封装(章节接受/回滚用) |

### 子包(按职能聚合)

| 目录 | 职责 |
|---|---|
| `cli/` | **Typer CLI 入口**。`main.py` 是 root app,`*_cmd.py` 每个对应一个子命令 |
| `llm/` | LLM 适配器层。`base.py` 抽象基类,`deepseek.py`/`doubao.py`/`glm.py`/`kimi.py` 各家具体实现 |
| `editor/` | **Editor 阶段**。`editor.py` 单 agent,`multi_agent.py` 3-agent Blind Peer Review(A=网文编辑 / B=角色顾问 / C=设定审计,Phase1 独立→Phase2 反思→Phase3 合并);`merge.py` 投票合并,`auto_fix.py` 自动修复 |
| `auditor/` | **Auditor 检查器集合**(章节生成后的硬规则审计)。`base.py` 抽象基类,12 个 checker:anchor_check/character_presence/character_naming/chapter_ending/dedup/dialogue_ratio/meta_vocab/punctuation_density/style_repeat/transition/worldbook_check 等 |
| `audit_reports/` | 审稿报告序列化/反序列化。`state.py` JSON schema,`builder.py` 渲染 MD,`sync.py` MD↔JSON 同步 |
| `reviser/` | Reviser:按 Editor issue 改写正文(`biyu revise --apply`) |
| `fingerprint/` | **声纹学习**。`extractor.py` 提取,`schema.py` 数据模型,`writer.py` 用声纹写,`adapter.py` LLM 桥接,`prompts.py` prompt 模板;`evaluation/` 下 `blind_test.py`(盲测)/`multi_genre_test.py`(多题材鲁棒性) |
| `postproc/` | 后处理:`dash_fixer.py`(破折号)/`wenyan_fixer.py`(文白夹杂) |
| `grammar_check/` | 语法检查 Stage 3.7,`checker.py` + `whitelist.py` |
| `lint_rules/` | `biyu lint` 规则:outline/sub-md 工程冲突扫描(character_check/forbidden_check/hook_tracking/symbol_collision/worldbook_check) |
| `ask/` | `biyu ask`:和书对话查询(RAG 式) |
| `prompts/` | Prompt 模板代码(`chapter_writer.py` 等) |
| `web/` | FastAPI Web UI。`app.py` 入口,`routes.py` 路由,`sse.py` Server-Sent Events 流式输出 |
| `prompt/` | (空,预留) |
| `core/` `db/` `rag/` `utils/` | (目前空,预留) |

---

## 2. 写作入口点 / 怎么启动一次完整写章

### 入口点

- **CLI root**:`src/biyu/cli/main.py:app`(Typer 应用)
- **`biyu write` 命令**:`main.py:write()` → `cli/write_cmd.py:write_command()` → `pipeline.py:generate_chapter()`
- **entry point**:`pyproject.toml` 的 `[project.scripts] biyu = "biyu.cli.main:app"`,装包后生成 `.venv/Scripts/biyu.exe`

### 启动一次完整写章(烧钱,调真模型)

```bash
# 激活 .venv
source .venv/Scripts/activate

# 跑一章(书名可省,自动检测 data/ 下唯一书目录)
biyu write -c 3 -b <书名>

# 临时覆盖某阶段模型
biyu write -c 3 --planner r1 --writer v4_pro --polisher kimi

# 批量连续写多章,带成本报警线(超 12 元停)
biyu auto -b <书名> --from 28 --to 32 --warning 12.0
```

### 入口路径(代码视角)

```
biyu write -c 3
  └─ cli/main.py:write()             (Typer 声明)
     └─ cli/write_cmd.py:write_command()
        └─ pipeline.py:generate_chapter()
           ├─ Stage 1: Architect     (调 planner 模型出细纲)
           ├─ Stage 2: Writer        (调 writer 模型出 skeleton)
           │  └─ writer_continuation (字数不够时自续)
           ├─ Stage 3: WordGuard     (字数检查,触发自续)
           ├─ Stage 3.5/3.6/3.7: dash_fixer / wenyan_fixer / grammar_check
           ├─ Stage 3.8: Editor      (3-agent 审稿 + merge)
           ├─ Stage 4: Polish        (可跳过)
           └─ Stage 5: Observer      (更新 truth_files)
```

### 其他常用入口

- `biyu status` — 看项目状态(已签/待处理/成本)
- `biyu review <N>` — 看章节 audit_report
- `biyu accept <N>` — 老板手改后接受章节(_pending → chapters + git commit)
- `biyu approve <N>` — 老板不改放过(同上,无修改)
- `biyu fingerprint extract -s <源> -o <输出.json>` — 提取声纹
- `biyu serve -p 8080` — Web UI

---

## 3. 管线数据流(从输入到出稿的真实顺序)

`pipeline.py:generate_chapter()` 编排,**9 个阶段**:

| Stage | 名称 | 调用模型 | 输入 | 输出 | 失败行为 |
|---|---|---|---|---|---|
| 1 | **Architect** | planner(r1) | outline + truth 注入块 + prev_tail | 创作者细纲 markdown | 阻塞 |
| 1.5 | anchor 早闸 | (零 LLM) | 细纲 + anchors.yaml | anchor report(非阻塞) | 静默跳过 |
| 2 | **Writer** | writer(v4_pro) | 细纲 + truth 块 + 上下文 | skeleton_raw(章节正文草稿) | 阻塞 |
| 2+ | writer_continuation | writer | skeleton + 续写指令 | 补全的 skeleton | 字数不够时触发 |
| 3 | **WordGuard** | (规则) | skeleton | 字数检查报告 | 触发自续 |
| 3.5 | dash_fixer | (规则) | skeleton | 破折号后处理 | 静默 |
| 3.6 | wenyan_fixer | (规则) | skeleton | 文白夹杂后处理 | 可关闭 |
| 3.7 | grammar_check | (规则) | skeleton | 语法检查报告 | 静默 |
| 3.8 | **Editor** | editor × 3 agent | skeleton + 细纲 | issue list + merged report | warning 不阻塞 |
| 4 | **Polish** | polisher(kimi) | skeleton | polished 最终稿 | 可跳过(`polish_enabled=false`) |
| 5 | **Observer** | writer(v3,固定) | polished | 更新 truth_files(current_state.md / particle_ledger.md / pending_hooks.md / character_appearances.yaml) | warning 不阻塞 |

**数据落盘路径**(以 `data/<book>/` 为根):

```
data/<book>/
├── outlines/          # 大纲(输入)
├── sub_md/            # 创作者细纲(输入,或 Architect 产出)
├── chapters/
│   ├── ch<N>.md       # 已签章(Polish 后)
│   └── _pending/      # 待审章(等 accept/approve)
├── logs/ch<N>/
│   ├── planning.md    # Stage 1 产出
│   ├── skeleton*.md   # Stage 2/3 产出
│   ├── polished.md    # Stage 4 产出
│   ├── meta.json/md   # 本章 meta(字数/成本/延迟/阶段 latencies)
│   └── editor_*.json  # Editor 各 agent trace(P6-A1 起)
├── truth_files/
│   ├── current_state.md       # Observer 维护
│   ├── particle_ledger.md     # Observer 维护
│   ├── pending_hooks.md       # Observer 维护
│   ├── character_appearances.yaml
│   └── history/ch<N>/         # 每章 truth 快照(回滚用)
├── audit_reports/
│   ├── ch<N>.json             # Auditor JSON(规则审计)
│   ├── ch<N>.md               # Auditor MD
│   ├── ch<N>.editor.json      # Editor JSON(双层报告)
│   └── ch<N>.editor.md        # Editor MD
├── book.db / book.json        # 书目元数据
└── worldbook.yaml / characters.yaml / anchors.yaml
```

**成本记录**:`logs/cost_log.csv` 是**唯一可信成本源**,每行 `timestamp,chapter,stage,cost_cny,latency_s`。`biyu cost` 读它汇总。

---

## 4. anchor_checker 当前在哪、怎么调用

**核心引擎**:`src/biyu/anchor_check.py`(顶层模块,非子包)

**两个独立调用点**(共用引擎,职责不同):

### 调用点 A:管线细纲层早闸(Stage 1.5,非阻塞)

- 位置:`pipeline.py:447-459`(Stage 1 Architect 之后立即跑)
- 调用:`run_check_text(anchors_yaml, planning_text, chapter_id)`
- 行为:零 LLM,纯子串 value-match。`anchors.yaml` 不存在则静默跳过
- 目的:Architect 一输出细纲就检查"本章必须出现的 anchor 值"是否在细纲里;不在就报警告(但不阻塞 Writer)

### 调用点 B:Auditor 审稿层(章节生成后)

- 位置:`src/biyu/auditor/anchor_check.py`(Auditor 的一个 checker)
- 调用:`run_check_text(anchors_path, chapter_text, chapter_id)`
- 行为:跑在 Auditor 全套 checker 里,和 character_presence/dialogue_ratio 等并列
- 目的:对**最终章节正文**做 anchor 检查,结果进 `audit_reports/ch<N>.json`

### P6-A2 待办(本任务不动)

`anchor_checker` 的"早闸是否升级为阻塞 / 引擎语义扩展"属于 **P6-A2 真值审计** 任务范围,本次 SETUP-04 只观察、不改。

---

## 5. truth 真值注入当前在哪、怎么注入

**核心引擎**:`src/biyu/truth_inject.py`

**调用点**:`pipeline.py:416`(`generate_chapter()` 里,Stage 1 Architect 之前)

```python
truth_files_block = build_truth_injection_block(
    truth_md=truth_md,               # read_all_truth_files 产出 {filename: content}
    raw_characters=raw_characters,   # characters.yaml 原始 dict
    filter_text=filter_text,         # 细纲/正文,用于过滤
    filter_enabled=filter_enabled,   # 开关
)
```

### 注入模式(D-45 钉死的双模式,控制变量)

| 模式 | `filter_enabled` | 行为 | 用途 |
|---|---|---|---|
| **全量注入**(基线) | `False`(默认) | 原样拼接全部 truth_files 内容,与原 pipeline 逐字等价 | 基线可复现、A/B 对照 |
| **按出场过滤**(改造后) | `True` | 解析 YAML → 用 alias registry 识别本章出场实体 → 只注入相关真值 | 减 token、防串扰 |

### 过滤实现(A1/A3,关键词级,不做语义)

- `build_alias_registry()` 从 `characters.yaml` 收集每个角色的识别别名(name + narrator_default + called_by 的 values),**排除** `self_referent`("我"太泛)和 `forbidden_in_narrative`
- `identify_appearing_entities()` 在 filter_text 里子串匹配,定本章出场角色/地点
- `filter_truth_by_entities()` 按"出场实体"过滤 truth dict:
  - `characters` / `locations` 段:键即实体名,按 key ∈ appearing 过滤
  - `clues` / `hooks` 段:按文本字段(`name` / `desc`)含 appearing 关键词过滤

**边界(D-43 钉死)**:关键词/字符串级匹配,**不做语义检索 / 向量 / 同义归一化**。复用 `biyu.anchor_check.normalize` 处理全角→半角。

### 容错(A4-V0 Part 2)

Observer 写入的 markdown 表格等非 YAML 内容会让 `yaml.safe_load` 抛 `ScannerError`,跳过不可解析条目而非崩溃。

### P6-A2 待办(本任务不动)

truth_inject 的"过滤效果实测 / 边界扩展"属于 **P6-A2 真值审计** 任务范围。

---

## 6. 测试在哪、怎么组织

### 测试位置

- `tests/`(仓库根下,与 `src/` 平级)
- 配置:`pyproject.toml` 的 `[tool.pytest.ini_options] pythonpath = ["src"]`,测试吃本地 src 不吃装包

### 测试组织(467 tests,按职责命名)

| 命名前缀 | 内容 |
|---|---|
| `test_auditor_*.py`(11 个) | 每个 Auditor checker 一个测试文件 |
| `test_editor*.py`(5 个) | Editor 单 agent / 多 agent / schema / output contract / merge |
| `test_lint.py` + `test_lint_rules/` | lint 命令 + 各 lint rule |
| `test_fingerprint/`(子目录) | 声纹子系统的 extractor/schema/writer/sampler/blind_test/multi_genre/adapter_contract |
| `test_*_cmd.py` | CLI 命令测试(revise 等) |
| `test_pipeline.py` | 主管线编排测试 |
| `test_anchor_checker.py` / `test_truth_inject.py` | 引擎单测 |
| `test_postproc/grammar_check` 系列 | 后处理 + 语法检查 |
| `test_bugfix_tP3D33.py` / `test_p6_13a_debt_fixes.py` | 历史 bug 回归测试 |
| `test_llm_manual.py` | **手动** LLM 测试(默认 skip,需 `--manual` 触发,会烧钱) |
| `pipeline_lab.py` | 退役实验脚本；现役 `v3_opening.py` 仍引用其提示词来源，迁移来源说明前暂留 |

### 跑测试

```bash
pytest                                  # 全跑(零成本,467 tests)
pytest tests/test_pipeline.py -v        # 单文件
pytest --cov=biyu --cov-report=term-missing   # 覆盖率
pytest --manual                         # 含手动 LLM 测试(烧钱,默认 skip)
```

---

## 7. 敏感目录 / 文件(碰它要格外小心)

> 这些路径涉及 **计费调用 / Key / 真书内容**,改前停下来核权限,后续可能为它们写路径规则(IDE / git hook / pre-commit)。

### ⛔ Key 与配置

| 路径 | 风险 | 已有保护 |
|---|---|---|
| `config/models.yaml` | **含真实 API Key**(模型别名 → key/url) | `.gitignore` 已挡 + `git log --all --full-history` 核验无历史 |
| `config/*.yaml`(其他) | 含模型路由配置(无 Key 但敏感) | `.gitignore` 挡 `*.yaml`(只放行 `.example`) |
| `config/models.yaml.example` | 模板,无 Key,可公开 | 同步到镜像 |

### 💰 计费调用(改代码前先确认不会触发非预期 LLM 调用)

| 模块 | 触发 |
|---|---|
| `biyu write` / `biyu auto` | 完整管线,单章 ~¥0.07 |
| `biyu fingerprint extract` | 声纹提取,采样 8000 字 ~¥0.1 |
| `biyu fingerprint blind-test` / `multi-genre-test` | 多轮评测,~¥1-5 |
| `src/biyu/llm/` 任何适配器 | 直接调模型,改它影响所有调用 |
| `tests/test_llm_manual.py` | 默认 skip,但跑就烧钱 |

**所有 LLM 调用必须走 `biyu.llm` 层 + 记 `cost_log.csv`**,不允许在 `pipeline.py` / `editor/` / `observer.py` 等业务代码里直接 `httpx.post`。改 LLM 层要先看 `cost_log.csv` 是否还能正确记账。

### 📖 真书内容(绝不进镜像 / 公开 git / 第三方)

| 路径 | 内容 |
|---|---|
| `data/<book>/chapters/*.md` | 章节正文 |
| `data/<book>/outlines/` `sub_md/` | 大纲、细纲 |
| `data/<book>/truth_files/` | 角色/线索/钩子真相 |
| `data/<book>/logs/ch<N>/polished.md` 等 | 生成中间稿 |
| `data/<book>/worldbook.yaml` `characters.yaml` | 世界书、角色设定 |
| `data/<book>/book.db` | 书目 SQLite |
| `全景图.md`(仓库根) | 含真书决策数据 |
| `eval_set_v0/` | **例外**:公开测试集(EV1 回声巷的脱敏版),允许进镜像 |

**发布机制**：`E:\webnovel\biyu-dev` 是唯一开发 checkout；验证后 push 到 `guge0/biyu`，生产 checkout `E:\webnovel\biyu` 只从 GitHub pull。书稿数据、`config/models.yaml`、`.venv/` 与本机协作元数据不进入源码仓。

### 🔧 易碎生产代码(改前看全景图 + 写 spec)

| 路径 | 为什么易碎 |
|---|---|
| `src/biyu/pipeline.py` | 主管线,任何改动影响所有写章调用 |
| `src/biyu/editor/multi_agent.py` | 3-agent Editor 编排,改 prompts/合并逻辑影响质量 |
| `src/biyu/observer.py` | 维护 truth_files,改格式会让历史 truth 失配 |
| `src/biyu/truth_inject.py` | D-45 双模式钉死,改默认行为破坏基线 |
| `src/biyu/anchor_check.py` | D-43 钉死纯子串匹配,改引擎语义是 P6-A2 范围 |
| `src/biyu/llm/*` | 改适配器要保 cost_log 完整 |

---

## 附:开发现状速览

- **主入口**:`biyu write`(单章)/ `biyu auto`(批量)
- **测试规模**:467 tests,跑全套零成本
- **当前阶段**(2026-06-24):Phase 6 进行中,P6-A1 真值审计 / P6-人味检测 / P6-2 题材模板均收口;下一动作见全景图
- **遗留**:`ruff check src/` 当前报 24 处可自动修(非阻塞,日常不强求清零)

**详细历史/决策/踩坑** → 见仓库根 `全景图.md`(唯一事实源)。
