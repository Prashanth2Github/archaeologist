# Demo Script

Target runtime: ~4 minutes. Timings are guidance, not a strict cue sheet — pause where the audience needs a beat.

**Before recording:** run `python scripts/seed_memory.py` against a fresh bank, confirm the app is up (`streamlit run app/ui/streamlit_app.py`), and confirm `search_api.rate_limit` has **not** been recorded yet (it's excluded from seed data by design). Have the Ask, Record, and Timeline tabs ready in separate browser positions if screen-recording live rather than cutting between takes.

---

## 0:00–0:30 — Intro

> "Every codebase has a line like this somewhere:
> `RATE_LIMIT = 100  // DO NOT CHANGE`
> Nobody remembers why. This is Archaeologist — it remembers why your engineering decisions were made, and it never guesses when it doesn't know."

*(Show the app title screen — "The AI that remembers why your code exists.")*

## 0:30–1:00 — The problem

> "The reasoning behind a decision like this lives in a Slack thread, a closed ticket, or one engineer's memory — never in the code itself. When that engineer leaves, the reasoning leaves with them. Everyone else either re-litigates the decision from scratch, or — more often — leaves it alone forever, afraid to touch it."

*(Cut to the Ask tab, empty.)*

## 1:00–3:30 — Demo

**Session 1 — ask before anything is recorded** *(~30s)*

> "Let's ask Archaeologist why `search_api.rate_limit` is set to 100."

Type: *Why is search_api.rate_limit still 100?* → Ask.

> "Nothing recorded. Archaeologist doesn't guess — it says so plainly."

*(Point out: "I don't have recorded historical context for this decision.")*

**Session 1 — record the original decision** *(~40s)*

> "Let's say Priya was the engineer who set this limit, back in April 2023. She records it."

Switch to **Record decision** tab. Fill in:
- Entity: `search_api.rate_limit`
- Decision: `search_api.rate_limit set to 100 requests/sec.`
- Reason: `Elasticsearch became unstable above 100 requests/sec.`
- Author: `Priya Raman`
- Date: `2023-04-11`
- Evidence: `Incident INC-1229`

Submit → point out the success message and document id. *"That's a real write to Hindsight — RETAIN."*

**Session 2 — record that the constraint was resolved** *(~40s)*

> "More than a year later, Marcus upgrades the Elasticsearch cluster and confirms the original problem is gone."

Switch to **Update decision** tab. Fill in:
- Entity: `search_api.rate_limit`
- Decision: `search_api.rate_limit left at 100 requests/sec (unchanged).`
- Reason: `Elasticsearch was upgraded to a larger cluster and the original stability constraint was resolved in testing. The rate limit itself was not changed.`
- Author: `Marcus Webb`
- Date: `2024-08-02`

Submit. *"Notice: this doesn't overwrite Priya's original record. It's added alongside it."*

**Session 3 — ask again** *(~60s)*

> "Now a third engineer, six months later, asks the same question."

Switch to **Ask** tab. Type the same question again → Ask.

> "This time, Archaeologist recalls both memories, reconstructs the full history, and — this is the important part — flags decision drift."

*(Point out, in order: the grounded answer citing both Priya and Marcus by name and date; the drift badge — "may be outdated" — with its cautious rationale; the timeline, oldest first; the memory panel showing exactly what was recalled.)*

> "It never says the code is wrong. It says the record shows the original reason may no longer apply, and that it requires review. That's the difference between a chatbot guessing and an agent that actually remembers."

*(Optional, if time allows — ~20s)* Switch to **Timeline** tab, look up `legacy_api.workaround` from the seed data — a workaround kept in place after the vendor fixed the bug it worked around. *"This isn't staged for the demo — it's the same mechanism working on real seed data."*

## 3:30–4:00 — Conclusion

> "Archaeologist doesn't index your code and doesn't replace code review. It remembers the *decisions* — persistently, attributably, and it's honest the moment it doesn't know something. That's what 'AI agents that learn using hindsight' means here: not a bigger context window, but memory that actually accumulates and gets reasoned over across time. Thank you."

---

## Fallback if live demo fails

Keep a terminal ready with `python scripts/run_primary_demo.py` — it runs this exact story headlessly against the same live Hindsight bank and prints the full output (answer, drift, timeline, memories) if the UI has any issue mid-recording.
