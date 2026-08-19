"""Tests for biyu.ui.env — 环境标记模块(P8-M1 T1).

覆盖:
- 默认(无 BIYU_ENV)→ test/灰
- BIYU_ENV=prod → prod/红
- 非法值 → fallback test/灰 + logging.warning(D-70 不沉默)
- 大小写不敏感(PROD/Prod/prod 都识别)
"""
from __future__ import annotations

import logging

import pytest

from biyu.ui.env import read_env


class TestReadEnv:
    def test_default_returns_test_when_no_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("BIYU_ENV", raising=False)
        result = read_env()
        assert result["level"] == "test"
        assert result["label"] == "测试"
        assert result["color"] == "#a8a8a8"

    def test_prod_env_returns_prod(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BIYU_ENV", "prod")
        result = read_env()
        assert result["level"] == "prod"
        assert result["label"] == "真书"
        assert result["color"] == "#a83232"

    def test_invalid_value_falls_back_to_test_and_warns(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        monkeypatch.setenv("BIYU_ENV", "production")
        with caplog.at_level(logging.WARNING, logger="biyu.ui.env"):
            result = read_env()
        assert result["level"] == "test"
        assert result["color"] == "#a8a8a8"
        # D-70:不沉默,要出声
        assert any("production" in rec.message for rec in caplog.records), (
            "非法 BIYU_ENV 值应在 logging.WARNING 出声"
        )

    @pytest.mark.parametrize("raw", ["PROD", "Prod", "pRoD"])
    def test_case_insensitive(
        self, monkeypatch: pytest.MonkeyPatch, raw: str
    ):
        monkeypatch.setenv("BIYU_ENV", raw)
        result = read_env()
        assert result["level"] == "prod"
