"""ArchaeologistAgent: the orchestration of RECALL -> synthesis -> drift.

The store and LLM client are both fakes here (not mocks of the SDK boundary -
that is covered in test_hindsight_store.py and test_llm_client.py). This file
tests the agent's own logic: honest-unknown behaviour, id-filtering against
hallucinated citations, and graceful degradation when the LLM is unavailable.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.agent.archaeologist import ArchaeologistAgent
from app.domain.errors import LLMResponseError, MemoryServiceError, ValidationError
from app.domain.models import DecisionKind, DriftStatus, RecalledMemory


class FakeStore:
    def __init__(self, memories: list[RecalledMemory] | None = None,
                 raise_on_recall: Exception | None = None) -> None:
        self._memories = memories or []
        self._raise_on_recall = raise_on_recall
        self.retained: list[object] = []

    def recall_for_question(self, question: str, entity_hint: str | None) -> list[RecalledMemory]:
        if self._raise_on_recall:
            raise self._raise_on_recall
        return list(self._memories)

    def recall_entity_history(self, entity: str) -> list[RecalledMemory]:
        return list(self._memories)

    def retain_decision(self, record: object) -> str:
        self.retained.append(record)
        return "fake-document-id"


class FakeLLM:
    def __init__(self, payload: dict | None = None, raise_error: Exception | None = None) -> None:
        self._payload = payload
        self._raise_error = raise_error
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict:
        self.calls.append((system_prompt, user_prompt))
        if self._raise_error:
            raise self._raise_error
        return self._payload or {}


def _memory(memory_id: str = "mem-1", **overrides: object) -> RecalledMemory:
    kwargs = {
        "memory_id": memory_id,
        "text": "Rate limit introduced because Elasticsearch was unstable above 100 rps.",
        "occurred_at": datetime(2023, 4, 11, tzinfo=timezone.utc),
        "metadata": {
            "author": "Priya Raman",
            "entity": "search_api.rate_limit",
            "kind": "original",
        },
    }
    kwargs.update(overrides)
    return RecalledMemory(**kwargs)


# -- honest unknown state ------------------------------------------------------


def test_ask_with_no_memory_returns_honest_unknown() -> None:
    agent = ArchaeologistAgent(FakeStore(memories=[]), FakeLLM())
    result = agent.ask("Why is search_api.rate_limit 100?")

    assert result.has_memory is False
    assert "don't have recorded historical context" in result.answer
    assert result.memories == []


def test_ask_does_not_call_llm_when_no_memory() -> None:
    llm = FakeLLM()
    agent = ArchaeologistAgent(FakeStore(memories=[]), llm)
    agent.ask("Why is search_api.rate_limit 100?")
    assert llm.calls == []


# -- input validation -----------------------------------------------------------


def test_ask_rejects_empty_question() -> None:
    agent = ArchaeologistAgent(FakeStore(), FakeLLM())
    with pytest.raises(ValidationError):
        agent.ask("   ")


# -- grounded synthesis happy path ----------------------------------------------


def test_ask_returns_grounded_answer_and_timeline() -> None:
    memories = [_memory("mem-1")]
    payload = {
        "answer": (
            "Introduced by Priya Raman on 2023-04-11 because Elasticsearch was "
            "unstable above 100 rps."
        ),
        "drift_status": "no_evidence",
        "drift_rationale": "",
        "drift_memory_ids": [],
        "conflicts": [],
    }
    agent = ArchaeologistAgent(FakeStore(memories=memories), FakeLLM(payload))

    result = agent.ask("Why is search_api.rate_limit 100?")

    assert result.has_memory is True
    assert "Priya Raman" in result.answer
    assert len(result.timeline) == 1
    assert result.timeline[0].memory_id == "mem-1"
    assert result.drift.status is DriftStatus.NO_EVIDENCE


def test_ask_passes_chronologically_ordered_memories_to_llm() -> None:
    newer = _memory("new", occurred_at=datetime(2024, 8, 2, tzinfo=timezone.utc))
    older = _memory("old", occurred_at=datetime(2023, 4, 11, tzinfo=timezone.utc))
    llm = FakeLLM({"answer": "ok"})
    agent = ArchaeologistAgent(FakeStore(memories=[newer, older]), llm)

    agent.ask("Why is search_api.rate_limit still 100?")

    _, user_prompt = llm.calls[0]
    assert user_prompt.index("id: old") < user_prompt.index("id: new")


# -- decision drift ---------------------------------------------------------------


def test_drift_status_may_be_outdated_is_surfaced() -> None:
    memories = [
        _memory("mem-1"),
        _memory("mem-2", text="Elasticsearch was upgraded; constraint resolved."),
    ]
    payload = {
        "answer": (
            "The original constraint was resolved after an upgrade, but the "
            "limit is unchanged."
        ),
        "drift_status": "may_be_outdated",
        "drift_rationale": (
            "Elasticsearch was upgraded per mem-2, yet the limit was not revisited."
        ),
        "drift_memory_ids": ["mem-1", "mem-2"],
        "conflicts": [],
    }
    agent = ArchaeologistAgent(FakeStore(memories=memories), FakeLLM(payload))

    result = agent.ask("Why is search_api.rate_limit still 100?")

    assert result.drift.status is DriftStatus.MAY_BE_OUTDATED
    assert result.drift.supporting_memory_ids == ["mem-1", "mem-2"]


def test_drift_citation_of_unknown_memory_id_is_dropped() -> None:
    memories = [_memory("mem-1")]
    payload = {
        "answer": "ok",
        "drift_status": "needs_review",
        "drift_rationale": "hallucinated citation",
        "drift_memory_ids": ["mem-1", "mem-does-not-exist"],
        "conflicts": [],
    }
    agent = ArchaeologistAgent(FakeStore(memories=memories), FakeLLM(payload))

    result = agent.ask("why?")

    assert result.drift.supporting_memory_ids == ["mem-1"]


def test_unrecognised_drift_status_defaults_to_no_evidence() -> None:
    memories = [_memory("mem-1")]
    payload = {"answer": "ok", "drift_status": "definitely_wrong", "conflicts": []}
    agent = ArchaeologistAgent(FakeStore(memories=memories), FakeLLM(payload))

    result = agent.ask("why?")

    assert result.drift.status is DriftStatus.NO_EVIDENCE


# -- conflicting memories ----------------------------------------------------------


def test_conflicts_are_surfaced_with_memory_ids() -> None:
    memories = [_memory("mem-1"), _memory("mem-2")]
    payload = {
        "answer": "Two memories disagree on whether the limit was ever raised.",
        "drift_status": "needs_review",
        "conflicts": [
            {"summary": "mem-1 says the limit stayed 100; mem-2 says it was raised to 150.",
             "memory_ids": ["mem-1", "mem-2"]}
        ],
    }
    agent = ArchaeologistAgent(FakeStore(memories=memories), FakeLLM(payload))

    result = agent.ask("why?")

    assert len(result.conflicts) == 1
    assert result.conflicts[0].memory_ids == ["mem-1", "mem-2"]


def test_malformed_conflicts_field_is_ignored_not_fatal() -> None:
    memories = [_memory("mem-1")]
    payload = {"answer": "ok", "conflicts": "not-a-list"}
    agent = ArchaeologistAgent(FakeStore(memories=memories), FakeLLM(payload))

    result = agent.ask("why?")

    assert result.conflicts == []


# -- malformed / unavailable LLM ---------------------------------------------------


def test_llm_failure_degrades_to_raw_evidence_not_a_crash() -> None:
    memories = [_memory("mem-1")]
    agent = ArchaeologistAgent(
        FakeStore(memories=memories), FakeLLM(raise_error=LLMResponseError("bad json"))
    )

    result = agent.ask("why?")

    assert result.has_memory is True
    assert result.degraded_reason is not None
    assert result.memories == memories
    assert len(result.timeline) == 1


def test_missing_answer_field_falls_back_to_safe_message() -> None:
    memories = [_memory("mem-1")]
    llm = FakeLLM({"drift_status": "no_evidence"})
    agent = ArchaeologistAgent(FakeStore(memories=memories), llm)

    result = agent.ask("why?")

    assert result.has_memory is True
    assert result.answer  # non-empty fallback text, not a crash


# -- Hindsight failure ---------------------------------------------------------------


def test_memory_service_failure_propagates() -> None:
    agent = ArchaeologistAgent(
        FakeStore(raise_on_recall=MemoryServiceError("down")), FakeLLM()
    )
    with pytest.raises(MemoryServiceError):
        agent.ask("why?")


# -- record decision -------------------------------------------------------------------


def test_record_decision_delegates_to_store() -> None:
    store = FakeStore()
    agent = ArchaeologistAgent(store, FakeLLM())
    from app.domain.models import DecisionRecord

    record = DecisionRecord(
        entity="search_api.rate_limit",
        decision="Set to 100 rps.",
        reason="Elasticsearch was unstable above 100 rps.",
        author="Priya Raman",
        occurred_at=datetime(2023, 4, 11, tzinfo=timezone.utc),
        kind=DecisionKind.ORIGINAL,
    )

    document_id = agent.record_decision(record)

    assert document_id == "fake-document-id"
    assert store.retained == [record]
