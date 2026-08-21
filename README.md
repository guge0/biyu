# 笔驭 BiYu

笔驭是面向中文网文连载的本地 AI 创作工作台。它把书籍、设定、章节、声纹、责编讨论和生成流程放在同一个浏览器界面中；书稿保存在你的电脑上，不上传到源码仓库。

![书架](docs/images/shelf.png)

![书籍页](docs/images/book.png)

## 主要功能

- 管理书籍、章节、世界观和人物卡
- 按细纲生成或续写章节
- 检查前后文一致性、节奏、钩子和人物状态
- 管理声纹样本与本书好句
- 在 Claude Code 中打开本书责编，读取已保存的设定并继续讨论
- 本地保存 API Key、成本记录和书稿版本

## Windows 安装

### 前置条件

1. [Git for Windows](https://git-scm.com/download/win)
2. Python 3.12，并在安装时勾选 **Add Python to PATH**
3. 能读取本仓库的 GitHub 账号

责编功能还需要 [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview)。先安装 Node.js，再执行：

```powershell
npm install -g @anthropic-ai/claude-code
claude
```

首次运行 `claude` 时按提示登录。没有安装 Claude Code 时，书架、设定、章节生成等网页功能仍可使用，但“打开责编”不可用。

### 安装笔驭

在 PowerShell 中进入准备存放程序的目录，然后执行：

```powershell
git clone https://github.com/guge0/biyu.git
Set-Location biyu
.\安装笔驭.bat
```

安装器会在仓库内创建独立的 `.venv` 并安装运行依赖。首次安装需要联网。

## 使用

双击仓库根目录的 `start_biyu_ui.bat`。这是唯一的用户启动入口：

- 固定打开 `http://127.0.0.1:8080`
- 服务就绪后自动打开浏览器
- 如果 Biyu 已经在运行，重复双击会自动重启到当前代码并打开新页面；只有端口被其他程序占用时才会显示 PID 并停止，不会悄悄换端口
- 代码或依赖变化时刷新本地运行包

默认书稿目录是：

```text
%USERPROFILE%\BiyuData
```

启动器会在首次使用时创建该目录。需要放到其他磁盘时，在启动前设置 `BIYU_DATA_ROOT`，例如：

```powershell
[Environment]::SetEnvironmentVariable('BIYU_DATA_ROOT', 'D:\MyBiyuBooks', 'User')
```

重新打开终端或重新登录 Windows 后生效。不要把书稿目录放进源码仓库。

首次打开书架后，通过“换 Key / 换模型”选择模型并输入服务商 API Key，再点击“保存并校验连接”。Key 优先保存在 Windows 系统钥匙串；系统钥匙串不可用时保存到用户目录中的本地加密文件，不写入 Git。

## 模型配置

内置示例包含 DeepSeek、Kimi（Moonshot）、GLM、豆包的配置入口。API Key 通过网页安全存储，不要写入 `config/models.yaml`。

要增加模型，可以从 `config/models.yaml.example` 复制出被 Git 忽略的 `config/models.yaml`，再填写 provider、模型 ID 和 API 地址。豆包还需要通过 `DOUBAO_ENDPOINT_ID` 提供自己的推理接入点 endpoint ID。接入第五家供应商时，现有适配层不支持的还需新增 adapter 并在模型注册表登记，不能只改下拉配置。

## 更新

关闭笔驭后，在仓库目录执行：

```powershell
git pull --ff-only
.\安装笔驭.bat
```

然后继续双击 `start_biyu_ui.bat`。书稿目录和源码目录彼此独立，更新代码不会覆盖书稿。

## 备份

自动备份默认关闭。在书架点击备份状态，或点击右上角“备份”，即可选择备份位置、打开自动备份或立即备份一次。打开后每次启动笔驭会备份一次，并在 Windows 可用时每天凌晨 3:15 备份；错过会在之后补备。

备份只复制有效书目录和根级成本记录，不复制源码、报告或测试输出。保留最近 7 个备份日，并从更早记录中每周留一份，共 4 周。失败原因、上次成功时间、实际备份本数和位置会显示在备份面板。

备份用于防止同机误删和软件损坏，不能替代异机或离线备份。

## 开发与测试

开发者仍使用同一套源码，不存在另一套“测试版产品”。开发进程通过环境变量绑定独立数据目录：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

$env:BIYU_ENV = 'test'
$env:BIYU_RUNTIME_ROLE = 'test'
$env:BIYU_DATA_ROOT = 'C:\temp\BiyuTestData'
$env:BIYU_TEST_DATA_ROOT = $env:BIYU_DATA_ROOT
.\.venv\Scripts\python.exe -m uvicorn biyu.ui.app:app --host 127.0.0.1 --port 8090
```

运行自动化测试：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

测试通过并合入 `main` 的代码才进入发布链。部署实例应从 GitHub 拉取已接受的提交，不应直接在部署目录修改代码。

## 项目结构

```text
.claude/skills/   Claude Code 责编与方案解释 skill
assets/           内置声纹资产
config/           模型与检查器配置
docs/             使用和开发文档
prompts/          写作、修订与检查提示词
scripts/          安装、启动、备份和维护脚本
src/biyu/         产品代码、CLI 与网页界面
tests/            自动化测试
tools/            独立校验工具
```

`.venv/`、API Key、书稿、本机编辑器配置和本地测试数据都不进入 Git。
