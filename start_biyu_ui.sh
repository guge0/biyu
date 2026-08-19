#!/usr/bin/env bash
# ===================================================================
# start_biyu_ui.sh - 笔驭作者工作台一键启动(macOS/Linux)
# 用法:./start_biyu_ui.sh ; Ctrl+C 退出
# 详:docs/codebase-structure.md
# ===================================================================

set -e

# 切到脚本所在目录(项目根)
cd "$(dirname "$0")"

# 检查 .venv
if [ ! -f ".venv/bin/activate" ]; then
    echo "[X] 未找到 .venv,请先在项目目录运行:"
    echo "    pip install -e \".[dev]\""
    exit 1
fi

# 激活 venv
source .venv/bin/activate

# 打印 banner 后启动
echo
echo "=========================================="
echo " 笔驭作者工作台启动中..."
echo " 浏览器请打开: http://127.0.0.1:8080"
echo " Ctrl+C 退出"
echo "=========================================="
echo

# 启动 UI(端口冲突自动 +1,最多重试 10 次)
biyu ui -p 8080
