"""Composition root.

The UI and the command-line scripts both need a fully wired agent. Building it
in one place keeps construction order (and its failure modes) identical
everywhere, so a misconfiguration surfaces the same way in both.
"""

from __future__ import annotations

import logging

from app.agent.archaeologist import ArchaeologistAgent
from app.config.settings import Settings, configure_logging, get_settings
from app.llm.client import LLMClient
from app.memory.hindsight_store import HindsightMemoryStore

logger = logging.getLogger(__name__)


def build_store(settings: Settings | None = None) -> HindsightMemoryStore:
    """Construct the Hindsight-backed memory store."""
    return HindsightMemoryStore(settings or get_settings())


def build_agent(settings: Settings | None = None) -> ArchaeologistAgent:
    """Construct the agent with a live memory store and language model.

    Raises:
        ConfigurationError: if required configuration is missing or invalid.
    """
    resolved = settings or get_settings()
    return ArchaeologistAgent(
        store=HindsightMemoryStore(resolved),
        llm=LLMClient(resolved),
    )


def bootstrap() -> tuple[Settings, ArchaeologistAgent]:
    """Load settings, configure logging, and build the agent. For script entry points."""
    settings = get_settings()
    configure_logging(settings.log_level)
    return settings, build_agent(settings)
