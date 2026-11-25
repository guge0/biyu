"""S-7b：诊断包不含 Key 明文与书稿正文。"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from biyu.ui.diagnostics import build_diagnostics_zip, redact_config, scrub_text

FAKE_KEY = "sk-FAKEKEY1234567890abcdef"
MANUSCRIPT = "这是一段绝不能出现在诊断包里的书稿正文特征串甲乙丙丁"


def _seed(root: Path) -> Path:
    book = root / "测试书"
    (book / "logs" / "ch1" / "runs").mkdir(parents=True)
    (book / "chapters" / "_pending").mkdir(parents=True)
    (book / "chapters" / "ch1.md").write_text(MANUSCRIPT, encoding="utf-8")
    (book / "chapters" / "_pending" / "ch1.md").write_text(MANUSCRIPT, encoding="utf-8")
    (book / "logs" / "ch1" / "planning.md").write_text(MANUSCRIPT, encoding="utf-8")
    (book / "logs" / "cost_log.csv").write_text("timestamp,chapter,stage,cost_cny\nt,1,writer,0.06\n", encoding="utf-8")
    (book / "logs" / "ch1" / "runs" / "r1.log").write_text(
        f"argv=write\n  [2/4] OK - 1s\n  key={FAKE_KEY}\n    [PASS] character_presence: 在场角色一致: 甲乙丙丁\n  {MANUSCRIPT}\n", encoding="utf-8"
    )
    (root / "cost_log.csv").write_text("timestamp,task\n", encoding="utf-8")
    cfg = root / "models.yaml"
    cfg.write_text(
        f"providers:\n  deepseek:\n    base_url: https://x\n    api_key: {FAKE_KEY}\n  glm:\n    api_key: ''\n",
        encoding="utf-8",
    )
    return cfg


def test_zip_has_no_key_and_no_manuscript(tmp_path: Path):
    cfg = _seed(tmp_path)
    data = build_diagnostics_zip(tmp_path, cfg)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        blob = "\n".join(zf.read(n).decode("utf-8") for n in names)
    assert FAKE_KEY not in blob
    assert MANUSCRIPT not in blob
    assert "测试书" not in "\n".join(names)  # 书名不进路径
    assert "***已配置***" in blob and "未配置" in blob
    assert any(n.startswith("运行日志/") for n in names)
    assert any(n.startswith("花费/") for n in names)


def test_redact_nested():
    out = redact_config({"a": {"api_key": "x", "token": ""}, "b": [{"secret": "y"}], "url": "u"})
    assert out == {"a": {"api_key": "***已配置***", "token": "未配置"}, "b": [{"secret": "***已配置***"}], "url": "u"}


def test_scrub_text():
    assert FAKE_KEY not in scrub_text(f"Bearer {FAKE_KEY}")
