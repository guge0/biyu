"""extractor.py 单测 — mock LLM 调用."""
import json
from unittest.mock import patch, MagicMock

import pytest

from biyu.fingerprint.extractor import extract_fingerprint


def _mock_llm_response():
    """构建 mock LLM JSON 返回."""
    return {
        "style_description": "这位作家的风格特点是喜欢用长句穿插短句，因为他追求情绪的潮汐感。"
        "他的对话往往带有知识分子的腔调，因为他笔下的人物多是受过教育的年轻人。"
        "战斗场景中他会冷不丁插入一段内心独白，因为他认为战斗不只是肉体碰撞，更是精神对抗。"
        "他的修辞是松散的、口语化的，因为他觉得刻意雕琢会打断阅读节奏。"
        "他擅长用具体物件承载情感，因为他信奉细节比形容词更有力量。"
        "他喜欢在叙事中穿插议论，因为他要和读者建立一种智识上的亲密感。"
        "他的结尾往往不收束而是留白，因为他相信未完比完结更令人难忘。" + "x" * 300,
        "exemplar_passages": [
            {
                "passage": "a" * 600,
                "why_representative": "这段展示了长句插短句的节奏感",
            }
            for _ in range(5)
        ],
        "ai_pitfalls": [
            {
                "pitfall": "AI 会过度使用排比",
                "why_it_happens": "因为 AI 觉得排比有文学性",
            }
            for _ in range(5)
        ],
    }


class TestExtractFingerprint:
    @patch("biyu.fingerprint.extractor._run_async")
    @patch("biyu.fingerprint.extractor.load_source")
    def test_basic_extraction(self, mock_load, mock_run):
        mock_load.return_value = "x" * 30000

        # mock _run_async 返回 (parsed_dict, usage)
        mock_run.return_value = (
            _mock_llm_response(),
            {"prompt_tokens": 1000, "completion_tokens": 2000, "cost": 0.01},
        )

        fp, usage = extract_fingerprint(
            source_path="fake/path",
            output_path="/tmp/test_fp.json",
            sample_size=8000,
        )

        assert fp.schema_version == 1
        assert fp.source_info.total_chars == 30000
        assert fp.source_info.sampling_method == "uniform"
        assert len(fp.exemplar_passages) == 5
        assert len(fp.ai_pitfalls) == 5
        assert usage["cost"] == 0.01

    @patch("biyu.fingerprint.extractor._run_async")
    @patch("biyu.fingerprint.extractor.load_source")
    def test_small_text_uses_full(self, mock_load, mock_run):
        mock_load.return_value = "x" * 5000

        mock_run.return_value = (
            _mock_llm_response(),
            {"prompt_tokens": 500, "completion_tokens": 1000, "cost": 0.005},
        )

        fp, usage = extract_fingerprint(
            source_path="fake/path",
            output_path="/tmp/test_fp2.json",
            sample_size=8000,
        )

        assert fp.source_info.sampling_method == "full"
        assert fp.source_info.sampled_chars == 5000

    @patch("biyu.fingerprint.extractor._run_async")
    @patch("biyu.fingerprint.extractor.load_source")
    def test_output_file_created(self, mock_load, mock_run, tmp_path):
        mock_load.return_value = "x" * 5000
        mock_run.return_value = (
            _mock_llm_response(),
            {"prompt_tokens": 500, "completion_tokens": 1000, "cost": 0.005},
        )

        out_path = str(tmp_path / "fp.json")
        fp, usage = extract_fingerprint(
            source_path="fake/path",
            output_path=out_path,
        )

        assert (tmp_path / "fp.json").exists()
        saved = json.loads((tmp_path / "fp.json").read_text(encoding="utf-8"))
        assert saved["schema_version"] == 1
