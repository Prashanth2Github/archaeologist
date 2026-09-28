# Technical Article Outlines

Each team member writes one public, technical, English-language article, 800-1,500 words per the official guide (the generation-prompt range of 1,200-2,000 overlaps at 1,200-1,500 — aim there to satisfy both). None of these outlines contain "hackathon" anywhere, and none use student-oriented or `#Hackathon`-style tags — keep that true in the final draft and in any hashtags used.

Do not fabricate personal experience, benchmark numbers, or production results in the final article. If an outline below suggests a claim ("we saw X"), only keep it if it actually happened during this build; otherwise reframe it as a design rationale instead of an anecdote.

Pick one angle per author so the team's articles don't overlap.

---

## Angle 1 — "Why your rate limit comment is a memory problem, not a documentation problem"

**Audience:** engineers who've hit `DO NOT CHANGE` comments and wondered.

**Outline:**
1. The concrete failure mode: a constraint outlives the reasoning behind it, and removing it feels riskier than leaving it.
2. Why this isn't solved by "just write better comments" — the reasoning changes over time (constraints get resolved, get worse, get partially superseded), and a static comment can't track that.
3. Reframe as a memory problem: what's needed is not a comment, but a system that can answer "why," attribute it, date it, and tell you if anything has changed since.
4. Introduce Archaeologist's RETAIN/RECALL loop as the concrete mechanism, using the `search_api.rate_limit` example end to end.
5. Show the decision-drift output for a case where the original reasoning was later resolved but the code wasn't revisited — the moment this stops being "a Q&A bot" and becomes something closer to institutional memory.
6. Close with what's deliberately not solved (multi-repo indexing, automatic capture) and why that scoping was the right call for a first version.

## Angle 2 — "Building on Hindsight: what RETAIN/RECALL actually forces you to get right"

**Audience:** engineers evaluating Hindsight or building their own memory-backed agent.

**Outline:**
1. The core design tension in any memory-backed agent: how do you add new knowledge without destroying old knowledge, and how do you know when new knowledge contradicts old knowledge?
2. Hindsight's document model and the `document_id` upsert behavior — explain the gotcha (reusing an id deletes the prior document) and why that single behavior shaped the entire write path (`retain_decision` mints a fresh id every time).
3. Tag-scoped recall as the mechanism for "give me everything about entity X" versus "search broadly" — with the `entity:<id>` tagging convention as the concrete example.
4. What grounding an LLM in recalled memories actually requires beyond "put it in the prompt": fencing retrieved content as untrusted data, checking every cited id against what was actually retrieved, and computing chronology in code rather than trusting the model to get temporal ordering right.
5. What was verified against the SDK directly (via `inspect.signature`) rather than assumed from docs, and why that mattered once building started.
6. Close with what `reflect()` (not used in this MVP) could add for cross-decision consolidation — framed as a natural next step, not a claim about what was built.

## Angle 3 — "Designing an agent that says 'I don't know' on purpose"

**Audience:** engineers building LLM products who are wary of hallucination.

**Outline:**
1. The specific failure this project is built to avoid: an agent that invents a plausible-sounding but false historical justification when no real one was ever recorded.
2. Why "honest unknown" is a first-class UI state here, not an edge case — walk through what happens when `recall()` returns nothing.
3. The three concrete mechanisms that keep answers grounded: (a) retrieved memories fenced as untrusted data in the prompt, (b) chronology computed deterministically rather than left to the model, (c) every cited memory id checked against what was actually retrieved before being shown.
4. What happens when the LLM itself fails but memory doesn't — degrading to raw recalled evidence instead of failing the whole interaction, and why that's the right trade-off for a memory-first product specifically.
5. The cautious-language design for decision drift ("may no longer apply," never "this is wrong") and why hedged uncertainty is a feature, not a hedge against liability.
6. Close with the broader principle: for a memory agent, being wrong is worse than being unhelpful, so every design choice erred toward the latter.
