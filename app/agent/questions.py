"""Question validation and entity extraction.

Entity detection is deliberately a regex, not an LLM call. When an engineer types
`search_api.rate_limit` the identifier is right there in the text; spending a
model round-trip on it would add latency and a way to be wrong.
"""

from __future__ import annotations

import re

from app.domain.errors import ValidationError
from app.domain.models import MAX_QUESTION_CHARS

# A dotted/namespaced code identifier: at least one separator, so ordinary prose
# words never match. Examples: search_api.rate_limit, auth.token_expiry,
# services/auth:timeout.
_IDENTIFIER_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_\-]*(?:[./:][A-Za-z0-9_\-]+)+\b")

# Identifier-looking tokens that are almost always prose or URLs, not entities.
_IDENTIFIER_STOPWORDS = {"e.g", "i.e", "etc", "http", "https", "www"}


def validate_question(question: str) -> str:
    """Normalise and check a user question.

    Raises:
        ValidationError: if the question is empty or too long for a recall query.
    """
    cleaned = " ".join(question.split())
    if not cleaned:
        raise ValidationError(
            "Empty question.",
            user_message="Please enter a question before asking.",
        )
    if len(cleaned) > MAX_QUESTION_CHARS:
        raise ValidationError(
            "Question too long.",
            user_message=(
                f"Questions are limited to {MAX_QUESTION_CHARS} characters "
                f"(yours is {len(cleaned)})."
            ),
        )
    return cleaned


def extract_entity_hint(question: str) -> str | None:
    """Return the code identifier a question is about, if it names one explicitly.

    Returns None when the question is phrased in prose ("why is the rate limit
    100?"). That is fine: recall still runs over the whole bank, it just is not
    additionally scoped by tag.
    """
    for match in _IDENTIFIER_RE.finditer(question):
        candidate = match.group(0).rstrip(".:/?")
        head = candidate.split(".", 1)[0].lower()
        if candidate.lower() in _IDENTIFIER_STOPWORDS or head in _IDENTIFIER_STOPWORDS:
            continue
        if "://" in candidate:
            continue
        # A match starting right after "scheme://" is a URL host/path, e.g. the
        # "example.com/docs" tail of "https://example.com/docs" - not a code identifier.
        if question[: match.start()].endswith("//"):
            continue
        return candidate
    return None
