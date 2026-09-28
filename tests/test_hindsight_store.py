"""HindsightMemoryStore: RETAIN/RECALL request construction and error mapping.

The `hindsight_client.Hindsight` class is patched out entirely; no network call
is made. Assertions check the exact kwargs our code sends, since a subtly wrong
tag or timestamp would silently break recall precision or history integrity.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from hindsight_client_api.exceptions import ServiceException, UnauthorizedException

from app.config.settings import Settings
from app.domain.errors import MemoryAuthError, MemoryServiceError, MemoryTimeoutError
from app.domain.models import DecisionKind, DecisionRecord
from app.memory.hindsight_store import HindsightMemoryStore
from tests.conftest import make_recall_result


def _build_store(fake_settings: Settings) -> tuple[HindsightMemoryStore, MagicMock]:
    with patch("app.memory.hindsight_store.Hindsight") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        store = HindsightMemoryStore(fake_settings)
    return store, mock_instance


def _decision(**overrides: object) -> DecisionRecord:
    kwargs = {
        "entity": "search_api.rate_limit",
        "decision": "Rate limit set to 100 rps.",
        "reason": "Elasticsearch was unstable above 100 rps.",
        "author": "Priya Raman",
        "occurred_at": datetime(2023, 4, 11, tzinfo=timezone.utc),
    }
    kwargs.update(overrides)
    return DecisionRecord(**kwargs)


# -- RETAIN construction ------------------------------------------------------


def test_retain_sends_entity_tag_and_metadata(fake_settings: Settings) -> None:
    store, mock_instance = _build_store(fake_settings)
    mock_instance.retain.return_value = SimpleNamespace(success=True)

    store.retain_decision(_decision())

    _, kwargs = mock_instance.retain.call_args
    assert kwargs["bank_id"] == "test-bank"
    assert "entity:search_api.rate_limit" in kwargs["tags"]
    assert kwargs["metadata"]["entity"] == "search_api.rate_limit"
    assert kwargs["metadata"]["author"] == "Priya Raman"
    assert kwargs["metadata"]["kind"] == "original"
    assert kwargs["timestamp"] == datetime(2023, 4, 11, tzinfo=timezone.utc)
    assert "search_api.rate_limit" in kwargs["content"]
    assert "Elasticsearch was unstable" in kwargs["content"]


def test_retain_update_uses_distinct_document_id_from_original(fake_settings: Settings) -> None:
    store, mock_instance = _build_store(fake_settings)
    mock_instance.retain.return_value = SimpleNamespace(success=True)

    store.retain_decision(_decision(kind=DecisionKind.ORIGINAL))
    first_id = mock_instance.retain.call_args.kwargs["document_id"]

    store.retain_decision(_decision(kind=DecisionKind.UPDATE, decision="Still 100.",
                                     reason="Constraint resolved."))
    second_id = mock_instance.retain.call_args.kwargs["document_id"]

    assert first_id != second_id
    assert mock_instance.retain.call_args.kwargs["metadata"]["kind"] == "update"


def test_retain_omits_empty_evidence_from_metadata(fake_settings: Settings) -> None:
    store, mock_instance = _build_store(fake_settings)
    mock_instance.retain.return_value = SimpleNamespace(success=True)

    store.retain_decision(_decision(evidence=None))

    assert "evidence" not in mock_instance.retain.call_args.kwargs["metadata"]


# -- RECALL construction -------------------------------------------------------


def test_recall_merges_broad_and_entity_scoped_results(fake_settings: Settings) -> None:
    store, mock_instance = _build_store(fake_settings)
    broad = SimpleNamespace(results=[make_recall_result(memory_id="broad-1")])
    scoped = SimpleNamespace(
        results=[make_recall_result(memory_id="broad-1"), make_recall_result(memory_id="scoped-2")]
    )
    mock_instance.recall.side_effect = [broad, scoped]

    memories = store.recall_for_question(
        "Why is search_api.rate_limit 100?", "search_api.rate_limit"
    )

    ids = {m.memory_id for m in memories}
    assert ids == {"broad-1", "scoped-2"}
    assert mock_instance.recall.call_count == 2
    scoped_kwargs = mock_instance.recall.call_args_list[1].kwargs
    assert scoped_kwargs["tags"] == ["entity:search_api.rate_limit"]
    assert scoped_kwargs["tags_match"] == "any_strict"


def test_recall_for_question_without_entity_hint_runs_single_query(fake_settings: Settings) -> None:
    store, mock_instance = _build_store(fake_settings)
    mock_instance.recall.return_value = SimpleNamespace(results=[])

    store.recall_for_question("Why is the timeout so long?", None)

    assert mock_instance.recall.call_count == 1


def test_recall_returns_empty_list_when_no_results(fake_settings: Settings) -> None:
    store, mock_instance = _build_store(fake_settings)
    mock_instance.recall.return_value = SimpleNamespace(results=[])

    memories = store.recall_for_question("Why is nothing recorded?", None)

    assert memories == []


def test_recall_result_mapping_reads_expected_fields(fake_settings: Settings) -> None:
    store, mock_instance = _build_store(fake_settings)
    result = make_recall_result(
        memory_id="mem-42",
        text="Rate limit introduced because of ES instability.",
        occurred_start="2023-04-11T10:00:00Z",
        metadata={"author": "Priya Raman", "entity": "search_api.rate_limit", "kind": "original"},
    )
    mock_instance.recall.return_value = SimpleNamespace(results=[result])

    memories = store.recall_for_question("why", None)

    memory = memories[0]
    assert memory.memory_id == "mem-42"
    assert memory.author == "Priya Raman"
    assert memory.entity == "search_api.rate_limit"
    assert memory.kind is DecisionKind.ORIGINAL
    assert memory.occurred_at == datetime(2023, 4, 11, 10, 0, tzinfo=timezone.utc)


# -- error mapping --------------------------------------------------------------


def test_unauthorized_maps_to_memory_auth_error(fake_settings: Settings) -> None:
    store, mock_instance = _build_store(fake_settings)
    mock_instance.recall.side_effect = UnauthorizedException(status=401, reason="Unauthorized")
    with pytest.raises(MemoryAuthError):
        store.recall_for_question("why", None)


def test_service_exception_maps_to_memory_service_error(fake_settings: Settings) -> None:
    store, mock_instance = _build_store(fake_settings)
    mock_instance.recall.side_effect = ServiceException(status=503, reason="Unavailable")
    with pytest.raises(MemoryServiceError):
        store.recall_for_question("why", None)


def test_generic_timeout_message_maps_to_memory_timeout_error(fake_settings: Settings) -> None:
    store, mock_instance = _build_store(fake_settings)
    mock_instance.recall.side_effect = TimeoutError("Request timed out after 60s")
    with pytest.raises(MemoryTimeoutError):
        store.recall_for_question("why", None)


def test_unexpected_exception_maps_to_generic_memory_service_error(fake_settings: Settings) -> None:
    store, mock_instance = _build_store(fake_settings)
    mock_instance.recall.side_effect = RuntimeError("something odd")
    with pytest.raises(MemoryServiceError):
        store.recall_for_question("why", None)
