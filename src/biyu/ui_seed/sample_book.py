"""示例书《死亡回溯》首启种入 — S-3 T2(design.md: fixture 注入,幂等,不污染存量)。

规则:
- 只有 BIYU_SEED_SAMPLE_BOOK=1(安装版 Electron 壳注入)且书架为空时种入;
- 幂等标记 <data_root>/.biyu-seed.json:种过(或判定不必种)后不再种;
- 书本体走 create_book 正常建档,候选稿 AI 味超标由真实 run_audit 判定(阈值零改动);
- 批注为手写 fixture(工单 D2:内容真跑或手写由工程定;DeepSeek 充值后可换真跑)。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

MARKER_FILENAME = ".biyu-seed.json"
SAMPLE_TITLE = "死亡回溯"
SAMPLE_GENRE = "xuanyi"  # 代码值;genre.js 以代码映射中文徽章(写中文会显示「未知题材」)

_NORTH_STAR_MD = """# 北极星

## 一句话故事
重度社恐的旧武馆学徒张今空，在灰雾吞噬南城之夜绑定祖传七字铜鞘短刀；每次死亡都会回到惨剧发生前十二小时，他必须靠极其细腻的观察力在无数次试错中找出唯一的破局活路。

## 主题
社恐不是缺陷，是另一种看世界的方式。当所有人都在喊叫时，安静观察的人才看得见活路。

## 全书基调
冷硬、克制、重器物细节与市井烟火气；情绪落到具体物象，不写抽象抒情。
"""

_BOOK_OUTLINE_MD = """# 大纲

## 第一卷 · 雾起南城（第 1 – 35 章）
灰雾封锁南城外门，张今空借七字铜刀经历三次死亡回溯，查清钟楼异响与巡城司暗探围捕真相，护住旧武馆众人。

## 第二卷 · 守夜人残卷（第 36 – 80 章）
走出南城内坊，潜入钟楼地下藏经阁，揭开“七字铜刀”重燃所需的代价，与第二位回溯者展开时间博弈。

