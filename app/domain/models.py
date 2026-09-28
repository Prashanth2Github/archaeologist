"""Core domain types for engineering-decision memory.

These types are storage-agnostic. `DecisionRecord` is what an engineer writes
down; `RecalledMemory` is what Hindsight gives back. The mapping between the two
lives in `app.memory`, not here.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

# A code identifier such as "search_api.rate_limit" or "services/auth:token_expiry".
# Deliberately permissive about separators, strict about everything else: this string
# is echoed into prompts and used to build memory tags.
ENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-]{0,119}$")

MAX_DECISION_CHARS = 2000
MAX_REASON_CHARS = 4000
MAX_AUTHOR_CHARS = 120
MAX_EVIDENCE_CHARS = 1000
MAX_QUESTION_CHARS = 500
MAX_TAGS = 10
MAX_TAG_CHARS = 50

ENTITY_TAG_PREFIX = "entity:"


class DecisionKind(str, Enum):
    """Whether a record establishes a decision or revises the knowledge around it."""

    ORIGINAL = "original"
    UPDATE = "update"


class MemoryType(str, Enum):
    """Hindsight fact categories."""

    WORLD = "world"
    EXPERIENCE = "experience"
    OBSERVATION = "observation"


def normalize_entity(entity: str) -> str:
    """Canonical form of a code identifier, used for tagging and grouping."""
    return entity.strip().lower()


def entity_tag(entity: str) -> str:
    """Hindsight tag that scopes a memory to one code identifier."""
    return f"{ENTITY_TAG_PREFIX}{normalize_entity(entity)}"


def _clean(value: str) -> str:
    """Trim surrounding whitespace without destroying intentional line breaks."""
    return "\n".join(line.rstrip() for line in value.strip().splitlines())


class DecisionRecord(BaseModel):
    """A single engineering decision, or a later revision of one.

    Updates never overwrite originals. Both are retained as separate memories so
    the full history survives.
    """

    entity: str
    decision: str
    reason: str
    author: str
    occurred_at: datetime
    kind: DecisionKind = DecisionKind.ORIGINAL
    evidence: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("entity")
    @classmethod
    def _validate_entity(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Entity is required (for example: search_api.rate_limit).")
        if not ENTITY_PATTERN.match(cleaned):
            raise ValueError(
                "Entity must start with a letter or digit and may contain only "
                "letters, digits, and . _ : / - characters."
            )
        return cleaned

    @field_validator("decision")
    @classmethod
    def _validate_decision(cls, value: str) -> str:
        cleaned = _clean(value)
        if not cleaned:
            raise ValueError("Decision is required.")
        if len(cleaned) > MAX_DECISION_CHARS:
            raise ValueError(f"Decision must be at most {MAX_DECISION_CHARS} characters.")
        return cleaned

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        cleaned = _clean(value)
        if not cleaned:
            raise ValueError("Reason is required - the 'why' is the whole point.")
        if len(cleaned) > MAX_REASON_CHARS:
            raise ValueError(f"Reason must be at most {MAX_REASON_CHARS} characters.")
        return cleaned

    @field_validator("author")
    @classmethod
    def _validate_author(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Author is required.")
        if len(cleaned) > MAX_AUTHOR_CHARS:
            raise ValueError(f"Author must be at most {MAX_AUTHOR_CHARS} characters.")
        return cleaned

    @field_validator("evidence")
    @classmethod
    def _validate_evidence(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _clean(value)
        if not cleaned:
            return None
        if len(cleaned) > MAX_EVIDENCE_CHARS:
            raise ValueError(f"Evidence must be at most {MAX_EVIDENCE_CHARS} characters.")
        return cleaned

    @field_validator("occurred_at")
    @classmethod
    def _validate_occurred_at(cls, value: datetime) -> datetime:
        # Hindsight grounds relative time expressions against this value, so it must
        # be unambiguous. Naive datetimes are assumed to be UTC.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in value:
            tag = raw.strip().lower()
            if not tag:
                continue
            if len(tag) > MAX_TAG_CHARS:
                raise ValueError(f"Each tag must be at most {MAX_TAG_CHARS} characters.")
            if tag not in cleaned:
                cleaned.append(tag)
        if len(cleaned) > MAX_TAGS:
            raise ValueError(f"At most {MAX_TAGS} tags are allowed.")
        return cleaned

    @property
    def memory_tags(self) -> list[str]:
        """Tags written to Hindsight: the entity scope plus any user tags."""
        return [entity_tag(self.entity), *self.tags]


class RecalledMemory(BaseModel):
    """One fact returned by Hindsight RECALL.

    Treated as untrusted input: the text originates from user-supplied content and
    is never allowed to act as an instruction to the model.
    """

    memory_id: str
    text: str
    memory_type: MemoryType = MemoryType.WORLD
    context: str | None = None
    tags: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    occurred_at: datetime | None = None
    mentioned_at: datetime | None = None
    document_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float | None = None

    @property
    def effective_time(self) -> datetime | None:
        """Best available timestamp for chronological ordering.

        Prefers when the decision actually happened over when it was written down.
        """
        return self.occurred_at or self.mentioned_at

    @property
    def author(self) -> str | None:
        value = self.metadata.get("author")
        return str(value) if value else None

    @property
    def entity(self) -> str | None:
        value = self.metadata.get("entity")
        if value:
            return str(value)
        for tag in self.tags:
            if tag.startswith(ENTITY_TAG_PREFIX):
                return tag[len(ENTITY_TAG_PREFIX) :]
        return None

    @property
    def kind(self) -> DecisionKind | None:
        raw = self.metadata.get("kind")
        if raw in {DecisionKind.ORIGINAL.value, DecisionKind.UPDATE.value}:
            return DecisionKind(raw)
        return None


class TimelineEvent(BaseModel):
    """One dated point in a decision's history, derived from retrieved memories."""

    occurred_at: datetime | None
    text: str
    author: str | None = None
    kind: DecisionKind | None = None
    memory_type: MemoryType = MemoryType.WORLD
    memory_id: str
    is_undated: bool = False


