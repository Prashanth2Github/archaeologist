"""Environment-driven configuration.

All secrets come from the environment (or a local `.env` that is git-ignored).
Nothing in this module ever prints a credential: `describe_redacted` exists so the
UI can show what is configured without showing what the values are.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic import ValidationError as PydanticValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.errors import ConfigurationError

RecallBudget = Literal["low", "mid", "high"]

load_dotenv(override=False)

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Typed view of the process environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Hindsight memory service -----------------------------------------
    hindsight_base_url: str = "http://localhost:8888"
    hindsight_api_key: str | None = None
    hindsight_bank_id: str = "archaeologist"
    hindsight_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    hindsight_recall_budget: RecallBudget = "high"
    hindsight_recall_max_tokens: int = Field(default=4096, ge=256, le=32000)

    # --- LLM provider (any OpenAI-compatible endpoint) ---------------------
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str | None = None
    llm_model: str = "openai/gpt-oss-120b"
    llm_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    llm_temperature: float = Field(default=0.1, ge=0.0, le=2.0)

    # --- Application -------------------------------------------------------
    log_level: str = "INFO"

    @field_validator("hindsight_api_key", "llm_api_key", mode="before")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        """Treat an empty env var the same as an unset one."""
        if value is None:
            return None
        stripped = str(value).strip()
        return stripped or None

    @field_validator("hindsight_base_url", "llm_base_url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        cleaned = value.strip().rstrip("/")
        if not cleaned.startswith(("http://", "https://")):
            raise ValueError("Base URL must start with http:// or https://")
        return cleaned

    @field_validator("hindsight_bank_id")
    @classmethod
    def _validate_bank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("HINDSIGHT_BANK_ID must not be empty.")
        return cleaned

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL.")
        return level

    @property
    def is_local_hindsight(self) -> bool:
        """Local servers usually run unauthenticated, so a missing key is fine there."""
        return "localhost" in self.hindsight_base_url or "127.0.0.1" in self.hindsight_base_url

    def missing_requirements(self) -> list[str]:
        """Human-readable list of configuration problems that block real use.

        Returned rather than raised so the UI can render a helpful setup panel
        instead of a stack trace.
        """
        problems: list[str] = []
        if not self.llm_api_key:
            problems.append(
                "LLM_API_KEY is not set - Archaeologist cannot synthesise answers. "
                "Get a free key at https://console.groq.com/keys"
            )
        if not self.hindsight_api_key and not self.is_local_hindsight:
            problems.append(
                "HINDSIGHT_API_KEY is not set, but HINDSIGHT_BASE_URL points at a remote "
                "server. Remote Hindsight deployments require a bearer token."
            )
        return problems

    def describe_redacted(self) -> dict[str, str]:
        """Safe-to-display configuration summary. Never contains secret values."""

        def mask(secret: str | None) -> str:
            return "set" if secret else "not set"

        return {
            "Hindsight URL": self.hindsight_base_url,
            "Hindsight API key": mask(self.hindsight_api_key),
            "Memory bank": self.hindsight_bank_id,
            "Recall budget": self.hindsight_recall_budget,
            "LLM URL": self.llm_base_url,
            "LLM API key": mask(self.llm_api_key),
            "LLM model": self.llm_model,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache settings, converting pydantic errors into a clean failure."""
    try:
        return Settings()
    except PydanticValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigurationError(
            f"Invalid configuration: {details}",
            user_message=f"Invalid configuration - {details}",
        ) from exc


def configure_logging(level: str = "INFO") -> None:
    """Install a single stream handler.

    Credentials are never passed to loggers anywhere in this codebase, so no
    redaction filter is required here.
    """
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    )
    # These libraries log request URLs at INFO, which is noise for our purposes.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
