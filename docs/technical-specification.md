# Archaeologist — Technical Specification

## 1. Purpose

Archaeologist is an engineering-decision memory agent: it persists *why* a decision was made (entity, decision, reason, author, date, optional evidence) via Hindsight's `retain()`, and reconstructs grounded historical answers via Hindsight's `recall()` plus LLM synthesis. This document specifies the system's components, data flow, and the contracts between them, for engineers extending or auditing the codebase.

## 2. Non-goals

Explicitly out of scope (see README §Future work for the full rationale):

- Slack/Teams/Jira ingestion, full repository indexing, autonomous code changes, CI/CD integration.
- Multi-tenancy, SSO, billing, multi-bank routing.
- A homemade replacement for Hindsight's retrieval (semantic/keyword/graph/temporal fusion) — this is Hindsight's job, not ours.

## 3. Component map

```
app/
├── config/settings.py       Pydantic-settings configuration, validated at startup
├── domain/
│   ├── models.py             DecisionRecord, RecalledMemory, TimelineEvent,
│   │                         DriftAssessment, MemoryConflict, AnswerResult
│   └── errors.py             ArchaeologistError hierarchy (user-safe messages)
├── memory/hindsight_store.py HindsightMemoryStore — the only module importing
│                             the Hindsight SDK. RETAIN/RECALL + error mapping.
├── llm/
│   ├── client.py             LLMClient (OpenAI-compatible), JSON extraction,
│   │                         provider-error mapping
│   └── prompts.py            System/user prompt templates, grounding rules
├── agent/
│   ├── archaeologist.py      ArchaeologistAgent — orchestrates ask()/record_decision()
│   ├── questions.py          Question validation, entity-hint extraction (regex)
│   └── timeline.py           Deterministic chronological sort + timeline construction
├── services/factory.py       Composition root (build_agent, bootstrap)
└── ui/
    ├── streamlit_app.py      Entry point, page config, tab wiring
    ├── state.py               st.cache_resource wiring, config-or-stop helpers
    ├── components.py          Shared render functions (timeline, memory panel, drift)
    └── tabs/                  ask.py, record.py, update.py, timeline.py, decision_form.py
```

## 4. Data model

### 4.1 `DecisionRecord` (write path)

| Field | Type | Constraints |
|---|---|---|
| `entity` | `str` | 1-120 chars, `^[A-Za-z0-9][A-Za-z0-9._:/-]*$` |
| `decision` | `str` | 1-2000 chars |
| `reason` | `str` | 1-4000 chars |
| `author` | `str` | 1-120 chars |
| `occurred_at` | `datetime` | naive datetimes assumed UTC |
| `kind` | `original \| update` | default `original` |
| `evidence` | `str \| None` | ≤1000 chars, blank → `None` |
| `tags` | `list[str]` | ≤10 tags, ≤50 chars each, deduplicated, lowercased |

`memory_tags` (property) = `[f"entity:{normalize(entity)}", *tags]` — this is what actually gets written as Hindsight tags.

### 4.2 `RecalledMemory` (read path)

Maps 1:1 from a Hindsight `RecallResult` (`hindsight_client_api.models.recall_result.RecallResult`). Notable derived properties:

- `effective_time` = `occurred_at or mentioned_at` — used for all chronological sorting.
- `author`, `entity`, `kind` — read from the `metadata` dict Hindsight returns verbatim (written at retain time), with `entity` falling back to parsing the `entity:` tag if metadata is absent.

### 4.3 `AnswerResult` (agent output)

Bundles `answer` (str), `has_memory` (bool), `memories` (list, oldest-first), `timeline` (list, computed), `drift` (`DriftAssessment`), `conflicts` (list), and `degraded_reason` (set only when LLM synthesis failed but recall succeeded).

## 5. Hindsight integration contract

Verified directly against the installed `hindsight-client` SDK (introspected via `inspect.signature`, not assumed from documentation alone) before implementation. Key signatures used:

```python
Hindsight(base_url: str, api_key: str | None = None, timeout: float = 300.0, ...)

Hindsight.retain(
    bank_id: str, content: str, timestamp: datetime | None = None,
    context: str | None = None, document_id: str | None = None,
    metadata: dict[str, str] | None = None, entities: list[dict[str, str]] | None = None,
    tags: list[str] | None = None, update_mode: str | None = None,
    retain_async: bool = False, operation_id: str | None = None,
) -> RetainResponse

Hindsight.recall(
    bank_id: str, query: str, types: list[str] | None = None,
    max_tokens: int = 4096, budget: str = "mid", tags: list[str] | None = None,
    tags_match: Literal["any","all","any_strict","all_strict","exact"] = "any",
    include_entities: bool = False, ...
) -> RecallResponse   # .results: list[RecallResult]
```

