"""schema.py 单测 — Pydantic 模型校验."""
import pytest
from pydantic import ValidationError

from biyu.fingerprint.schema import (
    AiPitfall,
    ExemplarPassage,
    Fingerprint,
    SourceInfo,
)


def _valid_fingerprint(**overrides):
    """构建合法 Fingerprint 数据."""
    data = {
        "schema_version": 1,
        "extracted_at": "2026-05-15T00:00:00+00:00",
        "source_info": {
            "source_path": "data/test",
            "total_chars": 30000,
            "sampled_chars": 8000,
            "sampling_method": "uniform",
        },
        "style_description": "x" * 500,  # 500 字符
        "exemplar_passages": [
            {"passage": "y" * 600, "why_representative": "因为这段展示了特征"}
            for _ in range(5)
        ],
        "ai_pitfalls": [
            {"pitfall": "AI 会过度使用排比", "why_it_happens": "因为排比有文学性"}
            for _ in range(5)
        ],
    }
    data.update(overrides)
    return data


class TestSourceInfo:
    def test_valid(self):
        info = SourceInfo(
            source_path="data/test",
            total_chars=30000,
            sampled_chars=8000,
            sampling_method="uniform",
        )
        assert info.total_chars == 30000

    def test_negative_chars(self):
        with pytest.raises(ValidationError):
            SourceInfo(
                source_path="data/test",
                total_chars=-1,
                sampled_chars=0,
                sampling_method="uniform",
            )


class TestExemplarPassage:
    def test_valid(self):
        p = ExemplarPassage(
            passage="x" * 500,
            why_representative="这段展示了核心风格",
        )
        assert len(p.passage) == 500

    def test_too_short(self):
        with pytest.raises(ValidationError):
            ExemplarPassage(passage="short", why_representative="原因")

    def test_too_long(self):
        with pytest.raises(ValidationError):
            ExemplarPassage(passage="x" * 1501, why_representative="原因")

    def test_empty_why(self):
        with pytest.raises(ValidationError):
            ExemplarPassage(passage="x" * 500, why_representative="")

    def test_exactly_500(self):
        p = ExemplarPassage(passage="x" * 500, why_representative="原因")
        assert len(p.passage) == 500

    def test_exactly_1500(self):
        p = ExemplarPassage(passage="x" * 1500, why_representative="原因")
        assert len(p.passage) == 1500


class TestAiPitfall:
    def test_valid(self):
        p = AiPitfall(pitfall="AI 会过度排比", why_it_happens="因为排比看起来文学")
        assert p.pitfall

    def test_empty_why(self):
        with pytest.raises(ValidationError):
            AiPitfall(pitfall="问题", why_it_happens="")


class TestFingerprint:
    def test_valid_minimal(self):
        fp = Fingerprint.model_validate(_valid_fingerprint())
        assert fp.schema_version == 1
        assert len(fp.exemplar_passages) == 5
        assert len(fp.ai_pitfalls) == 5

    def test_style_description_too_short(self):
        with pytest.raises(ValidationError):
            Fingerprint.model_validate(_valid_fingerprint(style_description="short"))

    def test_style_description_too_long(self):
        with pytest.raises(ValidationError):
            Fingerprint.model_validate(_valid_fingerprint(style_description="x" * 3001))

    def test_too_few_exemplars(self):
        with pytest.raises(ValidationError):
            Fingerprint.model_validate(
                _valid_fingerprint(
                    exemplar_passages=[
                        {"passage": "x" * 600, "why_representative": "原因"}
                        for _ in range(4)
                    ]
                )
            )

    def test_too_many_exemplars(self):
        with pytest.raises(ValidationError):
            Fingerprint.model_validate(
                _valid_fingerprint(
                    exemplar_passages=[
                        {"passage": "x" * 600, "why_representative": "原因"}
                        for _ in range(9)
                    ]
                )
            )

    def test_too_few_pitfalls(self):
        with pytest.raises(ValidationError):
            Fingerprint.model_validate(
                _valid_fingerprint(
                    ai_pitfalls=[
                        {"pitfall": "问题", "why_it_happens": "原因"}
                        for _ in range(4)
                    ]
                )
            )

    def test_too_many_pitfalls(self):
        with pytest.raises(ValidationError):
            Fingerprint.model_validate(
                _valid_fingerprint(
                    ai_pitfalls=[
                        {"pitfall": "问题", "why_it_happens": "原因"}
                        for _ in range(11)
                    ]
                )
            )

    def test_exactly_400_chars_description(self):
        fp = Fingerprint.model_validate(_valid_fingerprint(style_description="x" * 400))
        assert len(fp.style_description) == 400

    def test_exactly_3000_chars_description(self):
        fp = Fingerprint.model_validate(_valid_fingerprint(style_description="x" * 3000))
        assert len(fp.style_description) == 3000

    def test_max_exemplars(self):
        fp = Fingerprint.model_validate(
            _valid_fingerprint(
                exemplar_passages=[
                    {"passage": "x" * 600, "why_representative": "原因"}
                    for _ in range(8)
                ]
            )
        )
        assert len(fp.exemplar_passages) == 8

    def test_max_pitfalls(self):
        fp = Fingerprint.model_validate(
            _valid_fingerprint(
                ai_pitfalls=[
                    {"pitfall": "问题", "why_it_happens": "原因"}
                    for _ in range(10)
                ]
            )
        )
        assert len(fp.ai_pitfalls) == 10
