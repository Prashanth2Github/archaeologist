"""Hindsight-backed persistent memory for engineering decisions.

This is the only module that knows Hindsight exists. It performs the two
primitives the product is built on:

* **RETAIN** - a decision (or a later revision of one) is written to the bank as
  a dated, tagged, entity-linked narrative. Hindsight extracts structured facts
  from it; we never store or manage embeddings ourselves.
* **RECALL** - a natural-language question is answered with the facts Hindsight
  considers relevant, using its semantic + keyword + graph + temporal retrieval.

Updates are additive by design: every record gets a fresh `document_id`, because
reusing one would make Hindsight delete the prior document and destroy history.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from hindsight_client import Hindsight
from hindsight_client_api.exceptions import (
    ApiException,
    BadRequestException,
    ForbiddenException,
    NotFoundException,
    ServiceException,
    UnauthorizedException,
)

from app.config.settings import Settings
from app.domain.errors import MemoryAuthError, MemoryServiceError, MemoryTimeoutError
from app.domain.models import (
    DecisionKind,
    DecisionRecord,
    MemoryType,
    RecalledMemory,
    entity_tag,
    normalize_entity,
)
from app.llm.prompts import (
    RETAIN_CONTEXT_ORIGINAL,
    RETAIN_CONTEXT_UPDATE,
    build_decision_narrative,
)

logger = logging.getLogger(__name__)

# Marks every memory this application writes, so a shared bank stays attributable.
SOURCE_TAG = "archaeologist"

ENTITY_TYPE_CODE = "CODE_IDENTIFIER"
ENTITY_TYPE_PERSON = "PERSON"

# Upper bound on memories fed into a single synthesis prompt.
MAX_MEMORIES_PER_ANSWER = 24


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp from the API, tolerating a trailing 'Z'.

    Returns None rather than raising: a single unparseable timestamp should cost
    us one memory's date, not the whole answer.
    """
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        logger.debug("Unparseable timestamp from Hindsight: %r", value)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _as_memory_type(raw: str | None) -> MemoryType:
    try:
        return MemoryType(str(raw))
    except ValueError:
        return MemoryType.WORLD


def _stringify_metadata(values: dict[str, Any]) -> dict[str, str]:
    """Hindsight metadata values must be strings; drop empties rather than send nulls."""
    return {key: str(value) for key, value in values.items() if value not in (None, "")}


