"""LLM client: JSON extraction and provider-error mapping.

The OpenAI SDK client is patched out entirely; no network call is made.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import openai
import pytest

from app.config.settings import Settings
from app.domain.errors import (
    ConfigurationError,
    LLMAuthError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)
from app.llm.client import LLMClient, extract_json_object

# -- extract_json_object -----------------------------------------------------


def test_extract_plain_json() -> None:
    assert extract_json_object('{"answer": "hi"}') == {"answer": "hi"}


def test_extract_json_wrapped_in_fence() -> None:
    raw = 'Here is the result:\n```json\n{"answer": "hi"}\n```'
    assert extract_json_object(raw) == {"answer": "hi"}


def test_extract_json_with_surrounding_prose() -> None:
    raw = 'Sure thing! {"answer": "hi", "drift_status": "no_evidence"} Hope that helps.'
    assert extract_json_object(raw)["answer"] == "hi"


def test_extract_json_raises_on_empty_response() -> None:
    with pytest.raises(LLMResponseError):
        extract_json_object("")


def test_extract_json_raises_on_unparseable_response() -> None:
    with pytest.raises(LLMResponseError):
        extract_json_object("this is not json at all, no braces here")


def test_extract_json_raises_on_non_object_json() -> None:
    with pytest.raises(LLMResponseError):
        extract_json_object("[1, 2, 3]")


# -- LLMClient construction ---------------------------------------------------


def test_missing_api_key_raises_configuration_error(fake_settings: Settings) -> None:
    fake_settings.llm_api_key = None
    with pytest.raises(ConfigurationError):
        LLMClient(fake_settings)


def _client_with_mocked_completion(fake_settings: Settings, side_effect: object) -> LLMClient:
    with patch("app.llm.client.OpenAI") as mock_openai_cls:
        mock_instance = MagicMock()
        mock_openai_cls.return_value = mock_instance
        client = LLMClient(fake_settings)
    if isinstance(side_effect, Exception):
        mock_instance.chat.completions.create.side_effect = side_effect
    else:
        mock_instance.chat.completions.create.return_value = side_effect
    return client


def _fake_completion(content: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_complete_json_happy_path(fake_settings: Settings) -> None:
    client = _client_with_mocked_completion(fake_settings, _fake_completion('{"answer": "ok"}'))
    assert client.complete_json("system", "user") == {"answer": "ok"}


def test_complete_json_raises_llm_response_error_on_garbage(fake_settings: Settings) -> None:
    client = _client_with_mocked_completion(fake_settings, _fake_completion("not json"))
    with pytest.raises(LLMResponseError):
        client.complete_json("system", "user")


def test_authentication_error_is_mapped(fake_settings: Settings, httpx2_response) -> None:
    error = openai.AuthenticationError("bad key", response=httpx2_response(401), body=None)
    client = _client_with_mocked_completion(fake_settings, error)
    with pytest.raises(LLMAuthError):
        client.complete_json("system", "user")


def test_rate_limit_error_is_mapped(fake_settings: Settings, httpx2_response) -> None:
    error = openai.RateLimitError("slow down", response=httpx2_response(429), body=None)
    client = _client_with_mocked_completion(fake_settings, error)
    with pytest.raises(LLMRateLimitError):
        client.complete_json("system", "user")


def test_timeout_error_is_mapped(fake_settings: Settings, httpx2_request) -> None:
    error = openai.APITimeoutError(request=httpx2_request)
    client = _client_with_mocked_completion(fake_settings, error)
    with pytest.raises(LLMTimeoutError):
        client.complete_json("system", "user")


def test_json_mode_rejection_falls_back_to_plain_completion(
    fake_settings: Settings, httpx2_response
) -> None:
    """Some models reject response_format=json_object; retry once without it."""
    rejection = openai.BadRequestError(
        "response_format not supported", response=httpx2_response(400), body=None
    )
    with patch("app.llm.client.OpenAI") as mock_openai_cls:
        mock_instance = MagicMock()
        mock_openai_cls.return_value = mock_instance
        client = LLMClient(fake_settings)
    mock_instance.chat.completions.create.side_effect = [
        rejection,
        _fake_completion('{"answer": "ok without json mode"}'),
    ]

    result = client.complete_json("system", "user")

    assert result == {"answer": "ok without json mode"}
    assert mock_instance.chat.completions.create.call_count == 2
