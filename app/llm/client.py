"""Thin wrapper over any OpenAI-compatible chat completions endpoint.

Provider and model are configuration, not code: Groq, OpenAI, Together and
friends all speak this protocol, so switching is an environment-variable change.

The wrapper's real job is turning the provider's many failure modes into our own
small, user-safe exception set, and extracting JSON from responses that may be
wrapped in prose or code fences.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import openai
from openai import OpenAI

from app.config.settings import Settings
from app.domain.errors import (
    ConfigurationError,
    LLMAuthError,
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)

# Matches a ```json ... ``` (or bare ```) fence around a payload.
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def extract_json_object(raw: str) -> dict[str, Any]:
    """Pull a JSON object out of a model response.

    Models wrap JSON in code fences or prefix it with commentary often enough that
    strict parsing alone is unreliable. Tries, in order: the whole string, any
    fenced block, then the outermost brace-balanced span.

    Raises:
        LLMResponseError: if no JSON object can be recovered.
    """
    if not raw or not raw.strip():
        raise LLMResponseError("Model returned an empty response.")

    candidates: list[str] = [raw.strip()]

    fenced = _FENCE_RE.search(raw)
    if fenced:
        candidates.append(fenced.group(1).strip())

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        candidates.append(raw[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed

    logger.warning("Could not parse JSON from model response (%d chars).", len(raw))
    raise LLMResponseError("Model response did not contain a JSON object.")


class LLMClient:
    """Synchronous chat-completions client with mapped errors."""

    def __init__(self, settings: Settings) -> None:
        if not settings.llm_api_key:
            raise ConfigurationError(
                "LLM_API_KEY is not set.",
                user_message=(
                    "No LLM API key is configured. Set LLM_API_KEY in your .env file."
                ),
            )
        self._settings = settings
        self._model = settings.llm_model
        # The SDK's own retry logic covers connection errors and 429s with backoff.
        self._client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Run one completion and parse the result as a JSON object.

        Raises:
            LLMAuthError, LLMRateLimitError, LLMTimeoutError, LLMResponseError, LLMError
        """
        raw = self._complete(system_prompt, user_prompt, want_json=True)
        return extract_json_object(raw)

    def _complete(self, system_prompt: str, user_prompt: str, *, want_json: bool) -> str:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._settings.llm_temperature,
        }
        if want_json:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = self._client.chat.completions.create(**kwargs)
        except openai.BadRequestError as exc:
            # Not every model supports response_format; retry once without it rather
            # than failing a demo over an optional parameter.
            if want_json:
                logger.info("Model rejected response_format; retrying without JSON mode.")
                return self._complete(system_prompt, user_prompt, want_json=False)
            raise LLMError(f"Provider rejected the request: {type(exc).__name__}") from exc
        except openai.AuthenticationError as exc:
            raise LLMAuthError("LLM provider rejected the API key.") from exc
        except openai.PermissionDeniedError as exc:
            raise LLMAuthError("LLM provider denied access to the configured model.") from exc
        except openai.RateLimitError as exc:
            raise LLMRateLimitError("LLM provider rate limit reached.") from exc
        except openai.APITimeoutError as exc:
            raise LLMTimeoutError(
                f"LLM request exceeded {self._settings.llm_timeout_seconds}s."
            ) from exc
        except openai.APIConnectionError as exc:
            raise LLMError("Could not reach the LLM provider.") from exc
        except openai.APIStatusError as exc:
            raise LLMError(f"LLM provider returned HTTP {exc.status_code}.") from exc
        except openai.OpenAIError as exc:
            raise LLMError(f"LLM provider error: {type(exc).__name__}") from exc

        return self._extract_text(response)

    @staticmethod
    def _extract_text(response: Any) -> str:
        """Defensively read message content out of a completion response."""
        choices = getattr(response, "choices", None)
        if not choices:
            raise LLMResponseError("Model returned no choices.")
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None) if message else None
        if not content or not str(content).strip():
            raise LLMResponseError("Model returned empty message content.")
        return str(content)