class HindsightMemoryStore:
    """RETAIN/RECALL access to one Hindsight memory bank."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._bank_id = settings.hindsight_bank_id
        self._client = Hindsight(
            base_url=settings.hindsight_base_url,
            api_key=settings.hindsight_api_key,
            timeout=settings.hindsight_timeout_seconds,
        )

    # -- lifecycle ---------------------------------------------------------

    def ensure_bank(self) -> None:
        """Create the memory bank if it does not exist yet.

        Safe to call repeatedly; an already-existing bank is not an error.
        """
        try:
            self._client.create_bank(
                bank_id=self._bank_id,
                name="Archaeologist - engineering decisions",
                mission=(
                    "Remember why engineering decisions were made: the decision, the "
                    "reason, the author, the date, supporting evidence, and any later "
                    "change to that reasoning. Preserve superseded history rather than "
                    "replacing it."
                ),
            )
            logger.info("Created Hindsight bank %r.", self._bank_id)
        except (BadRequestException, ApiException) as exc:
            # The API returns 400/409 when the bank already exists. Anything else that
            # genuinely blocks us will resurface on the next retain/recall call.
            logger.debug("create_bank for %r returned %s (assuming it exists).",
                         self._bank_id, type(exc).__name__)

    def health_check(self) -> None:
        """Confirm the bank is reachable and our credentials work.

        Raises:
            MemoryAuthError, MemoryTimeoutError, MemoryServiceError
        """
        try:
            self._client.recall(bank_id=self._bank_id, query="health check", max_tokens=256,
                                budget="low")
        except Exception as exc:  # noqa: BLE001 - mapped to our own error set below
            raise self._map_error(exc, "health check") from exc

    # -- RETAIN ------------------------------------------------------------

    def retain_decision(self, record: DecisionRecord) -> str:
        """Persist one decision or update as a new Hindsight memory.

        Returns:
            The `document_id` written, for display and traceability.

        Raises:
            MemoryAuthError, MemoryTimeoutError, MemoryServiceError
        """
        is_update = record.kind is DecisionKind.UPDATE
        content = build_decision_narrative(
            entity=record.entity,
            decision=record.decision,
            reason=record.reason,
            author=record.author,
            is_update=is_update,
            evidence=record.evidence,
        )
        # Unique per record: reusing a document_id would delete the earlier document
        # and with it the history this product exists to protect.
        document_id = (
            f"{normalize_entity(record.entity)}:{record.kind.value}:{uuid.uuid4().hex[:12]}"
        )

        metadata = _stringify_metadata(
            {
                "entity": record.entity,
                "author": record.author,
                "kind": record.kind.value,
                "evidence": record.evidence,
                "source": SOURCE_TAG,
            }
        )
        entities = [
            {"text": record.entity, "type": ENTITY_TYPE_CODE},
            {"text": record.author, "type": ENTITY_TYPE_PERSON},
        ]

        try:
            self._client.retain(
                bank_id=self._bank_id,
                content=content,
                # Grounds Hindsight's temporal reasoning in when the decision was made,
                # not when it happened to be typed in.
                timestamp=record.occurred_at,
                context=RETAIN_CONTEXT_UPDATE if is_update else RETAIN_CONTEXT_ORIGINAL,
                document_id=document_id,
                metadata=metadata,
                entities=entities,
                tags=record.memory_tags,
            )
        except Exception as exc:  # noqa: BLE001 - mapped below
            raise self._map_error(exc, "retain") from exc

        logger.info(
            "RETAIN ok: entity=%s kind=%s document_id=%s",
            record.entity, record.kind.value, document_id,
        )
        return document_id

    # -- RECALL ------------------------------------------------------------

    def recall_for_question(
        self, question: str, entity_hint: str | None = None
    ) -> list[RecalledMemory]:
        """Retrieve memories relevant to a question.

        Runs a broad semantic recall over the whole bank. When the question names a
        concrete code identifier, a second recall scoped to that entity's tag is
        merged in, so a precise question does not lose precise memories to a
        crowded relevance ranking.

        Raises:
            MemoryAuthError, MemoryTimeoutError, MemoryServiceError
        """
        merged: dict[str, RecalledMemory] = {}

        for memory in self._recall(question):
            merged[memory.memory_id] = memory

        if entity_hint:
            for memory in self._recall(question, tags=[entity_tag(entity_hint)]):
                merged.setdefault(memory.memory_id, memory)

        memories = list(merged.values())[:MAX_MEMORIES_PER_ANSWER]
        logger.info(
            "RECALL ok: question_len=%d entity_hint=%s memories=%d",
            len(question), entity_hint or "-", len(memories),
        )
        return memories

    def recall_entity_history(self, entity: str) -> list[RecalledMemory]:
        """Retrieve everything recorded about one code identifier, for the timeline view."""
        query = f"All recorded engineering decisions, reasons and updates for {entity}"
        return self._recall(query, tags=[entity_tag(entity)])

    def _recall(self, query: str, tags: list[str] | None = None) -> list[RecalledMemory]:
        try:
            response = self._client.recall(
                bank_id=self._bank_id,
                query=query,
                budget=self._settings.hindsight_recall_budget,
                max_tokens=self._settings.hindsight_recall_max_tokens,
                include_entities=True,
                tags=tags,
                # "any_strict" keeps untagged noise out of an entity-scoped lookup.
                tags_match="any_strict" if tags else "any",
            )
        except Exception as exc:  # noqa: BLE001 - mapped below
            raise self._map_error(exc, "recall") from exc

        results = getattr(response, "results", None) or []
        return [self._to_memory(result) for result in results]

    @staticmethod
    def _to_memory(result: Any) -> RecalledMemory:
        """Map a Hindsight RecallResult onto our domain type."""
        scores = getattr(result, "scores", None)
        final_score = getattr(scores, "final", None) if scores else None

        return RecalledMemory(
            memory_id=str(getattr(result, "id", "") or uuid.uuid4().hex),
            text=str(getattr(result, "text", "") or ""),
            memory_type=_as_memory_type(getattr(result, "type", None)),
            context=getattr(result, "context", None),
            tags=list(getattr(result, "tags", None) or []),
            entities=list(getattr(result, "entities", None) or []),
            occurred_at=_parse_iso(getattr(result, "occurred_start", None)),
            mentioned_at=_parse_iso(getattr(result, "mentioned_at", None)),
            document_id=getattr(result, "document_id", None),
            metadata=dict(getattr(result, "metadata", None) or {}),
            score=float(final_score) if isinstance(final_score, (int, float)) else None,
        )

    # -- error mapping -----------------------------------------------------

    @staticmethod
    def _map_error(exc: Exception, operation: str) -> MemoryServiceError:
        """Translate SDK/transport failures into user-safe application errors.

        Response bodies are logged, never surfaced: they can echo request content.
        """
        if isinstance(exc, (UnauthorizedException, ForbiddenException)):
            logger.error("Hindsight %s rejected credentials (%s).", operation, type(exc).__name__)
            return MemoryAuthError(f"Hindsight {operation} unauthorized.")

        if isinstance(exc, NotFoundException):
            logger.error("Hindsight %s: bank or resource not found.", operation)
            return MemoryServiceError(
                f"Hindsight {operation} target not found.",
                user_message=(
                    "The configured Hindsight memory bank was not found. "
                    "Check HINDSIGHT_BANK_ID, or seed the bank first."
                ),
            )

        if isinstance(exc, (ServiceException, BadRequestException, ApiException)):
            status = getattr(exc, "status", "unknown")
            logger.error("Hindsight %s failed with HTTP %s.", operation, status)
            return MemoryServiceError(f"Hindsight {operation} failed (HTTP {status}).")

        message = str(exc).lower()
        if "timed out" in message or "timeout" in message:
            logger.error("Hindsight %s timed out.", operation)
            return MemoryTimeoutError(f"Hindsight {operation} timed out.")

        logger.exception("Unexpected Hindsight %s failure.", operation)
        return MemoryServiceError(f"Hindsight {operation} failed: {type(exc).__name__}")
