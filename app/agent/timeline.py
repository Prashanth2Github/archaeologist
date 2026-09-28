"""Deterministic timeline construction.

The timeline is assembled from retrieved memories by code, not by the language
model. A model asked to "order these events" can silently drop or invent one; a
sort cannot. The model's role is to explain the history, never to decide what the
history is.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.domain.models import RecalledMemory, TimelineEvent


def _sort_key(memory: RecalledMemory) -> tuple[int, datetime]:
    """Order oldest-first, with undated memories pushed to the end.

    Undated memories sort last because placing them at an arbitrary point in the
    sequence would imply a chronology the record does not support.
    """
    moment = memory.effective_time
    if moment is None:
        return (1, datetime.max.replace(tzinfo=timezone.utc))
    # Naive timestamps from the API are treated as UTC so comparisons never raise.
    normalized = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return (0, normalized)


def sort_memories_chronologically(memories: list[RecalledMemory]) -> list[RecalledMemory]:
    """Return memories oldest-first. Hindsight returns them by relevance."""
    return sorted(memories, key=_sort_key)


def build_timeline(memories: list[RecalledMemory]) -> list[TimelineEvent]:
    """Project retrieved memories onto a chronological timeline.

    Every event traces back to exactly one retrieved memory, so nothing on screen
    is unsourced.
    """
    events: list[TimelineEvent] = []
    for memory in sort_memories_chronologically(memories):
        events.append(
            TimelineEvent(
                occurred_at=memory.effective_time,
                text=memory.text,
                author=memory.author,
                kind=memory.kind,
                memory_type=memory.memory_type,
                memory_id=memory.memory_id,
                is_undated=memory.effective_time is None,
            )
        )
    return events