## 第三卷 · 倒悬京畿（第 81 – 140 章）
大历皇城被整座拖入回溯死循环，张今空以凡人学徒之躯布局百日，斩断灰雾源头。
"""

_WORLDBOOK: dict[str, Any] = {
    "narrative_anchors": {
        "protagonist_archetype": "极度社恐但观察力入微的旧武馆学徒，用最冷静的物证推理破解死亡回溯死局",
        "tone": "冷硬、克制、重器物细节与市井烟火气",
        "satisfaction_pattern": "观察型破局：别人靠武力，主角靠看见别人看不见的细节",
    },
    "facts": [
        "每次死亡回溯固定退回惨剧发生前 12 小时",
        "唯有祖传铜鞘短刀上的物理划痕与主角记忆能跨时间线留存",
        "短刀刀身铭刻“临兵斗者皆阵列护”七枚古篆，每次回溯消耗末位一字亮度",
    ],
    "power_system": {
        "name": "七字铜鞘短刀",
        "rules": [
            "每次死亡回溯消耗末位一枚古篆的光泽",
            "需达成特定救人或破局契机方可重燃",
            "古篆全部熄灭后短刀碎裂，回溯能力永久消失",
        ],
    },
    "forbidden": [
        "严禁主角向任何活人直接说出“我重生/回溯了”，违者触发抹杀",
        "严禁出现网游式系统面板弹窗或机械提示音",
        "严禁出现上午九点西窗直射阳光等物理方位常识硬伤",
    ],
    "geography": [
        "南城旧武馆：主角日常据点，位于内坊东槐巷（东侧高窗临巷）",
        "巡城司衙署：官方铁腕缉捕机构，黑衣暗探遍布街巷",
        "钟楼：南城十字街心，守夜人掌握灰雾源头真相的隐秘据点",
    ],
    "factions": [
        "南城旧武馆：陈馆主坐镇，收留主角的日常据点",
        "巡城司：官方缉捕机构，追查钟楼异响",
        "钟楼守夜人：掌握灰雾源头真相的隐秘教会",
    ],
    "timeline": [
        "大历十七年十月初九：灰雾首次封锁南城外城门",
        "十月初十辰时（上午九点）：武馆晨练异变、巡城司上门盘查",
    ],
}

_CHARACTERS: list[dict[str, Any]] = [
    {
        "name": "张今空",
        "tier": "protagonist",
        "role": "南城旧武馆挂名学徒 · 死亡回溯者",
        "background": "父母早亡，由陈馆主收留于旧武馆后厨与刀房打杂，继承祖传七字铜鞘短刀。",
        "personality": "重度社恐但观察入微，沉默寡言，习惯用眼角余光观察四周，右手虎口有常年握刀老茧。",
        "aliases": {
            "narrator_default": "张今空",
            "self_referent": "我",
            "called_by": {"方圆": "师兄", "陈馆主": "今空"},
        },
        "forbidden_in_narrative": ["小张", "张少侠", "宿主"],
        "voice_examples": ["“晨练加了两组重桩，虎口脱力而已。”", "“门栓松了半寸，昨晚有人从外头拨过。”"],
        "status": "经历第 3 次回溯，铜刀七字同暗一瞬",
        "current_location": "南城旧武馆内堂",
        "current_emotional_state": "外表平静，内里高度戒备",
        "current_power_level": "凡人武徒 · 短刀剩余 5 次回溯亮度",
    },
    {
        "name": "方圆",
        "tier": "major_supporting",
        "role": "陈馆主幼女 · 习武小师妹",
        "background": "自幼在武馆长大，负责照看药房与日常茶水。",
        "personality": "直率心细，外柔内刚，最早察觉张今空持刀手抖的异样。",
        "aliases": {
            "narrator_default": "方圆",
            "self_referent": "我",
            "called_by": {"张今空": "方师妹", "陈馆主": "圆儿"},
        },
        "forbidden_in_narrative": ["方小姐"],
        "voice_examples": ["“骗人。你拿刀的手在发抖，我看到了。”"],
        "status": "安然无恙，刚送完热茶",
        "current_location": "旧武馆内堂",
        "current_emotional_state": "担忧师兄身体",
        "current_power_level": "初通拳脚",
    },
    {
        "name": "陈馆主",
        "tier": "major_supporting",
        "role": "旧武馆馆主 · 退役军中教头",
        "background": "曾任南城防卫营校尉，因旧伤退伍开办武馆。",
        "personality": "护短沉稳，不怒自威，与巡城司旧部有暗中往来。",
        "aliases": {
            "narrator_default": "陈馆主",
            "self_referent": "老夫",
            "called_by": {"张今空": "馆主", "方圆": "爹"},
        },
        "forbidden_in_narrative": ["陈老头"],
        "voice_examples": ["“馆里弟子晨练，没听见什么钟楼响动。”"],
        "status": "在武馆台阶下挡住巡城司视线",
        "current_location": "旧武馆正门台阶",
        "current_emotional_state": "沉着周旋",
        "current_power_level": "气血浑厚（内劲三层）",
    },
]

_OUTLINE_TMPL = """---
present_characters: [{names}]
---

# 第 {num} 章 · {title}

