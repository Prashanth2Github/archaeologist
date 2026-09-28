"""Decision validation rules."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.models import (
    MAX_TAGS,
    DecisionKind,
    DecisionRecord,
    entity_tag,
    normalize_entity,
)


def _base_kwargs(**overrides: object) -> dict:
    kwargs = {
        "entity": "search_api.rate_limit",
        "decision": "Rate limit set to 100 rps.",
        "reason": "Elasticsearch was unstable above 100 rps.",
        "author": "Priya Raman",
        "occurred_at": datetime(2023, 4, 11, tzinfo=timezone.utc),
    }
    kwargs.update(overrides)
    return kwargs


def test_valid_decision_record_constructs() -> None:
    record = DecisionRecord(**_base_kwargs())
    assert record.entity == "search_api.rate_limit"
    assert record.kind is DecisionKind.ORIGINAL


@pytest.mark.parametrize("entity", ["", "   ", "!!!bad", " /leading-slash", "a" * 121])
def test_invalid_entity_rejected(entity: str) -> None:
    with pytest.raises(ValidationError):
        DecisionRecord(**_base_kwargs(entity=entity))


def test_valid_entity_separators_accepted() -> None:
    record = DecisionRecord(**_base_kwargs(entity="services/auth:token_expiry"))
    assert record.entity == "services/auth:token_expiry"


@pytest.mark.parametrize("field", ["decision", "reason", "author"])
def test_required_text_fields_reject_blank(field: str) -> None:
    with pytest.raises(ValidationError):
        DecisionRecord(**_base_kwargs(**{field: "   "}))


def test_decision_length_limit_enforced() -> None:
    with pytest.raises(ValidationError):
        DecisionRecord(**_base_kwargs(decision="x" * 2001))


def test_reason_length_limit_enforced() -> None:
    with pytest.raises(ValidationError):
        DecisionRecord(**_base_kwargs(reason="x" * 4001))


def test_naive_datetime_is_assumed_utc() -> None:
    record = DecisionRecord(**_base_kwargs(occurred_at=datetime(2023, 4, 11)))
    assert record.occurred_at.tzinfo is not None


def test_blank_evidence_becomes_none() -> None:
    record = DecisionRecord(**_base_kwargs(evidence="   "))
    assert record.evidence is None


def test_tags_are_deduplicated_and_lowercased() -> None:
    record = DecisionRecord(**_base_kwargs(tags=["Security", "security", " Perf "]))
    assert record.tags == ["security", "perf"]


def test_too_many_tags_rejected() -> None:
    with pytest.raises(ValidationError):
        DecisionRecord(**_base_kwargs(tags=[f"tag{i}" for i in range(MAX_TAGS + 1)]))


def test_memory_tags_include_entity_scope() -> None:
    record = DecisionRecord(**_base_kwargs(tags=["security"]))
    assert record.memory_tags == ["entity:search_api.rate_limit", "security"]


def test_entity_tag_is_normalized() -> None:
    assert entity_tag("Search_API.Rate_Limit") == "entity:search_api.rate_limit"
    assert normalize_entity(" Search_API.Rate_Limit ") == "search_api.rate_limit"
