"""blind_test.py 单测 — mock 全部 LLM 调用."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from biyu.fingerprint.evaluation.blind_test import run_blind_test


def _make_fingerprint_file(tmp_dir: Path) -> str:
    """创建临时 fingerprint 文件."""
    data = {
        "schema_version": 1,
        "extracted_at": "2026-05-15T00:00:00+00:00",
        "source_info": {
            "source_path": "fake",
            "total_chars": 30000,
            "sampled_chars": 8000,
            "sampling_method": "uniform",
        },
        "style_description": "x" * 500,
        "exemplar_passages": [
            {"passage": "y" * 600, "why_representative": "原因"}
            for _ in range(5)
        ],
        "ai_pitfalls": [
            {"pitfall": "问题", "why_it_happens": "原因"}
            for _ in range(5)
        ],
    }
    fp_path = tmp_dir / "fp.json"
    fp_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(fp_path)


def _make_source_file(tmp_dir: Path) -> str:
    """创建临时源文本文件，包含足够长的段落."""
    paragraphs = []
    for i in range(20):
        paragraphs.append("段落" + str(i) + "的内容填充文字" * 100)
    src_path = tmp_dir / "source.txt"
    src_path.write_text("\n\n".join(paragraphs), encoding="utf-8")
    return str(src_path)


class TestBlindTest:
    @patch("biyu.fingerprint.evaluation.blind_test.generate_sync")
    @patch("biyu.fingerprint.evaluation.blind_test.write_with_fingerprint")
    def test_basic_run(self, mock_write, mock_generate_sync):
        mock_write.return_value = ("AI 生成的内容" * 100, {"cost": 0.01})

        review_result = json.dumps({
            "ai_generated_segment": "B",
            "confidence": "low",
            "key_evidence": ["不确定"],
        })
        mock_generate_sync.return_value = (review_result, {"cost": 0.005})

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            fp_path = _make_fingerprint_file(td_path)
            src_path = _make_source_file(td_path)

            results, summary = run_blind_test(
                fingerprint_path=fp_path,
                source_path=src_path,
                rounds=2,
                output_dir=str(td_path / "output"),
            )

            assert len(results) == 2
            assert "total_cost" in summary
            assert "error_rate" in summary

    @patch("biyu.fingerprint.evaluation.blind_test.generate_sync")
    @patch("biyu.fingerprint.evaluation.blind_test.write_with_fingerprint")
    def test_output_files_created(self, mock_write, mock_generate_sync):
        mock_write.return_value = ("AI 内容" * 100, {"cost": 0.01})
        review_result = json.dumps({
            "ai_generated_segment": "A",
            "confidence": "high",
            "key_evidence": ["test"],
        })
        mock_generate_sync.return_value = (review_result, {"cost": 0.005})

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            fp_path = _make_fingerprint_file(td_path)
            src_path = _make_source_file(td_path)
            out_dir = td_path / "output"

            run_blind_test(
                fingerprint_path=fp_path,
                source_path=src_path,
                rounds=1,
                output_dir=str(out_dir),
            )

            assert (out_dir / "blind_test_round_1.json").exists()
            assert (out_dir / "blind_test_summary.json").exists()
