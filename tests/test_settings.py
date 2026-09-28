"""Configuration validation and the missing-config reporting used by the UI."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config.settings import Settings


def test_blank_api_keys_are_treated_as_unset() -> None:
    settings = Settings(llm_api_key="   ", hindsight_api_key="")
    assert settings.llm_api_key is None
    assert settings.hindsight_api_key is None


def test_missing_llm_key_is_reported() -> None:
    settings = Settings(llm_api_key=None, hindsight_base_url="http://localhost:8888")
    problems = settings.missing_requirements()
    assert any("LLM_API_KEY" in p for p in problems)


def test_remote_hindsight_without_key_is_reported() -> None:
    settings = Settings(
        llm_api_key="present",
        hindsight_base_url="https://cloud.hindsight.example.com",
        hindsight_api_key=None,
    )
    problems = settings.missing_requirements()
    assert any("HINDSIGHT_API_KEY" in p for p in problems)


def test_local_hindsight_without_key_is_not_reported() -> None:
    settings = Settings(
        llm_api_key="present",
        hindsight_base_url="http://localhost:8888",
        hindsight_api_key=None,
    )
    problems = settings.missing_requirements()
    assert not any("HINDSIGHT_API_KEY" in p for p in problems)


def test_fully_configured_has_no_problems() -> None:
    settings = Settings(
        llm_api_key="present",
        hindsight_base_url="http://localhost:8888",
        hindsight_api_key=None,
    )
    assert settings.missing_requirements() == []


def test_invalid_base_url_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(hindsight_base_url="not-a-url")


def test_invalid_log_level_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(log_level="VERY_LOUD")


def test_invalid_recall_budget_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(hindsight_recall_budget="extreme")


def test_describe_redacted_never_contains_secret_values() -> None:
    settings = Settings(llm_api_key="super-secret-value", hindsight_api_key="also-secret")
    described = settings.describe_redacted()
    rendered = " ".join(described.values())
    assert "super-secret-value" not in rendered
    assert "also-secret" not in rendered
    assert described["LLM API key"] == "set"
