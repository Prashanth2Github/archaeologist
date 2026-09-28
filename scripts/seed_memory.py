"""Load data/seed_decisions.json into the configured Hindsight bank.

Usage:
    python scripts/seed_memory.py

Idempotent in effect, not in Hindsight bookkeeping: re-running adds duplicate
memories, since a fresh document_id is minted per record by design (see
app.memory.hindsight_store). Point HINDSIGHT_BANK_ID at a scratch bank if you
want to re-seed repeatedly during development.

Deliberately excludes `search_api.rate_limit`: that entity is reserved for the
live "unknown -> retain -> update -> recall" demo script
(scripts/run_primary_demo.py) so its "no recorded history" state stays genuine.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

# See scripts/run_primary_demo.py for why: Windows consoles default to a legacy
# codepage that cannot encode all characters seed content may contain.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config.settings import configure_logging, get_settings  # noqa: E402
from app.domain.errors import ArchaeologistError  # noqa: E402
from app.domain.models import DecisionKind, DecisionRecord  # noqa: E402
from app.memory.hindsight_store import HindsightMemoryStore  # noqa: E402

SEED_FILE = Path(__file__).resolve().parent.parent / "data" / "seed_decisions.json"


def load_records() -> list[DecisionRecord]:
    raw = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    records = []
    for item in raw:
        records.append(
            DecisionRecord(
                entity=item["entity"],
                decision=item["decision"],
                reason=item["reason"],
                author=item["author"],
                occurred_at=datetime.fromisoformat(item["occurred_at"].replace("Z", "+00:00")),
                kind=DecisionKind(item.get("kind", "original")),
                evidence=item.get("evidence"),
                tags=item.get("tags", []),
            )
        )
    return records


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)

    problems = settings.missing_requirements()
    if problems:
        print("Configuration is incomplete:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    store = HindsightMemoryStore(settings)
    print(
        f"Ensuring bank '{settings.hindsight_bank_id}' exists "
        f"at {settings.hindsight_base_url} ..."
    )
    store.ensure_bank()

    records = load_records()
    print(f"Seeding {len(records)} decision records ...")

    ok = 0
    for i, record in enumerate(records, start=1):
        try:
            document_id = store.retain_decision(record)
            print(
                f"  [{i:>2}/{len(records)}] {record.kind.value:<8} "
                f"{record.entity:<28} -> {document_id}"
            )
            ok += 1
        except ArchaeologistError as exc:
            print(f"  [{i:>2}/{len(records)}] FAILED {record.entity}: {exc.user_message}")
        # Hindsight extracts facts asynchronously server-side per request; a short
        # pause keeps us well under any per-second rate limit during a bulk seed.
        time.sleep(0.2)

    print(f"Done: {ok}/{len(records)} records retained.")
    return 0 if ok == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
