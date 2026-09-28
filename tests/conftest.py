"""Shared test fixtures.

Unit tests never touch a real Hindsight server or LLM provider: `fake_settings`
carries safe placeholder credentials, and `httpx2_request`/`httpx2_response`
build the request/response objects the `openai` SDK's exception classes need.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx2
import pytest

from app.config.settings import Settings


@pytest.fixture
def fake_settings() -> Settings:
    return Settings(
        hindsight_base_url="http://hindsight.test",
        hindsight_api_key="test-hindsight-key",
        hindsight_bank_id="test-bank",
        hindsight_recall_budget="mid",
        hindsight_recall_max_tokens=4096,
        llm_base_url="http://llm.test/v1",
        llm_api_key="test-llm-key",
        llm_model="test-model",
        llm_max_retries=0,
        log_level="ERROR",
    )


@pytest.fixture
def httpx2_request() -> httpx2.Request:
    return httpx2.Request("POST", "http://llm.test/v1/chat/completions")


@pytest.fixture
def httpx2_response(httpx2_request: httpx2.Request):
    def _make(status_code: int) -> httpx2.Response:
        return httpx2.Response(status_code, request=httpx2_request)

    return _make


def make_recall_result(
    *,
    memory_id: str = "mem-1",
    text: str = "Example fact.",
    memory_type: str = "world",
    context: str | None = None,
    tags: list[str] | None = None,
    entities: list[str] | None = None,
    occurred_start: str | None = None,
    mentioned_at: str | None = "2024-01-01T00:00:00Z",
    document_id: str | None = "doc-1",
    metadata: dict[str, str] | None = None,
    final_score: float | None = 0.9,
) -> SimpleNamespace:
    """A stand-in for hindsight_client_api.models.recall_result.RecallResult.

    Uses attribute access (SimpleNamespace) rather than the real SDK model so
    tests do not depend on its exact class, only on the attributes our mapping
    code reads via getattr.
    """
    return SimpleNamespace(
        id=memory_id,
        text=text,
        type=memory_type,
        context=context,
        tags=tags or [],
        entities=entities or [],
        occurred_start=occurred_start,
        occurred_end=None,
        mentioned_at=mentioned_at,
        document_id=document_id,
        metadata=metadata or {},
        scores=SimpleNamespace(final=final_score) if final_score is not None else None,
    )