### 5.1 RETAIN construction (`HindsightMemoryStore.retain_decision`)

1. Render `DecisionRecord` into a prose narrative via `build_decision_narrative()` — written so entity, actor, action, and rationale are each independently extractable by Hindsight's fact extraction.
2. Mint a **fresh** `document_id` (`{entity}:{kind}:{uuid4[:12]}`). Reusing a `document_id` triggers Hindsight's documented upsert-by-delete behavior, which would destroy prior history — the one invariant this product cannot violate.
3. Set `timestamp=record.occurred_at` (the decision's real-world date, not now) so Hindsight's temporal retrieval and our own chronological sort agree.
4. Set `tags=record.memory_tags` (entity scope + user tags) and `metadata` (entity, author, kind, evidence, source — all stringified, empties dropped).
5. Declare `entities=[{"text": entity, "type": "CODE_IDENTIFIER"}, {"text": author, "type": "PERSON"}]` explicitly rather than relying solely on extraction.

### 5.2 RECALL construction (`HindsightMemoryStore.recall_for_question`)

Two recalls are issued and merged (broad result kept first on id collision):

1. A broad semantic recall over the whole bank with the raw question.
2. If `extract_entity_hint()` found a dotted identifier in the question, a second recall scoped with `tags=[entity_tag(hint)]`, `tags_match="any_strict"` (excludes untagged memories, unlike the default `"any"`).

Both use `budget=HINDSIGHT_RECALL_BUDGET` (default `high`) and `include_entities=True`. Results are capped at `MAX_MEMORIES_PER_ANSWER = 24` before being handed to the LLM.

### 5.3 Error mapping

`HindsightMemoryStore._map_error` translates every SDK/transport failure into the application's own exception set — response *bodies* are logged (for diagnosis) but never surfaced to the user, since they can echo request content:

| SDK exception | Mapped to | User-visible message |
|---|---|---|
| `UnauthorizedException`, `ForbiddenException` | `MemoryAuthError` | "Hindsight rejected the configured API key." |
| `NotFoundException` | `MemoryServiceError` | "The configured Hindsight memory bank was not found." |
| `ServiceException`, `BadRequestException`, `ApiException` | `MemoryServiceError` | "Hindsight {op} failed (HTTP {status})." |
| any exception whose message contains "timeout"/"timed out" | `MemoryTimeoutError` | "Hindsight {op} timed out." |
| anything else | `MemoryServiceError` | "Hindsight {op} failed: {ExceptionType}" |

## 6. LLM integration contract

`LLMClient` wraps any OpenAI-compatible `chat.completions.create` endpoint (`app/llm/client.py`). Provider and model are pure configuration (`LLM_BASE_URL`, `LLM_MODEL`) — Groq, OpenAI, Together, etc. are interchangeable without a code change.

### 6.1 Request

- `response_format={"type": "json_object"}` is requested first; if the provider rejects it with `BadRequestError` (`400`), the client transparently retries once without it (some models/providers don't support JSON mode) — see `test_json_mode_rejection_falls_back_to_plain_completion`.
- `temperature=LLM_TEMPERATURE` (default `0.1`) — low, since this is a grounded-synthesis task, not creative generation.

### 6.2 Response parsing

`extract_json_object()` tries, in order: the raw string as JSON, a fenced ` ```json ... ``` ` block, then the outermost `{...}` span — because models reliably wrap JSON in prose or fences even when explicitly asked not to. Raises `LLMResponseError` if none parse into a JSON object.

### 6.3 Error mapping

| SDK exception | Mapped to |
|---|---|
| `AuthenticationError`, `PermissionDeniedError` | `LLMAuthError` |
| `RateLimitError` | `LLMRateLimitError` |
| `APITimeoutError` | `LLMTimeoutError` |
| `APIConnectionError` | `LLMError` |
| `APIStatusError`, other `OpenAIError` | `LLMError` |
| malformed/empty response content | `LLMResponseError` |

`LLMClient` itself uses the OpenAI SDK's built-in retry/backoff (`max_retries=LLM_MAX_RETRIES`) for transient connection failures.

## 7. Agent orchestration (`ArchaeologistAgent.ask`)

```
validate_question(question)                       -> ValidationError if empty/too long
extract_entity_hint(question)                      -> str | None (regex, not LLM)
store.recall_for_question(question, hint)          -> list[RecalledMemory]  (MemoryServiceError propagates)
  if empty: return AnswerResult(has_memory=False, answer=NO_MEMORY_ANSWER)   # honest unknown
sort_memories_chronologically(memories)            -> oldest-first (deterministic)
build_timeline(ordered)                            -> list[TimelineEvent]   (deterministic)
llm.complete_json(SYNTHESIS_SYSTEM_PROMPT, build_synthesis_user_prompt(...))
  on LLMError: return AnswerResult(has_memory=True, memories, timeline, degraded_reason=...)
              # never crash the user's session over a synthesis failure
_read_answer / _read_drift / _read_conflicts       -> defensive field parsing, unknown drift
                                                       statuses default to no_evidence, cited
                                                       memory ids not in `ordered` are dropped
return AnswerResult(...)
```

Design invariant: **the LLM cannot introduce a fact that was not retrieved.** Every memory id it cites (in `drift_memory_ids` or `conflicts[].memory_ids`) is checked against the set of ids actually returned by Hindsight for this question; anything else is silently filtered (`_filter_ids`), not displayed as if it were real.

## 8. UI data flow

Streamlit reruns the whole script on every interaction. Expensive objects (`Settings`, `ArchaeologistAgent`) are built once via `st.cache_resource` (`app/ui/state.py`). Each tab (`app/ui/tabs/*.py`) is a thin `render(agent)` function; results that must survive a rerun (the last `AnswerResult`, the last timeline lookup) are stashed in `st.session_state`.

Failure states are rendered explicitly, never left to surface as a raw traceback:

| State | UI treatment |
|---|---|
| Missing/invalid configuration | Blocking setup panel listing exactly what's missing, before any tab renders. |
| Empty/invalid input | Inline `st.error` with the specific validation message. |
| No memory recalled | `st.info` with the honest-unknown message — a normal, expected state, not an error. |
| Hindsight failure | `st.error(exc.user_message)` — no stack trace, no response body. |
| LLM failure (recall succeeded) | `st.warning` + the raw recalled memories and timeline are still shown (`degraded_reason`). |
| Conflicting memories | `st.warning` banner + each conflict rendered with its supporting memory ids — never auto-resolved. |

## 9. Security posture

See README §Security for the user-facing summary. Implementation notes:

- `Settings.describe_redacted()` is the *only* function permitted to render configuration in the UI; it returns `"set"`/`"not set"` for secrets, never the value.
- No logger call anywhere in the codebase is passed an API key, bearer token, or full Hindsight/LLM response body — verified by inspection of every `logger.*` call site during review (§11 of the build process).
- `app/llm/prompts.py::SYNTHESIS_SYSTEM_PROMPT` explicitly fences retrieved memories as `<retrieved_memories>` **data**, instructs the model never to treat their contents as instructions, and never to reveal the system prompt — the mitigation for prompt injection via memory content, since memories originate from arbitrary user-supplied `decision`/`reason` text.
- All user-facing exceptions descend from `ArchaeologistError`, which separates an internal `message` (logged) from a `user_message` (displayed) — the UI never renders a raw exception.

## 10. Testing strategy

79 unit tests (`tests/`), all external services mocked at the SDK boundary (`unittest.mock.patch` on `hindsight_client.Hindsight` and `openai.OpenAI` — no network call in the suite):

| File | Coverage |
|---|---|
| `test_domain_models.py` | `DecisionRecord` validation rules (entity format, length limits, tag dedup, tz normalization) |
| `test_questions.py` | Question validation, entity-hint extraction (including URL/abbreviation false-positive guards) |
| `test_timeline.py` | Chronological sort (undated-last, occurred_at vs mentioned_at fallback), timeline construction |
| `test_llm_client.py` | JSON extraction (plain/fenced/embedded), every mapped provider error, JSON-mode-rejection fallback |
| `test_hindsight_store.py` | RETAIN kwargs (tags/metadata/timestamp/document_id uniqueness), RECALL merge behavior, every mapped Hindsight error |
| `test_agent.py` | Honest-unknown path, grounded synthesis, drift statuses, hallucinated-citation filtering, conflicting memories, LLM degradation, Hindsight failure propagation |
| `test_settings.py` | Missing/invalid configuration detection, secret redaction |

`scripts/run_primary_demo.py` is the integration path — it exercises the exact primary-demo story against a real, configured Hindsight bank and LLM provider. It is intentionally not part of the pytest suite (it requires live credentials and network access) and is not claimed as a passing "integration test" unless it has actually been run in the target environment — see README §Limitations for what is and is not verified in this repository as delivered.

## 11. Known trade-offs

- Entity-hint extraction is a regex, not an LLM call — a deliberate latency/determinism trade-off (README §Limitations).
- Drift assessment is generated by the same synthesis call as the answer, sharing one LLM round-trip rather than two, to keep the "Ask" interaction fast for a live demo.
- The timeline and memory panel intentionally share one component (`app/ui/components.py`) rather than duplicating rendering logic between the Ask tab and the Timeline tab.
