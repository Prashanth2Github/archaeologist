"""Question validation and entity-hint extraction."""

from __future__ import annotations

import pytest

from app.agent.questions import extract_entity_hint, validate_question
from app.domain.errors import ValidationError
from app.domain.models import MAX_QUESTION_CHARS


def test_empty_question_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_question("")


def test_whitespace_only_question_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_question("     ")


def test_overlong_question_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_question("x" * (MAX_QUESTION_CHARS + 1))


def test_question_whitespace_is_collapsed() -> None:
    assert validate_question("  why   is   this   100?  ") == "why is this 100?"


def test_entity_hint_found_in_dotted_identifier() -> None:
    assert extract_entity_hint("Why is search_api.rate_limit still 100?") == "search_api.rate_limit"


def test_entity_hint_none_for_plain_prose() -> None:
    assert extract_entity_hint("Why is the rate limit 100?") is None


def test_entity_hint_ignores_common_abbreviations() -> None:
    assert extract_entity_hint("e.g. this is just an example") is None


def test_entity_hint_ignores_urls() -> None:
    assert extract_entity_hint("see https://example.com/docs for details") is None


def test_entity_hint_strips_trailing_punctuation() -> None:
    assert extract_entity_hint("why is auth.token_expiry?") == "auth.token_expiry"