{beats}
"""

_OUTLINES: dict[int, str] = {
    1: _OUTLINE_TMPL.format(
        names="张今空, 陈馆主",
        num=1,
        title="第七次呼吸停止之前",
        beats="1. 灰雾封城之夜，张今空在刀房第一次触发死亡回溯。\n2. 回到十二小时前的武馆清晨，发现铜鞘上多了一道刻痕。",
    ),
    2: _OUTLINE_TMPL.format(
        names="张今空, 方圆",
        num=2,
        title="东槐巷的第三个鞋印",
        beats="1. 张今空借整理兵器清点短棍，确认昨夜有人潜入武馆。\n2. 方圆送茶察觉他握刀手抖，他借口晨练脱力遮掩。",
    ),
    3: _OUTLINE_TMPL.format(
        names="张今空, 陈馆主, 方圆",
        num=3,
        title="钟楼第三声闷响",
        beats="1. 钟楼深夜传来三声闷响，巡城司黑衣暗探现身巷口茶摊盘问。\n2. 陈馆主出面周旋挡下盘查；张今空收刀入鞘听到铜鞘回音。",
    ),
    4: _OUTLINE_TMPL.format(
        names="张今空, 方圆, 陈馆主",
        num=4,
        title="面具下的脸",
        beats="1. 巡城司暗探再次登门，带来一张画着面具人的通缉画影。\n2. 方圆认出画影中的旧物；章末敲门声第三次响起。",
    ),
}

# 已定稿正文(干净文风,不触发 AI 味雷达)
_CHAPTERS_OFFICIAL: dict[int, str] = {
    1: (
        "灰雾是后半夜漫过外城门的。\n"
        "张今空被一阵极轻的铜器摩擦声惊醒。不是喊声——雾进城的时候没有人喊，"
        "只有武馆后院的狗把脖子上的链子绷直了，又慢慢松开。\n"
        "他摸到刀房，从木架上取下那柄祖传的七字铜鞘短刀。刀出鞘的一瞬，"
        "刀身七枚古篆同时亮了一线，像有人隔着黑暗划了七根火柴。\n"
        "然后呼吸停止了。这是他记事以来第七次觉得自己要死，"
        "也是第一次，死之前手里握着一样东西。\n"
        "再睁眼，是武馆清晨。东侧高窗漏进一束冷白日光，陈馆主的咳嗽声从院子里传来。"
        "张今空低头看刀：铜鞘边缘，多了一道新的刻痕。\n"
    ),
    2: (
        "晨练散场后，张今空把兵器架上的短棍一根根归位。\n"
        "第三排缺了一根——不是丢了，是被挪走又放了回来，木架的浮灰上留下半枚鞋印，"
        "鞋尖朝内。昨夜有人从院墙外进来过，就站在这排架子前。\n"
        "“师兄，茶凉了。”方圆把粗瓷碗搁在木案边，目光落在他指节泛白的右手上，"
        "“你拿刀的手在发抖，我看到了。”\n"
        "张今空没有抬头，只把袖口往下拽了半寸：“晨练加了两组重桩，虎口脱力而已。”\n"
        "方圆没再问。她走的时候，顺手把那半枚鞋印上方的短棍摆正了。\n"
    ),
    3: (
        "钟楼的闷响是子时传来的，三声，间隔极匀。\n"
        "天亮之后，两名玄衣巡城司暗探按刀站在东槐巷口的茶摊旁，问昨夜的响动。"
        "陈馆主背着手站在台阶下，替馆里弟子挡住了探子往里扫视的视线。\n"
        "张今空隔着窗缝看完全程。他把刀收入鞘中——这一次，鞘口铜边和刀镡咬合时，"
        "那声极轻极脆的“咔”终于响了，尾音在空旷的木鞘腔体里撞出一声只有他能听见的微弱回鸣。\n"
        "昨晚那场死局，终究在铜刃上留下了真实的残响。\n"
    ),
}

# 候选稿(手写 AI 味重灾样本:套话/明喻/缓冲词密度全部超阈值,供雷达与批注演示)
_CHAPTER_CANDIDATE = (
    "夜色深沉，南城旧武馆的后院里静得可怕。\n"
    "张今空站在石阶旁，嘴角勾起一抹三分薄凉七分讥诮的弧度，眼神微眯透出危险的气息。\n"
    "某种意义上来说，巡城司暗探的到来似乎早有预兆。他心中暗道不妙，瞳孔一缩，"
    "仿佛被无形命运扼住咽喉的窒息感似乎又一次笼罩了他。\n"
    "院墙外传来的脚步声如同潮水般涌来，像是一柄利剑刺破黑夜；他倒吸一口凉气，"
    "不由得缓缓握紧了手中仿佛有千钧之重的短刀。\n"
    "方圆端着茶碗走过来，她的身影在月光下宛如一尊凝固的雕塑。张今空嘴角微微上扬，"
    "心中暗道：这样的夜晚，恐怕又是一个不眠之夜了吧。\n"
    "巷口的灯笼缓缓熄灭，只剩巡城司暗探那双鹰隼般的眼睛，在黑暗中缓缓亮起，"
    "像是两点鬼火，瞳孔一缩之间，杀意如同实质般涌来。\n"
    "他轻轻叹了口气，淡淡的月光洒在青石板上，仿佛给这座武馆披上了一层银纱。"
    "巡城司的通缉画影在夜风中轻轻颤动，画上那张面具下的脸，嘴角勾起，"
    "仿佛正在对他微笑。\n"
    "门外，第三次敲门声响起。\n"
)

# 手写批注 fixture(示例书自带;充值后可换真跑 Editor 输出)
_SEED_ISSUES: list[dict[str, Any]] = [
    {
        "id": "ch4-001",
        "type": "文风与AI味",
        "paragraph": 3,
        "description": "“嘴角勾起一抹三分薄凉七分讥诮的弧度，眼神微眯透出危险的气息”是典型 AI 塑料霸总描写；主角是社恐武馆学徒，紧张时应写手指、刀鞘或呼吸细节。",
        "suggestion": "改为：张今空垂下眼睑，右手拇指无声地摩挲过铜鞘边缘那道新添的细微刻痕。",
        "severity": "high",
        "status": "open",
        "quoted_text": "嘴角勾起一抹三分薄凉七分讥诮的弧度，眼神微眯透出危险的气息",
    },
    {
        "id": "ch4-002",
        "type": "文风与AI味",
        "paragraph": 4,
        "description": "“仿佛被无形命运扼住咽喉的窒息感似乎又一次笼罩了他”单句堆叠“仿佛/似乎”缓冲词与抽象命运比喻，情绪没有落到具体物象。",
        "suggestion": "改为：后背贴紧廊柱阴影，他把呼吸压得极浅，右手虎口的老茧抵住刀镡。",
        "severity": "medium",
        "status": "open",
        "quoted_text": "仿佛被无形命运扼住咽喉的窒息感似乎又一次笼罩了他",
    },
]


def _marker_path(data_root: Path) -> Path:
    return data_root / MARKER_FILENAME


def _shelf_books(data_root: Path) -> list[Path]:
    if not data_root.is_dir():
        return []
    return [p for p in sorted(data_root.iterdir()) if p.is_dir() and (p / "book.json").is_file()]


def _write_marker(data_root: Path, payload: dict[str, Any]) -> None:
    _marker_path(data_root).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def sample_book_summary(data_root: Path) -> dict[str, Any] | None:
    """读种入标记;无标记返回 None。"""
    path = _marker_path(Path(data_root))
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _seed_chapter_audit(book_dir: Path, chapter: int, text: str) -> dict[str, Any]:
    """对候选稿跑真实 auditor 并落审计 JSON/MD + 手写批注。"""
    from biyu.auditor import run_audit
    from biyu.audit_reports.builder import build_audit_report
    from biyu.audit_reports.state import AuditIssue, AuditReportJSON
    from biyu.config import get_project_root, load_characters_yaml
    from biyu.worldbook import load_worldbook

    ctx: dict[str, Any] = {
        "book_dir": book_dir,
        "chapter_num": chapter,
        "project_root": get_project_root(),
        "worldbook": load_worldbook(book_dir),
        "characters": load_characters_yaml(book_dir),
        "present_characters": ["张今空", "方圆", "陈馆主"],
    }
    audit_results = run_audit(text, ctx)
    results = [
        {
            "checker": ar.checker,
            "severity": ar.severity.value if hasattr(ar.severity, "value") else str(ar.severity),
            "message": ar.message,
            "details": ar.details,
        }
        for ar in audit_results
    ]
    report = AuditReportJSON(
        chapter=chapter,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        editor_mode="single",
        editor_cost_yuan=0.0,
        issues=[AuditIssue.from_dict(dict(issue)) for issue in _SEED_ISSUES],
        results=results,
    )
    report.save(book_dir / "audit_reports")
    build_audit_report(book_dir, chapter)
    style = next((r for r in results if r["checker"] == "style_repeat"), None)
    return {
        "style_repeat_severity": style["severity"] if style else "MISSING",
        "density_violations": (
            (style.get("details") or {}).get("density_violations", []) if style else []
        ),
    }


def _do_seed(data_root: Path) -> dict[str, Any]:
    from biyu.book_service import create_book
    from biyu.config import load_characters_yaml  # noqa: F401  (确保导入链可用)
    from biyu.setup_asset_versions import (
        save_setup_asset_version,
        update_book_outline_text,
        update_north_star_text,
    )
    from biyu.worldbook import load_worldbook  # noqa: F401

    created = create_book(SAMPLE_TITLE, SAMPLE_GENRE, data_root=data_root)
    book_dir = created.book_dir

    # 标记为示例书(T3 书架徽章用;对既有 reader 是无害多余键)
    meta_path = book_dir / "book.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["is_sample"] = True
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 9 格:2 书级格 + 7 世界观格
    update_north_star_text(book_dir, _NORTH_STAR_MD, actor="示例书种子")
    update_book_outline_text(book_dir, _BOOK_OUTLINE_MD, actor="示例书种子")
    import yaml

    (book_dir / "worldbook.yaml").write_text(
        yaml.safe_dump(_WORLDBOOK, allow_unicode=True, sort_keys=False), encoding="utf-8",
    )
    save_setup_asset_version(book_dir, "worldbook", reason="seed_sample", actor="示例书种子")

    # 人物卡 ≥3
    (book_dir / "characters.yaml").write_text(
        yaml.safe_dump({"characters": _CHARACTERS}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    save_setup_asset_version(book_dir, "characters", reason="seed_sample", actor="示例书种子")

    # 细纲 + ≥3 章已定稿
    for num, outline in _OUTLINES.items():
        (book_dir / "outlines" / f"ch{num}.md").write_text(outline, encoding="utf-8")
    for num, text in _CHAPTERS_OFFICIAL.items():
        (book_dir / "chapters" / f"ch{num}.md").write_text(text, encoding="utf-8")

    # 候选稿(雷达超标样本)+ 真实审计 + 手写批注
    (book_dir / "chapters" / "_pending" / "ch4.md").write_text(
        _CHAPTER_CANDIDATE, encoding="utf-8",
    )
    audit_info = _seed_chapter_audit(book_dir, 4, _CHAPTER_CANDIDATE)

    return {
        "book_id": created.book_id,
        "chapters_official": sorted(_CHAPTERS_OFFICIAL),
        "candidate_chapter": 4,
        "characters": len(_CHARACTERS),
        **audit_info,
    }


def maybe_seed_sample_book(data_root: Path | None = None, *, enabled: bool | None = None) -> dict[str, Any]:
    """幂等种入示例书。返回动作说明(供日志/验收,不抛出阻塞启动)。"""
    from biyu.config import get_data_root

    root = Path(data_root) if data_root is not None else get_data_root()
    if enabled is None:
        enabled = os.environ.get("BIYU_SEED_SAMPLE_BOOK", "").strip() == "1"
    result: dict[str, Any] = {"data_root": str(root)}

    if not enabled:
        result.update(action="disabled", reason="BIYU_SEED_SAMPLE_BOOK!=1")
        return result

    if sample_book_summary(root) is not None:
        result.update(action="skipped", reason="already-seeded")
        return result

    existing = _shelf_books(root)
    if existing:
        _write_marker(root, {
            "version": 1,
            "seeded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": "shelf-nonempty",
            "sample_seeded": False,
        })
        result.update(action="skipped", reason=f"shelf-nonempty({len(existing)})")
        return result

    try:
        info = _do_seed(root)
    except Exception as exc:  # 种子失败不阻塞应用;留待下次(无标记可重试)
        result.update(action="failed", error=f"{type(exc).__name__}: {exc}")
        return result

    _write_marker(root, {
        "version": 1,
        "seeded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sample_seeded": True,
        "book_id": info["book_id"],
        "title": SAMPLE_TITLE,
    })
    result.update(action="seeded", **info)
    return result
