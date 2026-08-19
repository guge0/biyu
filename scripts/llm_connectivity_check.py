#!/usr/bin/env python3
"""LLM 连通性预检脚本 (P6-13-B2)

在跑生成任务前运行，检测 DeepSeek API 是否可达。
不可达时提示并退出，防止半途烧钱失败。

用法: python scripts/llm_connectivity_check.py
"""

import sys
import os

# 确保项目 src 在路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# 触发 NO_PROXY 注入（llm/__init__.py 中的环境变量修复）
import biyu.llm  # noqa: F401

import httpx


def check_deepseek() -> bool:
    """检查 DeepSeek API TLS 连通性。任何 HTTP 响应（含 401）即表示 TLS 层通。"""
    url = "https://api.deepseek.com/v1/models"
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url)
            print(f"[OK] DeepSeek API 可达 — HTTP {r.status_code}")
            return True
    except httpx.ConnectError as e:
        print(f"[FAIL] DeepSeek API 连接失败: {e}")
        return False
    except Exception as e:
        print(f"[FAIL] DeepSeek API 异常: {type(e).__name__}: {e}")
        return False


def main():
    print("=== LLM 连通性预检 ===")
    print(f"NO_PROXY = {os.environ.get('NO_PROXY', '(未设置)')}")

    # 显示系统代理状态
    try:
        import urllib.request
        proxies = urllib.request.getproxies()
        if proxies:
            print(f"系统代理: {proxies}")
        else:
            print("系统代理: (无)")
    except Exception:
        pass

    ok = check_deepseek()
    if not ok:
        print()
        print(">>> DeepSeek API 不可达！<<<")
        print("可能原因:")
        print("  1. VPN 系统代理拦截了国内流量")
        print("  2. 网络不通")
        print("建议:")
        print("  - 关闭 VPN 后重试")
        print("  - 或在 VPN 客户端添加 DIRECT 规则: api.deepseek.com")
        sys.exit(1)

    print("预检通过，可以开始生成。")
    sys.exit(0)


if __name__ == "__main__":
    main()
