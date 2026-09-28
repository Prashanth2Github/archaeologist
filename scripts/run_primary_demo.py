"""Run the exact primary demo story against a live Hindsight bank end to end.

    Session 1: ask about search_api.rate_limit -> no memory -> honest unknown
    Session 1: record the original decision                  -> RETAIN
    Session 2: record that the constraint was resolved        -> RETAIN
    Session 3: ask again -> RECALL both memories -> grounded synthesis,
               timeline, and a decision-drift assessment

This is the script referenced by docs/demo-script.md. It talks to real Hindsight
and a real LLM provider — it is not a unit test and is not run in CI.

Usage:
    python scripts/run_primary_demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows consoles default to the legacy system codepage (e.g. cp1252), which
# cannot encode characters an LLM may legitimately emit (curly quotes, narrow
# no-break spaces, em dashes). Force UTF-8 so a real answer never crashes print().
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config.settings import configure_logging, get_settings  # noqa: E402
from app.domain.errors import ArchaeologistError  # noqa: E402
from app.domain.models import DecisionKind, DecisionRecord  # noqa: E402
from app.services.factory import build_agent  # noqa: E402

ENTITY = "search_api.rate_limit"
QUESTION = "Why is search_api.rate_limit still 100?"


def _banner(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)

    problems = settings.missing_requirements()
    if problems:
        print("Configuration is incomplete - cannot run the live demo:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    agent = build_agent(settings)

    try:
        _banner("SESSION 1 - Ask before anything is recorded")
        result = agent.ask(QUESTION)
        print(f"Q: {QUESTION}")
        print(f"A: {result.answer}")
        print(f"has_memory = {result.has_memory}")
        if result.has_memory:
            print(
                "WARNING: expected no prior memory for this entity. "
                "Bank may already contain seed data for search_api.rate_limit."
            )

        _banner("SESSION 1 - Record the original decision (RETAIN)")
        original = DecisionRecord(
            entity=ENTITY,
            decision="search_api.rate_limit set to 100 requests/sec.",
            reason=(
                "Elasticsearch became unstable and began dropping queries when the "
                "search API sustained more than 100 requests/sec against it."
            ),
            author="Priya Raman",
            occurred_at=datetime(2023, 4, 11, 10, 0, tzinfo=timezone.utc),
            kind=DecisionKind.ORIGINAL,
            evidence="Incident INC-1229",
        )
        doc_id = agent.record_decision(original)
        print(f"Retained original decision. document_id={doc_id}")

        _banner("SESSION 2 - Record that the constraint was resolved (RETAIN)")
        update = DecisionRecord(
            entity=ENTITY,
            decision="search_api.rate_limit left at 100 requests/sec (unchanged).",
            reason=(
                "Elasticsearch was upgraded to a larger cluster and the original "
                "stability constraint above 100 requests/sec was resolved in testing. "
                "The rate limit itself was not changed as part of this work."
            ),
            author="Marcus Webb",
            occurred_at=datetime(2024, 8, 2, 15, 30, tzinfo=timezone.utc),
            kind=DecisionKind.UPDATE,
            evidence="Elasticsearch upgrade report ES-2024-08",
        )
        doc_id = agent.record_decision(update)
        print(f"Retained update. document_id={doc_id}")

        _banner("SESSION 3 - Ask again (RECALL both memories -> synthesis)")
        result = agent.ask(QUESTION)
        print(f"Q: {QUESTION}\n")
        print(f"A: {result.answer}\n")
        print(f"Drift status: {result.drift.label}")
        if result.drift.rationale:
            print(f"Drift rationale: {result.drift.rationale}")
        print(f"\nMemories used ({len(result.memories)}):")
        for m in result.memories:
            when = m.effective_time.date().isoformat() if m.effective_time else "undated"
            print(f"  - [{when}] ({m.author or 'unknown author'}) {m.text}")
        if result.conflicts:
            print("\nConflicts surfaced:")
            for c in result.conflicts:
                print(f"  - {c.summary}")

    except ArchaeologistError as exc:
        print(f"\nDemo failed: {exc.user_message}")
        return 1

    _banner("Demo complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
