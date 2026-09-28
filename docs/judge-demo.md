# Judge Walkthrough

A reference for anyone presenting or evaluating Archaeologist — pitch, architecture, the case for Hindsight specifically, and anticipated questions.

## 60-second pitch

Archaeologist remembers *why* engineering decisions were made. An engineer records a decision and its reason through Hindsight's `retain()`. Months later, a different engineer asks "why does this exist?" and Archaeologist reconstructs the answer through Hindsight's `recall()` — citing exactly who said what and when, flagging when the original reasoning may be outdated, and saying "I don't know" plainly when nothing was recorded. It is not a chatbot over your code; it is a decision historian with persistent, accumulating memory.

## The problem, concretely

```
MAX_RETRIES = 3
RATE_LIMIT = 100
// DO NOT CHANGE
```

The reason for that comment is not in the file. It's in a Slack thread, a closed Jira ticket, or the memory of an engineer who may no longer be at the company. Nobody wants to be the one who removes `DO NOT CHANGE` and finds out the hard way why it was there — so it never gets revisited, even after the original reason has expired.

## The solution

1. **RETAIN** — decisions and later updates are written to Hindsight as dated, attributed, tagged memories. Updates never overwrite originals.
2. **RECALL** — a question triggers both a broad semantic recall and, when the question names a specific identifier, a second recall scoped to that entity's tag.
3. **Deterministic chronology** — memories are sorted oldest-first in code, not by the LLM, so the timeline can never silently drop or reorder an event.
4. **Grounded synthesis** — an LLM explains the history using only what was retrieved, with retrieved memories fenced as untrusted data so they cannot override the system's instructions.
5. **Decision drift** — the system flags, in deliberately cautious language, when later-recorded evidence suggests the original reasoning may no longer hold.

## Architecture at a glance

```
Streamlit UI → ArchaeologistAgent → HindsightMemoryStore → Hindsight (RETAIN/RECALL)
                                  → LLMClient → any OpenAI-compatible provider (Groq)
```

Five layers (`config`, `domain`, `memory`, `llm`, `agent`, `ui`), each with a single responsibility. `app/memory/hindsight_store.py` is the *only* module that imports the Hindsight SDK — full detail in `docs/technical-specification.md`.

## Why Hindsight specifically — not a generic vector DB

- **Temporal grounding is native, not bolted on.** Retain accepts a real-world `timestamp`; recall's temporal retrieval strategy ranks by it. A generic vector store would require us to build that ourselves.
- **Tag-scoped retrieval maps directly onto "one entity, many decisions over time."** `entity:search_api.rate_limit` as a Hindsight tag gives precise, scoped recall without a second index.
- **The upsert-by-`document_id` model forced the one correctness decision that matters most here**: every retain call mints a fresh `document_id`, specifically *because* reusing one deletes the prior document. That single constraint, straight from Hindsight's documented behavior, is what guarantees history is never silently destroyed.
- **Structured fact extraction, not raw storage.** Hindsight extracts entities, dates, and facts from the narrative we retain — we do not manage embeddings, chunking, or extraction ourselves.

Remove Hindsight from this project and there is no timeline, no drift detection, and no grounded answer — just an LLM guessing from nothing. The memory layer is not a feature; it is the product.

## Demo sequence (see `docs/demo-script.md` for the full script)

1. Ask about `search_api.rate_limit` → honest "no recorded history."
2. Record the original decision (Priya Raman, 2023) → RETAIN.
3. Record that the constraint was later resolved (Marcus Webb, 2024) → RETAIN, additive.
4. Ask again → RECALL both, grounded answer, timeline, decision-drift flag.

## Likely judge questions

**"Isn't this just RAG over a document store?"**
No — RAG answers from static documents. This system's value is in what happens *after* the first retain: a second, independent fact later changes the correct answer to the same question, without deleting the first fact, and the system has to notice the tension between them. That's temporal reasoning over accumulating memory, not single-shot document retrieval.

**"How do you stop the model from hallucinating history?"**
The synthesis prompt is grounded-only by instruction, but we don't rely on the prompt alone: every memory id the model cites (for drift or conflicts) is checked in code against the ids Hindsight actually returned; anything else is dropped before it reaches the UI (`app/agent/archaeologist.py::_filter_ids`). Retrieved memories are also fenced as untrusted data in the prompt, so their contents can't be read as instructions.

**"What happens if Hindsight or the LLM is down?"**
Every Hindsight and LLM failure mode is caught and mapped to a specific, user-safe error (see `docs/technical-specification.md` §5.3, §6.3). If recall succeeds but synthesis fails, the app doesn't fail closed — it shows the raw recalled memories and timeline with a clear "synthesis unavailable" notice, since the memory itself is still useful even without a generated summary.

**"Why Streamlit and not a custom frontend?"**
Judging criteria weight technical implementation and UX, not frontend framework novelty. Streamlit let us spend the build budget on the memory/agent layer — where the actual innovation is — while still shipping a clean, demo-ready UI with proper loading/error/empty states.

**"Does this scale beyond a demo?"**
Not as shipped — see README §Limitations. It's a single-bank, single-tenant MVP by design, matching the hackathon's request for a tightly scoped build. The natural extensions (multi-bank, PR/ticket ingestion, `reflect()`-based consolidation) are documented, not built, per the explicit "do not overbuild" guidance.

**"What's not verified?"**
Anything requiring live Hindsight/LLM credentials that weren't available at build time is explicitly marked **NOT VERIFIED** rather than claimed — see the verification checklist referenced in the project's final report. All 79 unit tests, lint, and type checks have actually been run and pass.

## Limitations to state proactively

- Single memory bank, no multi-tenancy.
- Entity-hint extraction is a regex heuristic, not an LLM call.
- Drift assessment is advisory, not a verified fact.
- No integrations beyond the manual Record/Update UI — deliberately, per scope.
