'use strict';
/* 笔驭 v1.0 Electron 薄壳(packaging/electron/main.js)。
 * 职责(灵枢同款已验证路线,刻意保持极薄):
 *   1. 首启初始化安装版数据根 %APPDATA%\biyu-studio,并按数据根锁定机制写
 *      %USERPROFILE%\.biyu\runtime-production.json(机制本体零改动,只消费)。
 *   2. 挑空闲端口,以安装版语义 env 拉起 biyu-sidecar(本地 FastAPI)。
 *   3. 轮询 /api/version 就绪后开窗加载;退出时 taskkill 杀整棵 sidecar 进程树。
 *   4. --smoke 无窗模式:就绪后输出 JSON 并退出,供自动化红绿/走查取证。
 * 不做菜单/托盘/自动更新(v1.0 降级:状态栏版本区点击=到群/官网下载新版)。
 */

const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const net = require('net');
const os = require('os');
const path = require('path');

const SMOKEMODE = process.argv.includes('--smoke');
const READY_TIMEOUT_MS = 45000;

function log(msg) { console.log(`[biyu-shell] ${msg}`); }

// ---------- 路径解析:开发/便携形态(仓库内) 与 打包形态(resources/) ----------
function resolveLayout() {
  const here = __dirname;
  // S-3C 便携平铺布局:electron-shell/ 与 biyu-sidecar.exe 同在包根(启动笔驭.bat 直调时)
  const sibling = path.join(here, '..', 'biyu-sidecar.exe');
  if (fs.existsSync(sibling)) {
    return {
      mode: 'portable-root',
      sidecarExe: sibling,
      homeDir: path.dirname(sibling),
      icon: path.join(here, 'icons', 'biyu.ico'),
    };
  }
  const devRoot = path.resolve(here, '..', '..');
  const devSidecar = path.join(devRoot, 'packaging', 'dist', 'biyu-sidecar', 'biyu-sidecar.exe');
  if (fs.existsSync(devSidecar)) {
    return {
      mode: 'portable',
      sidecarExe: devSidecar,
      // exe 目录兼任 BIYU_PROJECT_ROOT(config 免Key件/docs/prompts/assets 已由构建脚本铺入)
      homeDir: path.dirname(devSidecar),
      icon: path.join(here, 'icons', 'biyu.ico'),
    };
  }
  const res = process.resourcesPath || '';
  const pkgSidecar = path.join(res, 'sidecar', 'biyu-sidecar.exe');
  if (res && fs.existsSync(pkgSidecar)) {
    return {
      mode: 'installed',
      sidecarExe: pkgSidecar,
      homeDir: path.dirname(pkgSidecar),
      icon: path.join(res, 'icon.ico'),
    };
  }
  return null;
}

// ---------- 安装版数据根(首启初始化,幂等) ----------
function initDataRoot() {
  const dataRoot = path.join(app.getPath('appData'), 'biyu-studio');
  fs.mkdirSync(dataRoot, { recursive: true });

  const cfgDir = process.env.BIYU_USER_CONFIG_DIR || path.join(os.homedir(), '.biyu');
  fs.mkdirSync(cfgDir, { recursive: true });
  const cfgPath = path.join(cfgDir, 'runtime-production.json');
  let current = null;
  try { current = JSON.parse(fs.readFileSync(cfgPath, 'utf8')); } catch (_) { /* 首启 */ }
  if (!current || current.data_root !== dataRoot) {
    fs.writeFileSync(cfgPath, JSON.stringify({ data_root: dataRoot }, null, 2), 'utf8');
    log(`runtime-production.json -> ${dataRoot}`);
  }
  return dataRoot;
}

function readBuildInfo(homeDir) {
  try {
    return JSON.parse(fs.readFileSync(path.join(homeDir, 'packaging-version.json'), 'utf8'));
  } catch (_) {
    return { version: '1.0.0', build: 'unknown', sha: 'unknown' };
  }
}

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
  });
}

