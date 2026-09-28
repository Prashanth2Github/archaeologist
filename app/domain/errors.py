"""Application exception hierarchy.

Every error carries a `user_message` that is safe to render in the UI: it never
contains stack traces, credentials, or raw provider payloads. Diagnostic detail
belongs in logs, not on screen.
"""

from __future__ import annotations


class ArchaeologistError(Exception):
    """Base class for all expected application failures."""

    user_message = "Something went wrong. Please try again."

    def __init__(self, message: str, *, user_message: str | None = None) -> None:
        super().__init__(message)
        if user_message is not None:
            self.user_message = user_message


class ConfigurationError(ArchaeologistError):
    """Required configuration is missing or invalid."""

    user_message = "Archaeologist is not configured correctly. See the setup steps in the README."


class ValidationError(ArchaeologistError):
    """Caller-supplied input failed validation."""

    user_message = "That input is not valid."


class MemoryServiceError(ArchaeologistError):
    """Hindsight was unreachable, refused the request, or returned nonsense."""

    user_message = "The memory service (Hindsight) is currently unavailable."


class MemoryAuthError(MemoryServiceError):
    """Hindsight rejected our credentials."""

    user_message = "Hindsight rejected the configured API key. Check HINDSIGHT_API_KEY."


class MemoryTimeoutError(MemoryServiceError):
    """Hindsight did not respond in time."""

    user_message = "The memory service timed out. Please try again."


class LLMError(ArchaeologistError):
    """The language model provider failed."""

    user_message = "The language model is currently unavailable."


class LLMAuthError(LLMError):
    """The provider rejected our credentials."""

    user_message = "The LLM provider rejected the configured API key. Check LLM_API_KEY."


class LLMTimeoutError(LLMError):
    """The provider did not respond in time."""

    user_message = "The language model timed out. Please try again."


class LLMRateLimitError(LLMError):
    """The provider rate-limited us."""

    user_message = "The language model is rate-limited right now. Please wait a moment and retry."


class LLMResponseError(LLMError):
    """The provider returned a malformed or unusable response."""

    user_message = "The language model returned an unreadable response. Please try again."
