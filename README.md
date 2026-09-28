# Archaeologist

**The AI that remembers why your code exists.**

> Built for the *AI Agents That Learn Using Hindsight* theme. Hindsight's RETAIN / RECALL memory primitives are not a bolted-on feature here — they are the entire product. Remove Hindsight and there is nothing left to build.

Every codebase has a `RATE_LIMIT = 100 // DO NOT CHANGE` somewhere. The engineer who wrote it knows why. Six months later, nobody else does — the reason is buried in a Slack thread, a closed ticket, or someone's memory of a bad Tuesday in production.

Archaeologist is an engineering-decision memory agent. Engineers record *what* was decided and *why*; later engineers ask *why does this exist?* and get a grounded historical answer, reconstructed from what was actually recorded — never invented.

---

## Contents

- [The problem](#the-problem)
- [The solution](#the-solution)
- [Why memory matters here](#why-memory-matters-here)
- [Architecture](#architecture)
- [Hindsight integration](#hindsight-integration)
- [The RETAIN / RECALL flow](#the-retain--recall-flow)
- [Decision timeline](#decision-timeline)
- [Decision drift](#decision-drift)
- [Setup](#setup)
- [Environment variables](#environment-variables)
- [Running](#running)
- [Testing](#testing)
- [Worked example](#worked-example)
- [Limitations](#limitations)
- [Future work](#future-work)
- [Security](#security)

---

## The problem

Engineering decisions accumulate context that outlives any one engineer's memory:

- *Why* is this rate limit 100 and not 1000?
- *Why* does this workaround exist — is the bug it works around even still present?
- *Was* this timeout ever revisited, or has everyone just been afraid to touch it?

That context lives in conversations, PRs, tickets, and people's heads — not in the code. When the person who made the decision leaves the team, the reasoning leaves with them. Everyone left behind either re-litigates the decision from scratch or, more often, leaves `DO NOT CHANGE` alone forever out of fear.

## The solution

Archaeologist gives engineering decisions **persistent, queryable memory**:

1. An engineer **records** a decision — the entity it governs, what was decided, why, who decided it, and when — through Hindsight's `retain()`.
2. Later, a different engineer **asks** "why does this exist?" Archaeologist runs Hindsight's `recall()` against the decision memory bank, orders what comes back chronologically, and asks an LLM to synthesize a grounded answer — citing only what was actually recorded.
3. If the reasoning has since changed — a later engineer recorded that the original constraint was resolved — Archaeologist surfaces that as **decision drift**: cautious language ("may no longer apply," "requires review"), never a confident claim that the code is wrong.
4. If nothing was ever recorded, Archaeologist says so plainly: *"I don't have recorded historical context for this decision."* It never fabricates history to fill the gap.

## Why memory matters here

This is not a RAG-over-documentation demo and not a chatbot wrapped around a codebase. The product's entire value proposition is **temporal, accumulating, attributable memory**:

- Every update is retained *alongside* the original, never overwriting it — history is additive, following Hindsight's document model.
- Chronology is preserved and computed deterministically from timestamps, not left to an LLM to reconstruct or silently reorder.
- The system's job is to notice when a decision's original justification may have been superseded by later-recorded facts — a task that is impossible without memory that persists and accumulates across sessions, which is exactly what Hindsight's RETAIN/RECALL model provides and a stateless chatbot cannot.

Take Hindsight away and there is no timeline, no drift detection, and no grounded answer — just an LLM guessing. That coupling is deliberate.

## Architecture

```
                     ┌──────────────────────┐
                     │   Streamlit UI        │  app/ui/
                     │  Ask · Record ·        │
                     │  Update · Timeline     │
                     └──────────┬────────────┘
                                │
                     ┌──────────▼────────────┐
                     │  ArchaeologistAgent    │  app/agent/
                     │  question parsing      │
                     │  chronological sort     │
                     │  drift/conflict guard   │
                     └────┬──────────────┬────┘
                          │              │
             ┌────────────▼───┐   ┌──────▼──────────┐
             │ HindsightMemory │   │   LLMClient      │  app/llm/
             │ Store           │   │  (OpenAI-        │
             │ RETAIN / RECALL │   │  compatible)      │
             └────────┬────────┘   └──────┬───────────┘
                      │                    │
              ┌───────▼──────┐     ┌───────▼────────┐
              │  Hindsight    │     │  Groq / any     │
              │  (memory)     │     │  OpenAI-compat  │
              │               │     │  LLM provider   │
              └───────────────┘     └─────────────────┘
```

Layer responsibilities (`app/`):

| Layer | Module | Responsibility |
|---|---|---|
| UI | `app/ui/` | Streamlit tabs, rendering, session state. No business logic. |
| Agent | `app/agent/` | Orchestrates recall → synthesis → drift. Question parsing, deterministic timeline construction. |
| Memory | `app/memory/` | The **only** module that imports the Hindsight SDK. RETAIN/RECALL request construction, response mapping, error translation. |
| LLM | `app/llm/` | Prompt templates and an OpenAI-compatible chat client with full provider-error mapping. |
| Domain | `app/domain/` | Pydantic models and validation (`DecisionRecord`, `RecalledMemory`, `DriftAssessment`, ...) and the application exception hierarchy. |
| Config | `app/config/` | Environment-driven settings, redacted-for-display config summary. |
| Services | `app/services/` | Composition root — wires the agent from settings. |

No database is used for application data: Hindsight *is* the persistence layer, as required. There is no homemade vector store, no shadow copy of memories, nothing to keep in sync.

## Hindsight integration

Archaeologist talks to Hindsight exclusively through the official [`hindsight-client`](https://pypi.org/project/hindsight-client/) Python SDK (`app/memory/hindsight_store.py`) — no hand-rolled HTTP calls, no reimplemented retrieval.

- **One memory bank** (`HINDSIGHT_BANK_ID`, default `archaeologist`) holds every engineering decision.
- Every decision is written with `entity:<normalized-entity>` as a Hindsight **tag**, so recall can be scoped precisely to one code identifier (`search_api.rate_limit`) as well as searched broadly across the whole bank.
- **`metadata`** carries `entity`, `author`, `kind` (`original`/`update`), and `evidence` — returned verbatim on recall, so the memory panel never has to re-derive who said what.
- **`entities`** are explicitly declared on retain (`CODE_IDENTIFIER`, `PERSON`) so Hindsight's entity graph recognizes them reliably rather than depending on extraction alone.
- **`timestamp`** on retain is the decision's real-world date, not the write time — this is what lets Hindsight's temporal retrieval and our own chronological sort agree with each other.
- Every record gets a **fresh, unique `document_id`**. Reusing a `document_id` would make Hindsight delete the previous document (its documented upsert behavior) — which would destroy exactly the history this product exists to protect. Updates are new documents, never edits.
- Recall uses `budget="high"` by default (configurable) for the exhaustive retrieval the drift/conflict analysis depends on, plus `tags_match="any_strict"` when scoped to one entity so untagged noise from other memories doesn't dilute a precise lookup.

## The RETAIN / RECALL flow

```
Engineer records a decision
        │
        ▼
DecisionRecord (validated: entity, decision, reason, author, date, evidence?, tags?)
        │
        ▼
Hindsight RETAIN  ── content: structured narrative · timestamp · tags · metadata · entities
        │
        ▼
Persistent memory (Hindsight extracts and stores structured facts)

        ⋯ time passes, more decisions and updates are retained ⋯

Engineer asks "why does this exist?"
        │
        ▼
Hindsight RECALL  ── broad semantic query + entity-scoped tag query, merged
        │
        ▼
Memories sorted chronologically (deterministic, in code — never by the LLM)
        │
        ▼
LLM synthesis (grounded-only prompt; retrieved memories are fenced as untrusted data)
        │
        ▼
Answer + Timeline + Decision Drift + Memory Panel + any unresolved Conflicts
```

The LLM is never the source of historical truth — only its narrator. It cannot cite a memory that was not actually retrieved: every id it references is checked against what Hindsight returned, and anything it invents is silently dropped rather than displayed (see `app/agent/archaeologist.py::_filter_ids`).

## Decision timeline

The timeline is **not generated** — it is computed by sorting retrieved memories on their real-world `occurred_at` (falling back to `mentioned_at` when a memory has no event date), oldest first (`app/agent/timeline.py`). An LLM asked to "order these events" can silently drop or invent one; a sort cannot. The model's only job is to *explain* the history that this deterministic step already established.

## Decision drift

After synthesizing an answer, Archaeologist separately asks the model to assess whether the *original* reasoning still appears to hold, using only what has been recorded:

| Status | Meaning |
|---|---|
| `no_evidence` | Nothing recorded speaks to whether the original reasoning still applies. |
| `likely_current` | The record contains evidence the original constraint still holds. |
| `needs_review` | The record hints the situation changed, but ambiguously or incompletely. |
| `may_be_outdated` | Later evidence suggests the original constraint was resolved, yet the decision appears unchanged. |

Archaeologist never asserts that code is *wrong* — only that the *record* suggests review, using deliberately hedged language throughout ("may no longer apply," "appears outdated," "requires review"). If retrieved memories disagree with each other, both sides are shown with their authors and dates; the system does not silently pick a winner.

## Setup

**Requirements:** Python 3.10+, a Hindsight endpoint (Cloud or self-hosted), and an API key for an OpenAI-compatible LLM provider (Groq recommended).

```bash
git clone <this-repo>
cd archaeologist
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env
# edit .env — see Environment variables below
```

> **Windows note:** if `python` resolves to an MSYS2/MinGW build (`python -c "import sysconfig; print(sysconfig.get_platform())"` prints something containing `mingw`), standard PyPI wheels (including Streamlit's and Pydantic's compiled dependencies) will fail to install. Install Python from [python.org](https://www.python.org/) or via `winget install Python.Python.3.12` and use that interpreter for the virtualenv instead.

### Hindsight

Pick one:

- **Hindsight Cloud** (no local install): sign up at `https://ui.hindsight.vectorize.io/signup`, then set `HINDSIGHT_BASE_URL` and `HINDSIGHT_API_KEY` to the values it gives you.
- **Self-hosted (Docker)**:
  ```bash
  docker run -it --pull always --name hindsight --restart unless-stopped \
    --shm-size=1g -p 8888:8888 -p 9999:9999 \
    -e HINDSIGHT_API_LLM_PROVIDER=groq \
    -e HINDSIGHT_API_LLM_API_KEY=$GROQ_API_KEY \
    -v hindsight-data:/home/hindsight/.pg0 \
    ghcr.io/vectorize-io/hindsight:latest
  ```
  Then set `HINDSIGHT_BASE_URL=http://localhost:8888` and leave `HINDSIGHT_API_KEY` blank.

### LLM provider

Any OpenAI-compatible endpoint works. For Groq: create a free key at `https://console.groq.com/keys` and set `LLM_API_KEY`. The hackathon-suggested models (`openai/gpt-oss-120b`, `qwen/qwen3-32b`) are both available on Groq.

## Environment variables

See [`.env.example`](.env.example) for the full annotated list. Summary:

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `HINDSIGHT_BASE_URL` | yes | `http://localhost:8888` | Hindsight server endpoint. |
| `HINDSIGHT_API_KEY` | yes for remote/Cloud | *(empty)* | Bearer token. Usually unnecessary for local Docker. |
| `HINDSIGHT_BANK_ID` | no | `archaeologist` | Memory bank holding all decisions. |
| `HINDSIGHT_RECALL_BUDGET` | no | `high` | Retrieval depth: `low`/`mid`/`high`. |
| `HINDSIGHT_RECALL_MAX_TOKENS` | no | `4096` | Token budget for recalled fact text. |
| `LLM_BASE_URL` | yes | Groq's endpoint | Any OpenAI-compatible chat completions endpoint. |
| `LLM_API_KEY` | **yes** | *(empty)* | Required — Archaeologist cannot synthesize answers without it. |
| `LLM_MODEL` | no | `openai/gpt-oss-120b` | Model id. |
| `LOG_LEVEL` | no | `INFO` | Application log verbosity. |

Missing required configuration is detected at startup and shown as a setup panel in the UI — never a stack trace.

## Running

```bash
# 1. Seed realistic demo data (~22 decisions across 16 entities)
python scripts/seed_memory.py

# 2. Launch the app
streamlit run app/ui/streamlit_app.py
```

Open `http://localhost:8501`. Use the **Ask** tab, or run the exact primary demo story end-to-end from the command line:

```bash
python scripts/run_primary_demo.py
```

This runs the full "unknown → retain → retain update → recall → synthesis → drift" sequence against your live, configured Hindsight bank and LLM — see [Worked example](#worked-example).

## Testing

```bash
pytest              # 79 unit tests — all external services mocked, no network calls
ruff check app scripts tests
mypy app scripts
```

Unit tests cover: decision validation, RETAIN/RECALL request construction, chronological ordering, decision-drift classification, conflicting-memory handling, malformed and unavailable LLM responses, every mapped Hindsight/LLM failure mode, missing configuration, and empty/invalid input. All external services (the Hindsight SDK, the OpenAI-compatible client) are mocked at the SDK boundary — no test makes a network call.

`scripts/run_primary_demo.py` is an integration script, not a unit test: it talks to a real, configured Hindsight bank and a real LLM provider. It is documented, not run in CI, and its result is only as good as the credentials you provide — see [Final verification](#limitations) for what has and has not actually been exercised in this environment.

## Worked example

The primary demo, run via `scripts/run_primary_demo.py` or the **Ask** tab:

**Session 1 — before anything is recorded**
> Q: *Why is search_api.rate_limit still 100?*
> A: *I don't have recorded historical context for this decision.*

**Session 1 — record the original decision**
> Priya Raman, 2023-04-11: "search_api.rate_limit set to 100 requests/sec. Elasticsearch became unstable above 100 requests/sec." → **RETAIN**

**Session 2 — record that the constraint was resolved**
> Marcus Webb, 2024-08-02: "Elasticsearch was upgraded to a larger cluster and the original stability constraint was resolved in testing. The rate limit itself was not changed." → **RETAIN**

**Session 3 — ask again**
> Q: *Why is search_api.rate_limit still 100?*
> A: *(synthesized from both memories, citing Priya Raman's 2023-04-11 original constraint and Marcus Webb's 2024-08-02 note that Elasticsearch was upgraded and the constraint resolved)*
> **Drift: may be outdated** — the record shows the original stability constraint was resolved, but the limit itself was never revisited.
> **Timeline:** two entries, oldest first.
> **Memory panel:** both memories, with author, date, and full text.

`search_api.rate_limit` is deliberately excluded from the seed data (`data/seed_decisions.json`) so this "no memory yet" state in Session 1 is genuine, not staged.

## Limitations

- **English only.** Prompts, extraction, and UI copy are not localized.
- **Single memory bank.** One bank per deployment; no per-team or per-repo partitioning (Hindsight supports multi-bank/multi-tag scoping — this MVP intentionally uses one bank for simplicity).
- **Entity-hint extraction is a regex heuristic**, not an LLM call (`app/agent/questions.py`) — by design, for speed and determinism, but it will miss code identifiers that don't look like `dotted.names`.
- **No automatic conflict resolution.** Archaeologist surfaces disagreements between memories; a human still has to resolve them.
- **Drift assessment is advisory**, generated by the LLM from retrieved evidence — it is a prompt to investigate, not a verified fact, and is always phrased with that uncertainty.
- **No authentication or multi-tenancy.** This is a single-team MVP, not a production multi-org SaaS.
- **No benchmarks are claimed anywhere in this project** — only what has actually been run and observed is described as such.

## Future work

Explicitly out of scope for this MVP (see hackathon prompt §17), documented here as natural extensions rather than built:

- Hindsight's `reflect()` primitive for deeper cross-decision reasoning and consolidated observations, beyond the `retain()`/`recall()` pair this MVP uses.
- Slack/Teams/Jira ingestion so decisions can be captured where engineers already discuss them, instead of requiring manual entry.
- Full repository indexing to auto-suggest which code identifiers lack recorded history.
- CI integration that nudges a PR author to record a decision when a "magic number" changes without an accompanying Archaeologist entry.
- Multi-bank / multi-repo support with per-team scoping.
- SSO and multi-tenancy for organization-wide deployment.

## Security

- **No secrets are committed.** `.env` is git-ignored; only `.env.example` (with placeholder values) is tracked. `.gitignore` also excludes `*.key`, `*.pem`, and `secrets/`.
- **Configuration is validated at startup** (`app/config/settings.py`); missing or malformed values produce a setup panel, never a stack trace.
- **Nothing sensitive is logged.** No credential value is ever passed to a logger anywhere in this codebase; the sidebar's config summary shows only `set`/`not set`.
- **User-facing errors never leak internals.** Every `ArchaeologistError` carries a separate `user_message` shown in the UI; the full exception (with stack trace) only ever reaches the server log.
- **Retrieved memories are treated as untrusted input.** The synthesis prompt explicitly fences recalled text as data, instructs the model never to treat it as instructions, and never to reveal the system prompt — a defense against prompt injection via memory content (`app/llm/prompts.py`).
- **Input is bounded and validated.** Entities, decisions, reasons, authors, evidence, tags, and questions all have explicit length limits and format rules (`app/domain/models.py`); invalid input is rejected before it reaches Hindsight or the LLM.
- **Timeouts everywhere.** Both the Hindsight client and the LLM client have configurable timeouts (`HINDSIGHT_TIMEOUT_SECONDS`, `LLM_TIMEOUT_SECONDS`) and the LLM client uses the provider SDK's built-in retry/backoff for transient failures.
