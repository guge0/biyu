"""S-8-1/S-8-3 · 示范对加载与抽样契约:用户目录覆盖 / 坏文件回落 / 抽样剔除与上限。

用户目录与包内文件(BUNDLED_PATH)都按用例 monkeypatch 到自己的 tmp_path 假文件,
互不串味、不依赖包内真实数据(TL 会往里换数据);真实包内文件另有一条形态用例兜底。
"""
from __future__ import annotations

import json

from biyu.zhuque import pairs as pairs_mod
from biyu.zhuque.pairs import BUNDLED_PATH, load_pairs, sample_pairs

# 与测试窗无 12 字以上重合的示范对
PAIR_A = {"src": "他猫着腰钻进柴房，把半袋糙米挪到了墙角。",
          "dst": "他弯腰进了柴房，把半袋糙米挪到墙角那里。", "note": ""}
PAIR_B = {"src": "她收了针线，吹熄油灯，摸黑躺下。",
          "dst": "她把针线收起来，吹了灯，摸黑躺下。", "note": ""}
WINDOW = "常野推开柴房的门，里面堆着喂马的草料，他挨着草料堆坐下数账。"

# 假包内文件沿用旧包内形态(version 2026.11-0、pairs 空),原有断言原样保留
FAKE_BUNDLED_VERSION = "2026.11-0"


def _write_pairs_file(path, version: str, pairs: list) -> None:
    path.write_text(json.dumps({"version": version, "updated": "2026-11-19", "pairs": pairs},
                               ensure_ascii=False), encoding="utf-8")


def _write_user_file(tmp_path, version: str, pairs: list, raw: str | None = None) -> None:
    path = tmp_path / "zhzh_pairs.json"
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
        return
    _write_pairs_file(path, version, pairs)


def _fake_bundled(monkeypatch, tmp_path) -> None:
    """把包内数据路径指到 tmp 里的假文件(2026.11-0 空,同 TL 填数据前的包内形态)。"""
    bundled = tmp_path / "bundled_zhzh_pairs.json"
    _write_pairs_file(bundled, FAKE_BUNDLED_VERSION, [])
    monkeypatch.setattr(pairs_mod, "BUNDLED_PATH", bundled)


# ---------- 加载:用户目录覆盖 / 坏文件回落 ----------

def test_bundled_used_when_no_user_file(tmp_path, monkeypatch) -> None:
    """用户目录没有 zhzh_pairs.json:用包内版本(load_pairs 走包内来源)。"""
    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(tmp_path))
    _fake_bundled(monkeypatch, tmp_path)
    version, pairs = load_pairs()
    assert version == FAKE_BUNDLED_VERSION and pairs == []


def test_user_newer_version_overrides_bundled(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(tmp_path))
    _fake_bundled(monkeypatch, tmp_path)
    _write_user_file(tmp_path, "2026.11-1", [PAIR_A, PAIR_B])
    version, pairs = load_pairs()
    assert version == "2026.11-1" and pairs == [PAIR_A, PAIR_B]


def test_user_older_version_ignored(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(tmp_path))
    _fake_bundled(monkeypatch, tmp_path)
    _write_user_file(tmp_path, "2026.10-9", [PAIR_A])
    version, pairs = load_pairs()
    assert version == FAKE_BUNDLED_VERSION and pairs == []   # 包内更新,用户的让位


def test_bad_user_file_falls_back_to_bundled(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(tmp_path))
    _fake_bundled(monkeypatch, tmp_path)
    _write_user_file(tmp_path, "2026.11-9", None, raw="{不是 json")
    version, pairs = load_pairs()
    assert version == FAKE_BUNDLED_VERSION and pairs == []


def test_user_file_with_wrong_pair_shape_falls_back(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(tmp_path))
    _fake_bundled(monkeypatch, tmp_path)
    _write_user_file(tmp_path, "2026.11-9", [{"src": "只有原文没有改写"}])
    version, pairs = load_pairs()
    assert pairs == []


def test_bundled_real_file_is_wellformed(tmp_path, monkeypatch) -> None:
    """真实包内数据文件(TL 2026-11-19 填入正式数据):能加载、量足、形态对;
    dst 不得含破折号(改写规则「不用破折号」,示范对自己先要守住)。
    不断言具体版本号和内容,TL 换数据不用改这里。"""
    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(tmp_path))   # 用户目录空 → 必走包内
    assert BUNDLED_PATH.exists(), "包内数据文件丢了"
    version, pairs = load_pairs()
    assert isinstance(version, str) and version
    assert len(pairs) >= 12
    for pair in pairs:
        src, dst = pair.get("src"), pair.get("dst")
        assert isinstance(src, str) and src, "src 要是非空字符串"
        assert isinstance(dst, str) and dst, "dst 要是非空字符串"
        assert "—" not in dst, "示范对的 dst 不应含破折号"


def test_version_numeric_suffix_compares_numerically() -> None:
    """「-10」要大于「-9」(按数值,不按字符串)。"""
    from biyu.zhuque.pairs import _version_key
    assert _version_key("2026.11-10") > _version_key("2026.11-9")
    assert _version_key("2026.12") > _version_key("2026.11-10")
    assert _version_key("2026.11-1") > _version_key("2026.11")  # 带后缀 > 不带


# ---------- 抽样:重合剔除与上限 ----------

OVERLAP_PAIR = {"src": "常野推开柴房的门，里面堆着喂马的草料，他挨着草料堆坐下。",
                "dst": "常野推开柴房门，里头堆着喂马的草料，他挨着草料堆坐下。", "note": ""}


def test_sample_pairs_drops_pairs_overlapping_window() -> None:
    """src 或 dst 与当前窗重合 12 字以上的对剔除(OVERLAP_PAIR 两头都重合)。"""
    picked = sample_pairs([OVERLAP_PAIR, PAIR_A], WINDOW)
    assert picked == [PAIR_A]


def test_sample_pairs_caps_at_limit() -> None:
    many = [{"src": f"第{i}段原文，他做了{i}件事。", "dst": f"第{i}段改文，他干{i}件事。"}
            for i in range(20)]
    picked = sample_pairs(many, WINDOW)
    assert len(picked) == 12 and picked == many[:12]   # 顺序取样,确定性


def test_sample_pairs_short_window_keeps_all() -> None:
    """窗比重合判定长度还短,无从重合,只截上限。"""
    picked = sample_pairs([PAIR_A, PAIR_B], "短窗。")
    assert picked == [PAIR_A, PAIR_B]
