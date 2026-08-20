# 笔驭 BiYu

专为中文网文连载设计的AI创作伙伴

## 功能列表

- ✅ 命令行交互界面 (CLI)
- ✅ 章节生成与续写
- ✅ 前后文一致性检查
- ✅ 网文节奏与钩子设计
- 🚧 RAG 知识库检索
- 📋 作品管理与数据结构

## Windows 新机器安装与启动（作者使用）

前置条件：这台机器能联网，并且你的 GitHub 账号有本私有仓库的读取权限。

1. 安装 [Git for Windows](https://git-scm.com/download/win)。安装后重新打开终端。
2. 安装 Python 3.12（最低 3.10），并在安装界面勾选 **Add Python to PATH**。在继续前确认
   `python --version` 显示 `3.10` 或更高版本；Python 3.9 不受支持。若安装过 Anaconda，
   `python` 仍指向低版本，可先在仓库目录运行 `py -3.12 -m venv .venv` 建立正确环境。
3. 打开 PowerShell，进入你准备存放程序的目录，执行唯一一条安装指令：

   ```powershell
   git clone https://github.com/guge0/biyu.git; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; Set-Location biyu; .\安装笔驭.bat
   ```

   GitHub 若要求登录，按窗口提示登录有仓库权限的账号。安装脚本会建立独立的 `.venv`
   并安装依赖；首次安装需要联网下载依赖。
4. 安装窗口显示完成后，双击仓库根目录的 `start_biyu_ui.bat`。这是日常写作使用的
   **生产版**，固定使用 `http://127.0.0.1:8080`，服务就绪后自动打开。以后也只需双击这个文件；已有
   运行环境时可离线启动，不会在日常启动时自动更新仓库或重装依赖。
5. 首次打开书架，选择模型并输入该服务商的 API Key，再点“保存并校验连接”。Key 优先
   保存在 Windows 系统钥匙串；系统钥匙串不可用时自动保存到用户目录中的本地加密文件，
   不写入仓库。请勿把 Key 填入或提交 `config/models.yaml`。

### 换 Key、换模型与换供应商

- 首次向导和书架顶栏的“换 Key / 换模型”使用同一套安全存储。页面不会显示已保存的 Key，
  只能从配置中已有的模型列表选择，不能在网页里新建模型定义。
- 示例配置已提供 DeepSeek、Kimi（Moonshot）、GLM、豆包四家 adapter 与对话模型 alias，
  前三家填对应 Key 后可直接在网页选择。豆包还要求先在火山方创建推理接入点，并把自己的
  `ep-xxx` endpoint ID 通过 `DOUBAO_ENDPOINT_ID` 环境变量提供；这个 ID 无法由仓库统一预置。
- 要使用这四家中的其他模型，可从 `config/models.yaml.example` 复制出被 Git 忽略的
  `config/models.yaml`，增加 provider/model 字段后再从网页选择；Key 仍只通过网页安全存储，
  不写进 YAML。要接入第五家供应商，除配置 provider、API 地址和模型 ID 外，现有适配器不支持时
  还必须新增 adapter 并在模型注册表登记，不能只靠网页下拉完成。

生产启动器固定使用 `D:\BiyuProductionData` 作为生产数据根，首次启动必须是空目录；测试启动器
测试版继续读取仓外数据根 `E:\webnovel\BiyuTestData`。书稿数据根是作者自己的本地目录，没有远端地址，
不会被推送到程序源码仓库。需要改位置时，在启动前设置对应的 `BIYU_DATA_ROOT`。
点击“采用”会在书稿数据仓创建本地 Git 提交，因此数据根必须可写，并已配置 Git 提交身份。

### 生产版与测试版

- 日常写作只双击 `start_biyu_ui.bat`：生产版、端口 8080、数据在 `D:\BiyuProductionData`。
- 工程调试才双击 `start_biyu_ui_dev.bat`：测试版、端口 8090、数据在 `E:\webnovel\BiyuTestData`。
- 两个端口均不自动换号。若被旧进程占用，启动器会显示 PID 和命令并停止，避免把新页面接到旧后端。

### 备份与恢复

- 备份根由 `BIYU_BACKUP_ROOT` 配置（未配置时兼容默认 `D:\BiyuBackup`），生产与测试分别放在 `production`、`test` 子目录。自动备份开关 `BIYU_AUTO_BACKUP` 默认关闭；网页会明确显示“备份没开”或最近一次时间和路径。每日任务 `BiyuDailyBackup` 也默认停用，需要作者主动启用。
- 生产备份只复制数据根下含 `book.json` 的书目录和根级 `cost_log.csv`，不复制报告、压缩包、测试输出或非书目录。备份是直接可打开的目录树，不打包；保留最近 7 个日备和 4 个周备。失败会写入 `<备份根>/<scope>/backup.log` 并在网页显示。
- 恢复从回收站或备份预览后进行，默认写入临时目录，不覆盖现役书。作者确认内容无误后，再自行处理后续入库。
- 这份备份用于同机另一块盘上的误删、误改和软件损坏恢复；防不了硬盘坏、机器丢失或勒索软件。请另行准备异机或离线备份。

手动启用自动备份：在启动对应环境前设置 `BIYU_AUTO_BACKUP=1`；手动运行 `POST /api/backup/run` 仍可按需生成一次备份。恢复使用网页的备份预览与恢复入口，目标默认是临时目录，禁止覆盖现役数据根。

## 开发安装

```powershell
# 创建虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 更新构建工具，避免旧版 pip/setuptools 退回 legacy develop 并显示 UNKNOWN 元数据
python -m pip install --upgrade pip setuptools wheel

# 安装依赖（首次安装需要联网）
python -m pip install -e ".[dev]"

# 验证安装
biyu --help
biyu hello
```

## 命令行快速开始

```powershell
# 查看帮助
biyu --help

# 查看欢迎信息
biyu hello
```

## 项目结构

```
biyu/
├── .claude/skills/  # 产品随附的责编与方案解释 skill
├── assets/          # 安装时随包分发的内置声纹资产
├── config/          # 可提交的默认配置与私有配置示例；models.yaml 不进 Git
├── docs/            # 作者使用说明与开发者代码结构说明
├── eval_set_v0/     # 自动测试直接读取的固定评测夹具，不含历史模型回显
├── prompts/         # 运行时从文件加载的提示词与模板
├── scripts/         # 启动、备份、迁移和测试夹具维护脚本
├── src/biyu/        # Python 产品代码、CLI、写作管线与网页界面
├── tests/           # 自动化测试与浏览器测试
└── tools/           # 可独立运行的校验工具
```

书稿不在源码仓内：生产数据固定在 `D:\BiyuProductionData`，测试数据固定在
`E:\webnovel\BiyuTestData`。`.venv/`、API Key、本机编辑器设置和 AI 编程助手配置也都不进入 Git。

## 开发

```powershell
# 安装开发依赖
python -m pip install -e ".[dev]"

# 运行测试
pytest

# 代码检查
ruff check src/
```
