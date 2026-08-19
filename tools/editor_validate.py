"""
Editor 验证实验脚本
独立于 pipeline，不影响主管线
用途：验证 V4-Pro 当 Editor 是否可行

用法：python -m tools.editor_validate（从 biyu/ 目录运行）
"""

import asyncio
import io
import json
import os
import re
import sys
from pathlib import Path

# Windows 控制台 UTF-8 输出
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 将 src 加入 path 以便 import biyu
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from biyu.llm import ModelRegistry

BOOK_DIR = Path("data/张今空_T-P3-A验证")

EDITOR_SYSTEM_PROMPT = """你是这本书的责任编辑。你的任务是读完本章并标出"明显问题"。

什么算明显问题(你只管这 4 类):

1. 字面伪影:正文里出现了不该出现的字符串
   例如:"[NAME]"、"{character}"、"章末句"、"本章结束"、"Layer 1"
   这些是创作工具的内部词，绝不该出现在正文中

2. 视角穿帮:角色说出/知道他不该说/知道的内容
   例如:三国时代的曹操说"后人编的"
   例如:秘境内的人物提到"手机"、"互联网"

3. 跨章一致性:与前文的设定/描述冲突
   例如:之前说眼睛是黑色，本章变成蓝色
   例如:之前说"金色"已经分配给某个独特意象，本章又把金色给了另一个对象

4. 明显逻辑漏洞:违反物理/常识的描述
   例如:在水中的布上用手指画图(布在水里会散)
   例如:角色身份与言行不符(电焊工父亲突然说出文绉绉的话)

什么不归你管(看到也别提):

- 文笔好不好、句子美不美、节奏对不对
- 创作判断(这个伏笔该不该埋、爽点够不够)
- 错别字、标点(那是另一个工具的事)
- 你的个人审美偏好

工作方式:

1. 通读本章一遍
2. 遇到疑惑时主动根据已知设定判断
3. 标出问题，引用原文具体行/句子，说明问题类型
4. 给出建议(只对字面伪影类给"删除"建议，其他类给"标记待审"建议)
5. 输出 JSON 列表，每章问题数 ≤5(只挑最明显的)

不要做的事:

- 不要列"小问题"凑数，只挑明显的
- 不要评论"建议这里改成..."(那是创作判断)
- 不要假装看到问题，看不出问题就返回空列表

输出格式(严格 JSON):

{
  "issues": [
    {
      "line": 257,
      "quote": "章末句只停在张今空的最后一个字",
      "type": "字面伪影",
      "explanation": "这是创作工具的内部描述词，模型把 prompt 元词写进了正文",
      "fix_suggestion": "删除该行"
    }
  ],
  "queries_used": [],
  "confidence": "high"
}"""


def build_user_prompt(chapter_text: str, prior_context: str) -> str:
    """构建 Editor user prompt"""
    return f"""【本章正文】

{chapter_text}

---

【已知设定提示】
本书已设定:
- 金色 = 外部观察者标志(CH10 末出现的"凭什么是你?"金字、"那只青铜色的手"前身)
- 未来 CH27 末本命短刀第七字也将是金色——这构成跨章符号撞色
- 张父身份:建筑工地电焊工(语气接地气，不会文绉绉)
- 张今空、林溪、周大龙、赵小磊是核心四人组

【前文摘要】
{prior_context}

请通读本章正文，按 system prompt 要求标出 4 类明显问题。"""


