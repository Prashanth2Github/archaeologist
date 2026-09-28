# Submission Template

Fill in the bracketed placeholders before submitting. Nothing below is a real
URL — none has been invented on your behalf, per the project's rule against
fabricating submission links.

---

**Project name:** Archaeologist

**Tagline:** The AI that remembers why your code exists.

**One-line description:**
An engineering-decision memory agent that uses Hindsight's RETAIN/RECALL to remember why a technical decision was made, and reconstructs grounded historical answers — with a timeline and decision-drift flag — when a later engineer asks why.

---

## Problem

Every codebase accumulates decisions whose reasoning outlives any one engineer's memory — a rate limit, a timeout, a workaround marked `DO NOT CHANGE`. That reasoning lives in Slack threads, closed tickets, or people's heads, never in the code. When the original engineer leaves the team, the reasoning leaves with them, and everyone left behind either re-litigates the decision or leaves it untouched out of fear.

## Solution

Archaeologist gives engineering decisions persistent, queryable memory. Engineers record what was decided and why through Hindsight's `retain()`; later engineers ask "why does this exist?" and get an answer synthesized only from what was actually recorded — reconstructed as a chronological timeline, with the original memories shown verbatim, and a cautious flag when later-recorded evidence suggests the original reasoning may no longer hold. If nothing was ever recorded, it says so plainly rather than guessing.

## Innovation

The product's entire value proposition depends on memory that persists and accumulates across sessions — not a bigger context window, not RAG over static documents. A second, independently recorded fact changes the correct answer to a previously-asked question without deleting the first fact, and the system has to notice and surface that tension rather than silently picking a winner. That's a genuinely different shape of problem from single-shot chat or code Q&A, and it's why the hackathon's own example categories (incident response, code review, DevOps pipelines) don't cover it.

## How Hindsight is used

- `retain()` for every decision and every later update, with a real-world `timestamp`, an `entity:<id>` tag for scoped recall, structured `metadata` (author, kind, evidence), and explicit `entities` (`CODE_IDENTIFIER`, `PERSON`).
- `recall()` twice per question — a broad semantic pass and, when the question names a code identifier, a second pass scoped to that entity's tag — merged before synthesis.
- A fresh `document_id` on every write, specifically because Hindsight's upsert-by-`document_id` behavior would otherwise delete prior history — the one correctness invariant the product cannot violate.
- No homemade vector store, no shadow copy of memories: Hindsight is the persistence layer, full stop.

Full integration detail: `docs/technical-specification.md` §5.

## Architecture

```
Streamlit UI → ArchaeologistAgent → HindsightMemoryStore → Hindsight
                                  → LLMClient → OpenAI-compatible provider (Groq)
```

Five focused layers (config, domain, memory, llm, agent, ui); see `README.md` §Architecture and `docs/technical-specification.md`.

## UX

Four tabs — Ask, Record decision, Update decision, Timeline — built around one primary interaction ("why does this exist?"). Every failure mode (no memory, Hindsight down, LLM down, invalid input, missing configuration) has an explicit, non-crashing UI state. The timeline and memory panel are the visual centerpiece; no dashboard clutter, no decorative charts.

## Real-world impact

Every engineering team accumulates "don't touch this, nobody remembers why" code. Archaeologist targets that specific, universal cost: decisions that either get re-litigated from scratch or left untouched indefinitely out of fear, because the reasoning behind them was never captured anywhere durable.

## Links

- **GitHub URL:** `[TODO — add before submitting]`
- **Demo video URL:** `[TODO — add after recording, per docs/demo-script.md]`
- **Live demo URL:** `[TODO — only if a live deployment is actually available; do not fabricate]`

## Team

- **Technical articles:** one per team member, outlines in `docs/article-outline.md`.
- **Social posts:** one per team member — under 800 characters, project GitHub link in the main post, Hindsight GitHub link in a comment, 3-5 relevant hashtags, no "hackathon" or student-oriented tags anywhere.
- **Demo video:** one per team, 2-5 minutes, screen recording + voiceover, 1080p minimum, uploaded publicly to YouTube — script in `docs/demo-script.md`.
