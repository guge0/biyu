"""S-3C · LLM 报错人话化单元契约 + 五阶段接线回归锚。

异常矩阵的「文案」层:401/402/断网/超时 → 作者能行动的中文;
真实五阶段端到端矩阵(带截图)见 _biyu交付记录/<日期>/S-3C/异常矩阵.md。
"""
from __future__ import annotations

from pathlib import Path

from biyu.llm.glm import LLMError
from biyu.ui.llm_error_copy import humanize_llm_error

REPO = Path(__file__).resolve().parents[1]


def test_401_invalid_key_becomes_actionable_copy() -> None:
    text = humanize_llm_error(LLMError(401, "Authentication Fails, Your api key: ***invalid"))
    assert "API Key 无效" in text
    assert "401" in text
    assert "原始信息" in text  # 排查线索保留


def test_402_insufficient_balance_becomes_actionable_copy() -> None:
    text = humanize_llm_error(LLMError(402, "Insufficient Balance"))
    assert "余额不足" in text
    assert "充值" in text


def test_402_from_raw_subprocess_tail_line() -> None:
    # 章动作走子进程,拿到的只是末行日志:LLMError 的 "[402] ..." 形态要能被识别
    tail = "biyu.llm.glm.LLMError: [402] Insufficient Balance"
    text = humanize_llm_error(raw=tail, default=tail)
    assert "余额不足" in text


def test_timeout_becomes_human_copy() -> None:
    text = humanize_llm_error(raw="httpx.ReadTimeout: The read operation timed out")
    assert "超时" in text
    assert "网络" in text


def test_connection_refused_becomes_human_copy() -> None:
    text = humanize_llm_error(LLMError(0, "连接失败：[WinError 10061] 由于目标计算机积极拒绝，无法连接。"))
    assert "连不上服务商" in text
    assert "接口地址" in text


def test_server_error_5xx_copy() -> None:
    text = humanize_llm_error(LLMError(503, "service unavailable"))
    assert "服务商" in text and "稍等" in text


def test_already_human_message_passes_through_default() -> None:
    original = "开书模型(v4_flash)不可用：请先在连接设置保存 Key"
    text = humanize_llm_error(ValueError(original), default=f"ValueError: {original}")
    assert text == f"ValueError: {original}"  # 已是人话 → 不硬翻,保留调用方上下文


def test_empty_error_falls_back_to_default() -> None:
    assert humanize_llm_error(raw="  ", default="备用文案") == "备用文案"


def test_humanizer_wired_into_all_five_stages() -> None:
    """接线回归锚:五个阶段的报错出口都必须经过人话化(工单 A2 只修文案,不改路径)。"""
    wiring = {
        "src/biyu/ui/setup.py": 2,        # 首次连接保存 complete + update(自定义服务商共三处)
        "src/biyu/ui/wizard.py": 1,       # 向导 premise
        "src/biyu/ui/cli_executor.py": 1,  # 导演方案/写章/返修(章动作子进程统一出口)
        "src/biyu/ui/routes.py": 1,       # 编辑审读(责编 SSE 失败如实显示)
    }
    for rel, floor in wiring.items():
        text = (REPO / rel).read_text(encoding="utf-8")
        assert text.count("humanize_llm_error") >= floor + (1 if "llm_error_copy" not in rel else 0), rel
        if rel != "src/biyu/ui/llm_error_copy.py":
            assert "humanize_llm_error" in text, rel