async def main():
    # 1. 读 CH10 正文
    ch10_path = BOOK_DIR / "chapters" / "ch10.md"
    if not ch10_path.exists():
        print(f"错误: {ch10_path} 不存在")
        sys.exit(1)
    chapter_text = ch10_path.read_text(encoding="utf-8")

    # 2. 构建简化前文摘要(ch1-9 关键设定)
    prior_context = """
- 张今空高考路上校车被吞入秘境，与同学共 47 人进入赤壁之战
- CH1-3 赤壁秘境，获得命甲(借的甲，有负担)
- CH4-5 镇异局成立，陈处招募
- CH6 第二次秘境铠甲勇士开篇，主角与同学进入
- CH7-9 铠甲秘境推进，楚老 CH9 揭名(中三境兵修)
- CH10 救李超意识、白色空间记忆战、章末"凭什么是你?"金字浮现 + 青铜色的手伸出
"""

    # 3. 通过 ModelRegistry 获取 V4-Pro adapter
    registry = ModelRegistry()
    adapter = registry.get_adapter("v4_pro")

    messages = [
        {"role": "system", "content": EDITOR_SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(chapter_text, prior_context)},
    ]

    print("正在调用 V4-Pro 进行 Editor 验证...")
    response = await adapter.generate(
        messages=messages,
        max_tokens=2000,
        temperature=0.1,
    )

    raw_text = response.text
    cost = response.cost

    print(f"\n调用完成: prompt_tokens={response.prompt_tokens}, "
          f"completion_tokens={response.completion_tokens}, cost=¥{cost:.4f}")

    # 4. 解析 JSON
    try:
        result = json.loads(raw_text.strip())
    except json.JSONDecodeError:
        # 兜底: 尝试提取 ```json 块
        match = re.search(r'```json\s*(\{.*?\})\s*```', raw_text, re.DOTALL)
        if match:
            result = json.loads(match.group(1))
        else:
            print(f"JSON 解析失败，原始返回:\n{raw_text}")
            sys.exit(1)

    # 5. 输出验证报告
    print("\n" + "=" * 60)
    print("Editor 验证实验 - CH10 测试结果")
    print("=" * 60)
    print(f"\n标出的问题数: {len(result.get('issues', []))}")
    print(f"置信度: {result.get('confidence', 'unknown')}")
    print(f"\n详细 issues:\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 6. 验证项打分
    print("\n" + "=" * 60)
    print("验证项检查")
    print("=" * 60)

    issues = result.get('issues', [])

    # 验证项 1: 是否标出"章末句只停在..."字面伪影
    found_meta_word = any(
        '章末句' in issue.get('quote', '') or 'prompt' in issue.get('explanation', '').lower()
        for issue in issues
    )
    print(f"\n[验证 1] 字面伪影 '章末句' 是否被标出: {'✅ PASS' if found_meta_word else '❌ FAIL'}")

    # 验证项 2: 是否标出金色撞色
    found_color_clash = any(
        '金色' in issue.get('quote', '') or '撞色' in issue.get('explanation', '') or '一致性' in issue.get('type', '')
        for issue in issues
    )
    print(f"[验证 2] 金色撞色是否被标出: {'✅ PASS' if found_color_clash else '❌ FAIL'}")

    # 验证项 3: 视角穿帮(本章可能没有，看是否假阳性)
    view_issues = [i for i in issues if i.get('type') == '视角穿帮']
    print(f"[验证 3] 视角穿帮 issue 数: {len(view_issues)} (期望 0，本章应无)")

    # 验证项 4: 严重幻觉(quote 是否真的在原文里)
    hallucination_count = 0
    for issue in issues:
        quote = issue.get('quote', '')
        if quote and quote not in chapter_text:
            hallucination_count += 1
            print(f"  ⚠️ 幻觉: '{quote}' 不在原文中")
    print(f"[验证 4] 幻觉数: {hallucination_count} (期望 ≤1)")

    # 7. 总判定
    print("\n" + "=" * 60)
    pass_count = sum([found_meta_word, found_color_clash, hallucination_count <= 1])
    if pass_count >= 2 and hallucination_count <= 2:
        print("总判定: ✅ V4-Pro 当 Editor 可行，T-P3-C 走全 Editor 路线")
    elif pass_count >= 1:
        print("总判定: ⚠️ V4-Pro 部分可行，T-P3-C 走 hybrid 路线")
    else:
        print("总判定: ❌ V4-Pro 不胜任，T-P3-C 评估升级 Opus 4.7")
    print("=" * 60)

    # 8. 成本报告
    print(f"\n实际成本: ¥{cost:.4f}")
    print(f"预算剩余: ¥{0.02 - cost:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
