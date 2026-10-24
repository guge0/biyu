# packaging/ · 笔驭 v1.0 打包链（S-3 T1 起）

目标：Windows x64 双击安装的「笔驭 v1.0.0」= Electron 薄壳 + PyInstaller sidecar（本地 FastAPI 服务）。
本目录属 S-3 工单白名单；构建产物（build/ dist/ home-staging/ node_modules/）不入库。

## 布局

```
packaging/
  sidecar_main.py      PyInstaller 入口:按 Electron 注入的 env 原样起 uvicorn(biyu.ui.app:app)
  sidecar.spec         PyInstaller spec(onedir;collect_data_files 带 ui/static 等包内资源)
  build_sidecar.ps1    一键构建:staging home + 装 PyInstaller(如缺) + 打包 + 体积报告
  make_icon.py         纯标准库(Windows GDI)生成 朱砂印「驭」图标 → electron/icons/biyu.ico(+png)
  smoke_sidecar.py     冒烟:干净临时数据根拉起 exe → 轮询 /api/version → 量启动耗时 → 杀树
  home-staging/        (构建期生成)BIYU_PROJECT_ROOT 载荷:config(免Key件)+docs/index.html+prompts/
  electron/            薄壳:main.js(选端口/首启数据根/拉起/退出杀 sidecar)+package.json+icons/
  dist/                (构建期生成)biyu-sidecar onedir 输出
  build/               (构建期生成)PyInstaller 中间产物
```

## 关键契约(与产品既有机制零改动对接)

- sidecar 不自带策略:`BIYU_DATA_ROOT` 未设置按产品侧既有行为「refusing to start」拒启;端口必须由壳经 `BIYU_SIDECAR_PORT` 指定。
- 安装版数据根默认 `%APPDATA%\biyu-studio`(design.md 决策;首启由 Electron 建目录并写 `%USERPROFILE%\.biyu\runtime-production.json`,与数据根锁定机制对齐,不改机制本体)。
- `BIYU_PROJECT_ROOT` 指向 home 载荷目录(config/models.yaml.example、config/auditor.yaml、docs/index.html、prompts/ 等)。
- **Key 红线**:`config/models.yaml`(私人 Key 配置)永不入包;home 只带 `models.yaml.example` 等免 Key 件,首启走既有 setup 流程。
- 壳环境注入对齐 `scripts/start_biyu_ui.ps1` 语义:`BIYU_ENV=prod`、`BIYU_RUNTIME_ROLE=production`、`BIYU_DATA_ROOT`、`BIYU_DATA_ROOT_SOURCE=environment`、`BIYU_PRODUCTION_DATA_ROOT`、`BIYU_PROJECT_ROOT`、`BIYU_SHORT_SHA`(来自 packaging-version.json,由构建脚本写入)。

## 构建(开发机,在仓库根)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build_sidecar.ps1
```

冒烟(红绿凭证):

```
.venv\Scripts\python.exe packaging\smoke_sidecar.py     # 构建前=红(exe 缺失),构建后=绿(带启动耗时)
```

Electron 薄壳(开发/便携形态):

```
cd packaging\electron
npm install
npm run smoke    # 无窗模式:拉起 sidecar→/api/version 就绪→输出 JSON→退出并杀干净
npm start        # 正式窗口
```

## 版本口径

对外版本号 v1.0.0(工单 E 节;图纸代号 V2.1 不外显)。构建信息(short sha、build 日期)由
`build_sidecar.ps1` 写入 `home-staging/packaging-version.json`,壳注入 `BIYU_SHORT_SHA` 供 `/api/version` 回显。
