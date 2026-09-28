"""Chronological ordering is computed deterministically, never by the LLM."""

from __future__ import annotations

from datetime import datetime, timezone

from app.agent.timeline import build_timeline, sort_memories_chronologically
from app.domain.models import RecalledMemory

_DEFAULT_MENTIONED_AT = datetime(2024, 1, 1, tzinfo=timezone.utc)
_UNSET = object()


def _memory(memory_id: str, occurred_at: datetime | None, mentioned_at: object = _UNSET,
            **kwargs: object) -> RecalledMemory:
    if mentioned_at is _UNSET:
        mentioned_at = _DEFAULT_MENTIONED_AT
    return RecalledMemory(
        memory_id=memory_id,
        text=f"text-{memory_id}",
        occurred_at=occurred_at,
        mentioned_at=mentioned_at,
        **kwargs,
    )


def test_memories_sorted_oldest_first() -> None:
    newer = _memory("new", datetime(2024, 6, 1, tzinfo=timezone.utc))
    older = _memory("old", datetime(2023, 1, 1, tzinfo=timezone.utc))
    ordered = sort_memories_chronologically([newer, older])
    assert [m.memory_id for m in ordered] == ["old", "new"]


def test_undated_memories_sort_last() -> None:
    dated = _memory("dated", datetime(2023, 1, 1, tzinfo=timezone.utc))
    undated = _memory("undated", None, mentioned_at=None)
    ordered = sort_memories_chronologically([undated, dated])
    assert [m.memory_id for m in ordered] == ["dated", "undated"]


def test_falls_back_to_mentioned_at_when_occurred_at_missing() -> None:
    early_mention = _memory("early", None, mentioned_at=datetime(2022, 1, 1, tzinfo=timezone.utc))
    late_occurrence = _memory("late", datetime(2023, 1, 1, tzinfo=timezone.utc))
    ordered = sort_memories_chronologically([late_occurrence, early_mention])
    assert [m.memory_id for m in ordered] == ["early", "late"]


def test_build_timeline_preserves_order_and_traceability() -> None:
    older = _memory("old", datetime(2023, 1, 1, tzinfo=timezone.utc), metadata={"author": "Devon"})
    newer = _memory("new", datetime(2024, 1, 1, tzinfo=timezone.utc), metadata={"author": "Sofia"})
    events = build_timeline([newer, older])

    assert [e.memory_id for e in events] == ["old", "new"]
    assert events[0].author == "Devon"
    assert events[1].author == "Sofia"
    assert all(not e.is_undated for e in events)


def test_build_timeline_flags_undated_events() -> None:
    undated = _memory("undated", None, mentioned_at=None)
    events = build_timeline([undated])
    assert events[0].is_undated is True
