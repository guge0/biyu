"""Phase 2 反思指令模板 — 每个 agent 审视自己的 v1 并参考 peer 的 v1。"""
from __future__ import annotations

REFLECTION_SYSTEM_TEMPLATE = """\
你是 Editor-{agent_id}，正在进行第二轮审稿反思。

## 任务
你之前对第 {chapter_num} 章提交了初版审稿意见（v1）。现在你将看到：
1. 你自己的 v1 意见
2. 其他审稿编辑的 v1 意见（但不知道他们是谁）

你需要：
- **保留**你认为正确的 issue（可以微调描述/建议）
- **撤回**你觉得站不住脚的 issue（设 retracted=true，写明 retracted_reason）
- **不要新增** issue（只做保留或撤回的决策）
- 参考同行的意见来校准自己的判断，但保持独立思考

## 信息隔离
你只能看到 v1 版本的意见。你不要试图猜测其他编辑的身份或专业领域。

## 输出格式

审稿完成后，调用 submit_review 工具提交结果。submit_review 的 issues 参数格式：
{{
  "issues": [
    {{
      "id": "{agent_id}-1",
      "type": "...",
      "paragraph": 0,
      "severity": "...",
      "keyword": "...",
      "description": "...",
      "suggestion": {{"content": "...", "rationale": "..."}},
      "retracted": false,
      "retracted_reason": ""
    }}
  ]
}}

每个 issue 的 id 必须与你的 v1 issue id 一一对应。
撤回的 issue 设置 retracted=true 并填写 retracted_reason。

再次提醒：你是 Editor-{agent_id}，只做保留或撤回决策，不要新增 issue。
"""


def build_reflection_prompt(
    agent_id: str,
    chapter_num: int,
    own_v1_json: str,
    peer_v1_jsons: list[str],
) -> tuple[str, str]:
    """构建 Phase 2 反思的 system prompt 和 user prompt。

    Returns:
        (system_prompt, user_prompt)
    """
    system_prompt = REFLECTION_SYSTEM_TEMPLATE.format(
        agent_id=agent_id,
        chapter_num=chapter_num,
    )

    parts = [f"## 你的 v1 意见：\n{own_v1_json}"]

    for idx, peer_json in enumerate(peer_v1_jsons, 1):
        parts.append(f"\n## 同行编辑 {idx} 的 v1 意见：\n{peer_json}")

    parts.append("\n请基于以上信息，重新审视你的 v1 意见，输出最终的 v2 版本。")

    user_prompt = "\n".join(parts)
    return system_prompt, user_prompt
