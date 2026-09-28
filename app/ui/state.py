"""Streamlit resource wiring and session-state helpers.

Streamlit reruns the whole script on every interaction, so anything expensive to
construct (the Hindsight client, the LLM client) is built once via
`st.cache_resource` rather than on every keystroke.
"""

from __future__ import annotations

import streamlit as st

from app.agent.archaeologist import ArchaeologistAgent
from app.config.settings import Settings, configure_logging, get_settings
from app.domain.errors import ConfigurationError
from app.services.factory import build_agent


@st.cache_resource(show_spinner=False)
def get_cached_settings() -> Settings:
    settings = get_settings()
    configure_logging(settings.log_level)
    return settings


@st.cache_resource(show_spinner=False)
def get_cached_agent(_settings: Settings) -> ArchaeologistAgent:
    """Build the agent once per process.

    `_settings` is prefixed with an underscore so Streamlit does not try to hash
    a Settings object as a cache key; the object identity is stable for the life
    of the process, which is all the caching needs here.
    """
    return build_agent(_settings)


def load_configuration_or_none() -> tuple[Settings, list[str]]:
    """Load settings and report any missing requirements without raising.

    Configuration errors are a normal, expected state (a fresh checkout with no
    .env yet) and are rendered as a setup panel, not a crash.
    """
    try:
        settings = get_cached_settings()
    except ConfigurationError as exc:
        st.error(exc.user_message)
        st.stop()
    return settings, settings.missing_requirements()


def get_agent_or_stop(settings: Settings) -> ArchaeologistAgent:
    """Build the agent, or halt the page with a clean error if construction fails."""
    try:
        return get_cached_agent(settings)
    except ConfigurationError as exc:
        st.error(exc.user_message)
        st.stop()
        raise  # pragma: no cover - st.stop() never returns; satisfies type checkers
