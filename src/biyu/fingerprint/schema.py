"""声纹数据结构 — Pydantic schema."""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class SourceInfo(BaseModel):
    source_path: str
    total_chars: int = Field(ge=0)
    sampled_chars: int = Field(ge=0)
    sampling_method: str


class ExemplarPassage(BaseModel):
    passage: str = Field(min_length=500, max_length=1500)
    why_representative: str = Field(min_length=1)


class AiPitfall(BaseModel):
    pitfall: str = Field(min_length=1)
    why_it_happens: str = Field(min_length=1)


class Fingerprint(BaseModel):
    schema_version: int = 1
    extracted_at: str
    source_info: SourceInfo
    style_description: str = Field(min_length=400, max_length=3000)
    exemplar_passages: list[ExemplarPassage] = Field(min_length=5, max_length=8)
    ai_pitfalls: list[AiPitfall] = Field(min_length=5, max_length=10)