class DriftStatus(str, Enum):
    """How confident we are that the original reasoning still holds."""

    NO_EVIDENCE = "no_evidence"
    LIKELY_CURRENT = "likely_current"
    NEEDS_REVIEW = "needs_review"
    MAY_BE_OUTDATED = "may_be_outdated"


DRIFT_LABELS: dict[DriftStatus, str] = {
    DriftStatus.NO_EVIDENCE: "No recorded evidence either way",
    DriftStatus.LIKELY_CURRENT: "Original reasoning appears to still apply",
    DriftStatus.NEEDS_REVIEW: "Requires review",
    DriftStatus.MAY_BE_OUTDATED: "Original reasoning may no longer apply",
}


class DriftAssessment(BaseModel):
    """Cautious judgement about whether a decision's rationale has gone stale."""

    status: DriftStatus = DriftStatus.NO_EVIDENCE
    rationale: str = ""
    supporting_memory_ids: list[str] = Field(default_factory=list)

    @property
    def label(self) -> str:
        return DRIFT_LABELS[self.status]


class MemoryConflict(BaseModel):
    """Two retrieved memories that cannot both be true.

    Surfaced verbatim to the user. We never silently pick a winner.
    """

    summary: str
    memory_ids: list[str] = Field(default_factory=list)


class AnswerResult(BaseModel):
    """Everything the UI needs to render a grounded historical answer."""

    question: str
    answer: str
    has_memory: bool
    memories: list[RecalledMemory] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    drift: DriftAssessment = Field(default_factory=DriftAssessment)
    conflicts: list[MemoryConflict] = Field(default_factory=list)
    degraded_reason: str | None = None