function waitReady(port, timeoutMs) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    (function poll() {
      if (Date.now() - started > timeoutMs) {
        reject(new Error(`/api/version not ready in ${timeoutMs}ms`));
        return;
      }
      const req = http.get({ host: '127.0.0.1', port, path: '/api/version', timeout: 2000 }, (res) => {
        let body = '';
        res.on('data', (c) => { body += c; });
        res.on('end', () => {
          if (res.statusCode === 200) {
            let payload = null;
            try { payload = JSON.parse(body); } catch (_) { /* keep null */ }
            resolve({ payload, ms: Date.now() - started });
          } else { setTimeout(poll, 300); }
        });
      });
      req.on('error', () => setTimeout(poll, 300));
      req.on('timeout', () => { req.destroy(); setTimeout(poll, 300); });
    })();
  });
}

function killTree(pid) {
  if (!pid) return;
  if (process.platform === 'win32') {
    spawn('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' });
  } else {
    try { process.kill(-pid, 'SIGTERM'); } catch (_) { try { process.kill(pid); } catch (_e) { /* gone */ } }
  }
}

async function main() {
  const layout = resolveLayout();
  if (!layout) {
    log('FATAL: biyu-sidecar not found (build packaging/dist first, or install layout broken).');
    if (SMOKEMODE) { console.log(JSON.stringify({ ok: false, error: 'sidecar-not-found' })); app.exit(1); return; }
    app.quit();
    return;
  }

  const dataRoot = initDataRoot();
  const build = readBuildInfo(layout.homeDir);
  const port = await freePort();
  log(`layout=${layout.mode} sidecar=${layout.sidecarExe}`);
  log(`data root=${dataRoot} port=${port} version=v${build.version} sha=${build.sha}`);

  const child = spawn(layout.sidecarExe, [], {
    cwd: layout.homeDir,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: Object.assign({}, process.env, {
      BIYU_ENV: 'prod',
      BIYU_RUNTIME_ROLE: 'production',
      BIYU_DATA_ROOT: dataRoot,
      BIYU_DATA_ROOT_SOURCE: 'persistent', // 数据根来自首启写入的持久配置(与生产 ps1 链路同语义),避免 UI 误报「临时数据根」
      BIYU_PRODUCTION_DATA_ROOT: dataRoot,
      BIYU_PROJECT_ROOT: layout.homeDir,
      BIYU_CHECKOUT_NAME: 'biyu-studio',
      BIYU_SHORT_SHA: String(build.sha || 'unknown'),
      BIYU_REMOTE_SLUG: 'guge0/biyu-studio',
      BIYU_SEED_SAMPLE_BOOK: '1', // S-3 无 Key 层:首启空架种入示例书(ui_seed 幂等)
      BIYU_SIDECAR_PORT: String(port),
    }),
  });
  child.stdout.on('data', (c) => { const s = String(c).trim(); if (s) log(`[sidecar] ${s}`); });
  child.stderr.on('data', (c) => { const s = String(c).trim(); if (s) log(`[sidecar!] ${s}`); });
  child.on('exit', (code) => { log(`sidecar exited code=${code}`); });

  const t0 = Date.now();
  let ready;
  try {
    ready = await waitReady(port, READY_TIMEOUT_MS);
  } catch (err) {
    killTree(child.pid);
    log(`FATAL: ${err.message}`);
    if (SMOKEMODE) { console.log(JSON.stringify({ ok: false, error: String(err.message) })); app.exit(1); return; }
    app.quit();
    return;
  }
  log(`sidecar ready in ${ready.ms}ms (${Date.now() - t0}ms wall) version=${JSON.stringify(ready.payload)}`);

  const cleanup = () => killTree(child.pid);
  app.on('before-quit', cleanup);
  process.on('exit', cleanup);

  if (SMOKEMODE) {
    console.log(JSON.stringify({ ok: true, port, ready_ms: ready.ms, version: ready.payload, data_root: dataRoot }));
    app.exit(0);
    return;
  }

  await app.whenReady();
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1180,
    minHeight: 720,
    backgroundColor: '#F3F1EA',
    autoHideMenuBar: true,
    title: '笔驭',
    icon: layout.icon,
    show: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  win.once('ready-to-show', () => win.show());
  await win.loadURL(`http://127.0.0.1:${port}/`);
  win.on('closed', () => app.quit());
}

if (!app.requestSingleInstanceLock()) {
  log('another instance is running; exiting.');
  app.quit();
} else {
  app.on('second-instance', () => { log('second instance blocked'); });
  main().catch((err) => { log(`FATAL: ${err && err.stack || err}`); app.exit(1); });
}
