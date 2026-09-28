"""The Archaeologist agent.

Orchestrates the product's core loop:

    question -> Hindsight RECALL -> chronological ordering -> grounded LLM
    synthesis -> historical answer + timeline + drift assessment

Two deliberate constraints:

* The **timeline is computed, not generated**. The model explains history; it
  never decides what the history is.
* Every id the model cites is **checked against what was actually retrieved**.
  A reference to a memory that was not recalled is dropped, so the memory panel
  can never show a citation that does not exist.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agent.questions import extract_entity_hint, validate_question
from app.agent.timeline import build_timeline, sort_memories_chronologically
from app.domain.errors import LLMError
from app.domain.models import (
    AnswerResult,
    DecisionRecord,
    DriftAssessment,
    DriftStatus,
    MemoryConflict,
    RecalledMemory,
)
from app.llm.client import LLMClient
from app.llm.prompts import (
    NO_MEMORY_ANSWER,
    SYNTHESIS_SYSTEM_PROMPT,
    build_synthesis_user_prompt,
)
from app.memory.hindsight_store import HindsightMemoryStore

logger = logging.getLogger(__name__)

MAX_CONFLICTS = 5

_DEGRADED_ANSWER = (
    "Archaeologist recalled the relevant history from Hindsight, but could not "
    "reach the language model to summarise it. The recorded memories and timeline "
    "below are the raw, unsummarised evidence."
)


class ArchaeologistAgent:
    """Application-layer coordinator over the memory store and the language model."""

    def __init__(self, store: HindsightMemoryStore, llm: LLMClient) -> None:
        self._store = store
        self._llm = llm

    # -- write path --------------------------------------------------------

    def record_decision(self, record: DecisionRecord) -> str:
        """RETAIN a decision or an update. Returns the Hindsight document id."""
        return self._store.retain_decision(record)

    # -- read path ---------------------------------------------------------

    def ask(self, question: str) -> AnswerResult:
        """Answer a "why does this exist?" question from recorded memory only.

        Raises:
            ValidationError: the question is empty or over-long.
            MemoryServiceError: Hindsight could not be reached.

        Language-model failures are *not* raised: the answer degrades to raw
        recalled evidence rather than losing the memory the user came for.
        """
        cleaned = validate_question(question)
        entity_hint = extract_entity_hint(cleaned)

        memories = self._store.recall_for_question(cleaned, entity_hint)
        if not memories:
            logger.info("No memories recalled for question (entity_hint=%s).", entity_hint or "-")
            return AnswerResult(
                question=cleaned,
                answer=NO_MEMORY_ANSWER,
                has_memory=False,
            )

        ordered = sort_memories_chronologically(memories)
        timeline = build_timeline(ordered)

        try:
            payload = self._llm.complete_json(
                SYNTHESIS_SYSTEM_PROMPT,
                build_synthesis_user_prompt(cleaned, ordered),
            )
        except LLMError as exc:
            logger.warning("Synthesis unavailable, returning raw evidence: %s", exc)
            return AnswerResult(
                question=cleaned,
                answer=_DEGRADED_ANSWER,
                has_memory=True,
                memories=ordered,
                timeline=timeline,
                degraded_reason=exc.user_message,
            )

        known_ids = {memory.memory_id for memory in ordered}
        return AnswerResult(
            question=cleaned,
            answer=_read_answer(payload),
            has_memory=True,
            memories=ordered,
            timeline=timeline,
            drift=_read_drift(payload, known_ids),
            conflicts=_read_conflicts(payload, known_ids),
        )

    def entity_history(self, entity: str) -> list[RecalledMemory]:
        """Everything recorded about one code identifier, oldest first."""
        return sort_memories_chronologically(self._store.recall_entity_history(entity))


# -- response parsing ------------------------------------------------------
#
# The model is instructed to return a fixed JSON shape, but a missing or
# malformed field must never take down an answer that is otherwise grounded.


def _read_answer(payload: dict[str, Any]) -> str:
    answer = payload.get("answer")
    if isinstance(answer, str) and answer.strip():
        return answer.strip()
    logger.warning("Synthesis payload had no usable 'answer' field.")
    return (
        "The memory bank returned relevant records, but no readable summary could be "
        "produced. The recalled memories below are the primary evidence."
    )


def _read_drift(payload: dict[str, Any], known_ids: set[str]) -> DriftAssessment:
    raw_status = payload.get("drift_status")
    try:
        status = DriftStatus(str(raw_status))
    except ValueError:
        logger.debug("Unrecognised drift_status %r; defaulting to no_evidence.", raw_status)
        status = DriftStatus.NO_EVIDENCE

    rationale = payload.get("drift_rationale")
    supporting = payload.get("drift_memory_ids")

    return DriftAssessment(
        status=status,
        rationale=rationale.strip() if isinstance(rationale, str) else "",
        supporting_memory_ids=_filter_ids(supporting, known_ids),
    )


def _read_conflicts(payload: dict[str, Any], known_ids: set[str]) -> list[MemoryConflict]:
    raw = payload.get("conflicts")
    if not isinstance(raw, list):
        return []

    conflicts: list[MemoryConflict] = []
    for item in raw[:MAX_CONFLICTS]:
        if not isinstance(item, dict):
            continue
        summary = item.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            continue
        conflicts.append(
            MemoryConflict(
                summary=summary.strip(),
                memory_ids=_filter_ids(item.get("memory_ids"), known_ids),
            )
        )
    return conflicts


def _filter_ids(raw: Any, known_ids: set[str]) -> list[str]:
    """Keep only ids that were genuinely retrieved, preserving order.

    Guards against a model citing a memory that does not exist.
    """
    if not isinstance(raw, list):
        return []
    seen: list[str] = []
    for item in raw:
        candidate = str(item)
        if candidate in known_ids and candidate not in seen:
            seen.append(candidate)
    return seen
