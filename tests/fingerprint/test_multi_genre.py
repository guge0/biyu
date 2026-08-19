"""multi_genre_test.py 单测 — mock 全部 LLM 调用."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from biyu.fingerprint.evaluation.multi_genre_test import run_multi_genre_test


def _make_fingerprint_file(tmp_dir: Path) -> str:
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


class TestMultiGenreTest:
    @patch("biyu.fingerprint.evaluation.multi_genre_test.generate_sync")
    @patch("biyu.fingerprint.evaluation.multi_genre_test.write_with_fingerprint")
    def test_basic_run(self, mock_write, mock_generate_sync):
        mock_write.return_value = ("生成的小说内容" * 100, {"cost": 0.01})

        review_result = json.dumps({
            "consistency_score": 4,
            "what_remains_same": ["句法节奏", "修辞习惯"],
            "what_differs": ["题材内容"],
            "verdict": "consistent",
        })
        mock_generate_sync.return_value = (review_result, {"cost": 0.005})

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            fp_path = _make_fingerprint_file(td_path)

            result = run_multi_genre_test(
                fingerprint_path=fp_path,
                output_dir=str(td_path / "output"),
            )

            assert result["consistency_score"] == 4
            assert result["verdict"] == "consistent"
            assert result["passed"] is True
            assert result["total_cost"] > 0

    @patch("biyu.fingerprint.evaluation.multi_genre_test.generate_sync")
    @patch("biyu.fingerprint.evaluation.multi_genre_test.write_with_fingerprint")
    def test_three_genres_written(self, mock_write, mock_generate_sync):
        mock_write.return_value = ("内容" * 100, {"cost": 0.01})
        mock_generate_sync.return_value = (json.dumps({
            "consistency_score": 3,
            "what_remains_same": [],
            "what_differs": [],
            "verdict": "partially_consistent",
        }), {"cost": 0.005})

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            fp_path = _make_fingerprint_file(td_path)

            result = run_multi_genre_test(
                fingerprint_path=fp_path,
                output_dir=str(td_path / "output"),
            )

            assert mock_write.call_count == 3
            assert "modern" in result["char_counts"]
            assert "xuanhuan" in result["char_counts"]
            assert "scifi" in result["char_counts"]

    @patch("biyu.fingerprint.evaluation.multi_genre_test.generate_sync")
    @patch("biyu.fingerprint.evaluation.multi_genre_test.write_with_fingerprint")
    def test_output_files_created(self, mock_write, mock_generate_sync):
        mock_write.return_value = ("内容" * 100, {"cost": 0.01})
        mock_generate_sync.return_value = (json.dumps({
            "consistency_score": 5,
            "what_remains_same": ["风格"],
            "what_differs": [],
            "verdict": "consistent",
        }), {"cost": 0.005})

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            fp_path = _make_fingerprint_file(td_path)
            out_dir = td_path / "output"

            run_multi_genre_test(
                fingerprint_path=fp_path,
                output_dir=str(out_dir),
            )

            assert (out_dir / "output_modern.txt").exists()
            assert (out_dir / "output_xuanhuan.txt").exists()
            assert (out_dir / "output_scifi.txt").exists()
            assert (out_dir / "multi_genre_result.json").exists()
