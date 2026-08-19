"""F4 (P8-M3R-fix) — scripts/blind_shuffle.py 盲测物料封装工具 TDD 测试。

工具行为(见 specs/P8-M3R-fix.md §F4):
- 输入 N 份 md → 随机天干标签(甲-癸,最多 10)shuffle 后复制到 out-dir/<label>.md
- mapping 写到 seal-dir/<task>_mapping.json(密封目录,默认 _mapping_sealed/)
- **stdout 只打物料路径(out-dir/<label>.md),不打映射内容**(防揭盲前泄漏)
- 超 10 份报错退出码非 0

零烧钱,纯 stdlib 测试。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "blind_shuffle.py"


def _run(args: list[str], **kw) -> subprocess.CompletedProcess:
    """跑 blind_shuffle.py 脚本,返 CompletedProcess。"""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        **kw,
    )


@pytest.fixture
def three_md_files(tmp_path: Path) -> list[Path]:
    """3 份假 md 物料(模拟盲测输入)。"""
    files = []
    for i, name in enumerate(["alpha.md", "beta.md", "gamma.md"]):
        p = tmp_path / "src" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        # 内容含 source 关键字(测 stdout 不泄漏)
        p.write_text(f"# 物料 {name}\nsource: deepseek-v4-pro\nmodel_xxx\n", encoding="utf-8")
        files.append(p)
    return files


# ---------------------------------------------------------------------------
# T4.1 输出数量 + mapping 结构
# ---------------------------------------------------------------------------


class TestShuffleOutputCount:
    """输入 N → 输出 N 副本 + mapping.json labels 含 N 条。"""

    def test_three_inputs_produce_three_outputs(self, three_md_files, tmp_path):
        out_dir = tmp_path / "washed"
        seal_dir = tmp_path / "_seal"
        result = _run([
            "--task", "B5",
            "--in", *[str(p) for p in three_md_files],
            "--out-dir", str(out_dir),
            "--seal-dir", str(seal_dir),
        ])
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        # out_dir 含 3 份 .md
        washed = list(out_dir.glob("*.md"))
        assert len(washed) == 3, f"期望 3 份输出,实际 {len(washed)}: {washed}"

    def test_mapping_json_has_n_labels(self, three_md_files, tmp_path):
        out_dir = tmp_path / "washed"
        seal_dir = tmp_path / "_seal"
        result = _run([
            "--task", "B5",
            "--in", *[str(p) for p in three_md_files],
            "--out-dir", str(out_dir),
            "--seal-dir", str(seal_dir),
        ])
        assert result.returncode == 0
        mapping_file = seal_dir / "B5_mapping.json"
        assert mapping_file.exists(), f"mapping 文件未生成: {mapping_file}"
        data = json.loads(mapping_file.read_text(encoding="utf-8"))
        assert "labels" in data, f"mapping 缺 labels 字段: {data.keys()}"
        assert len(data["labels"]) == 3, f"labels 应有 3 条,实际 {len(data['labels'])}"


# ---------------------------------------------------------------------------
# T4.2 stdout 不泄漏映射内容
# ---------------------------------------------------------------------------


class TestStdoutNoLeak:
    """stdout 只打物料路径,不含 source_path / 原 filename / model 关键字。"""

    def test_stdout_no_source_filename(self, three_md_files, tmp_path):
        out_dir = tmp_path / "washed"
        seal_dir = tmp_path / "_seal"
        result = _run([
            "--task", "B5",
            "--in", *[str(p) for p in three_md_files],
            "--out-dir", str(out_dir),
            "--seal-dir", str(seal_dir),
        ])
        assert result.returncode == 0
        # 原 filename(alpha.md/beta.md/gamma.md)不该出现在 stdout
        for src in three_md_files:
            assert src.name not in result.stdout, (
                f"stdout 泄漏原文件名 {src.name}: {result.stdout!r}"
            )

    def test_stdout_no_md_content_keywords(self, three_md_files, tmp_path):
        """md 文件内容里含 'deepseek' / 'model_xxx',stdout 不该泄漏。

        注:测试函数名不含被禁关键字,避免 pytest 临时目录名带这些字混进 path。
        """
        out_dir = tmp_path / "washed"
        seal_dir = tmp_path / "_seal"
        result = _run([
            "--task", "B5",
            "--in", *[str(p) for p in three_md_files],
            "--out-dir", str(out_dir),
            "--seal-dir", str(seal_dir),
        ])
        assert result.returncode == 0
        blacklist = ["deepseek", "model_xxx", "source:"]
        for word in blacklist:
            assert word not in result.stdout.lower(), (
                f"stdout 含泄漏关键字 {word!r}: {result.stdout!r}"
            )

    def test_stdout_only_has_washed_paths(self, three_md_files, tmp_path):
        """stdout 每行是 out_dir 下的 .md 路径(可解析为现存文件)。"""
        out_dir = tmp_path / "washed"
        seal_dir = tmp_path / "_seal"
        result = _run([
            "--task", "B5",
            "--in", *[str(p) for p in three_md_files],
            "--out-dir", str(out_dir),
            "--seal-dir", str(seal_dir),
        ])
        assert result.returncode == 0
        lines = [ln.strip() for ln in result.stdout.strip().split("\n") if ln.strip()]
        assert len(lines) == 3, f"stdout 行数应=输入数 3,实际 {len(lines)}: {lines!r}"
        for ln in lines:
            p = Path(ln)
            assert p.exists(), f"stdout 路径不存在: {ln}"
            # 应在 out_dir 下
            try:
                p.relative_to(out_dir.resolve())
            except ValueError as e:
                pytest.fail(f"stdout 路径不在 out_dir 下: {ln} (out_dir={out_dir}) {e}")


# ---------------------------------------------------------------------------
# T4.3 双射性(每输入 → 唯一标签,标签集大小 = 输入数)
# ---------------------------------------------------------------------------


class TestShuffleBijection:
    """随机双射:每输入对应唯一标签,标签不重复,标签集大小 = 输入数。"""

    def test_labels_are_unique(self, three_md_files, tmp_path):
        out_dir = tmp_path / "washed"
        seal_dir = tmp_path / "_seal"
        result = _run([
            "--task", "B5",
            "--in", *[str(p) for p in three_md_files],
            "--out-dir", str(out_dir),
            "--seal-dir", str(seal_dir),
        ])
        assert result.returncode == 0
        data = json.loads((seal_dir / "B5_mapping.json").read_text(encoding="utf-8"))
        labels = list(data["labels"].keys())
        assert len(labels) == len(set(labels)), f"标签重复: {labels}"
        assert len(labels) == 3

    def test_each_input_mapped_exactly_once(self, three_md_files, tmp_path):
        out_dir = tmp_path / "washed"
        seal_dir = tmp_path / "_seal"
        result = _run([
            "--task", "B5",
            "--in", *[str(p) for p in three_md_files],
            "--out-dir", str(out_dir),
            "--seal-dir", str(seal_dir),
        ])
        assert result.returncode == 0
        data = json.loads((seal_dir / "B5_mapping.json").read_text(encoding="utf-8"))
        # 每份输入文件出现在 labels.source_path 一次
        sources_in_mapping = []
        for entry in data["labels"].values():
            if "source_path" in entry:
                sources_in_mapping.append(Path(entry["source_path"]).name)
        src_names = [p.name for p in three_md_files]
        assert sorted(sources_in_mapping) == sorted(src_names), (
            f"映射缺输入或重复: 映射={sources_in_mapping}, 输入={src_names}"
        )

    def test_washed_label_paths_in_mapping_match_stdout(self, three_md_files, tmp_path):
        """stdout 行 = mapping 中 washed_label_path 集合(两者一致)。"""
        out_dir = tmp_path / "washed"
        seal_dir = tmp_path / "_seal"
        result = _run([
            "--task", "B5",
            "--in", *[str(p) for p in three_md_files],
            "--out-dir", str(out_dir),
            "--seal-dir", str(seal_dir),
        ])
        assert result.returncode == 0
        data = json.loads((seal_dir / "B5_mapping.json").read_text(encoding="utf-8"))
        washed_in_mapping = set()
        for entry in data["labels"].values():
            if "washed_label_path" in entry:
                washed_in_mapping.add(Path(entry["washed_label_path"]).resolve())
        stdout_paths = {Path(ln.strip()).resolve() for ln in result.stdout.strip().split("\n") if ln.strip()}
        assert washed_in_mapping == stdout_paths, (
            f"mapping.washed_label_path 与 stdout 不一致:\n"
            f"  mapping: {washed_in_mapping}\n  stdout: {stdout_paths}"
        )


# ---------------------------------------------------------------------------
# T4.4 超 10 份报错
# ---------------------------------------------------------------------------


class TestOverLimitError:
    """天干标签(10 个)不够时退出码非 0 + 友好错误消息。"""

    def test_eleven_inputs_fail(self, tmp_path):
        # 造 11 份假 md
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        files = []
        for i in range(11):
            p = src_dir / f"file_{i:02d}.md"
            p.write_text(f"# file {i}\n", encoding="utf-8")
            files.append(p)

        out_dir = tmp_path / "washed"
        seal_dir = tmp_path / "_seal"
        result = _run([
            "--task", "B5",
            "--in", *[str(p) for p in files],
            "--out-dir", str(out_dir),
            "--seal-dir", str(seal_dir),
        ])
        assert result.returncode != 0, f"11 份应失败,实际成功: stdout={result.stdout}"
        # 错误消息含数字提示("10")和友好说明
        combined = (result.stderr + result.stdout).lower()
        assert "10" in combined or "too many" in combined or "exceed" in combined, (
            f"错误消息未提示 10 份上限: stderr={result.stderr!r} stdout={result.stdout!r}"
        )

    def test_no_files_written_on_over_limit(self, tmp_path):
        """超 10 份时不应部分写出(原子性:要么全做,要么都不做)。"""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        files = []
        for i in range(11):
            p = src_dir / f"file_{i:02d}.md"
            p.write_text(f"# file {i}\n", encoding="utf-8")
            files.append(p)

        out_dir = tmp_path / "washed"
        seal_dir = tmp_path / "_seal"
        _run([
            "--task", "B5",
            "--in", *[str(p) for p in files],
            "--out-dir", str(out_dir),
            "--seal-dir", str(seal_dir),
        ])
        if out_dir.exists():
            leaked = list(out_dir.glob("*.md"))
            assert leaked == [], f"超限后不应部分写出,实际泄漏: {leaked}"


# ---------------------------------------------------------------------------
# T4.5 可选:seed 复现性(同一 seed → 同一映射)
# ---------------------------------------------------------------------------


class TestSeedReproducibility:
    """同 seed → 同映射(便于复现/审计);不同 seed → 大概率不同。"""

    def test_same_seed_same_mapping(self, three_md_files, tmp_path):
        out_a = tmp_path / "washed_a"
        out_b = tmp_path / "washed_b"
        seal_a = tmp_path / "_seal_a"
        seal_b = tmp_path / "_seal_b"

        common_args = ["--task", "B5", "--in", *[str(p) for p in three_md_files]]
        r1 = _run(common_args + ["--out-dir", str(out_a), "--seal-dir", str(seal_a), "--seed", "42"])
        r2 = _run(common_args + ["--out-dir", str(out_b), "--seal-dir", str(seal_b), "--seed", "42"])
        assert r1.returncode == 0 and r2.returncode == 0

        m1 = json.loads((seal_a / "B5_mapping.json").read_text(encoding="utf-8"))
        m2 = json.loads((seal_b / "B5_mapping.json").read_text(encoding="utf-8"))
        # 同 seed:输入 → 标签映射应一致(按 source_path 比对标签)
        map1 = {e["source_path"]: lbl for lbl, e in m1["labels"].items()}
        map2 = {e["source_path"]: lbl for lbl, e in m2["labels"].items()}
        assert map1 == map2, f"同 seed 42 但映射不一致:\n  {map1}\n  {map2}"
