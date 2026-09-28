"""Shared form for recording an original decision or a later update.

Record and Update are the same operation at the domain level - a
`DecisionRecord` tagged with its `DecisionKind` - so they share this one form
rather than duplicating field definitions and validation handling.
"""

from __future__ import annotations

from datetime import datetime, time, timezone

import streamlit as st
from pydantic import ValidationError as PydanticValidationError

from app.agent.archaeologist import ArchaeologistAgent
from app.domain.errors import ArchaeologistError
from app.domain.models import DecisionKind, DecisionRecord

_COPY = {
    DecisionKind.ORIGINAL: {
        "help": (
            "Record why a decision was made in the first place: the entity it "
            "governs, what was decided, and the reason. This becomes the start "
            "of that entity's permanent history."
        ),
        "decision_placeholder": "search_api.rate_limit set to 100 requests/sec.",
        "reason_placeholder": "Elasticsearch became unstable above 100 requests/sec.",
        "button": "Record decision",
        "success": "Decision recorded.",
    },
    DecisionKind.UPDATE: {
        "help": (
            "Record new knowledge about an existing decision - a change, a "
            "resolution, or evidence the original reasoning is still valid. This "
            "is added alongside the original; nothing is deleted or overwritten."
        ),
        "decision_placeholder": "search_api.rate_limit left at 100 requests/sec (unchanged).",
        "reason_placeholder": "Elasticsearch was upgraded and the original constraint resolved.",
        "button": "Record update",
        "success": "Update recorded. The original decision is preserved alongside it.",
    },
}


def render(agent: ArchaeologistAgent, kind: DecisionKind) -> None:
    copy = _COPY[kind]
    st.subheader("Record decision" if kind is DecisionKind.ORIGINAL else "Update decision")
    st.caption(copy["help"])

    form_key = f"decision_form_{kind.value}"
    with st.form(form_key, clear_on_submit=True):
        entity = st.text_input(
            "Entity / code identifier",
            placeholder="search_api.rate_limit",
            key=f"{form_key}_entity",
        )
        decision = st.text_area(
            "Decision",
            placeholder=copy["decision_placeholder"],
            key=f"{form_key}_decision",
        )
        reason = st.text_area(
            "Reason (the 'why')",
            placeholder=copy["reason_placeholder"],
            key=f"{form_key}_reason",
        )
        col1, col2 = st.columns(2)
        with col1:
            author = st.text_input("Author", placeholder="Your name", key=f"{form_key}_author")
        with col2:
            occurred_on = st.date_input(
                "Date", value=datetime.now(timezone.utc).date(), key=f"{form_key}_date"
            )
        evidence = st.text_input(
            "Evidence / reference (optional)",
            placeholder="JIRA-1234, PR #56, incident report...",
            key=f"{form_key}_evidence",
        )
        tags_raw = st.text_input(
            "Tags (optional, comma-separated)",
            placeholder="security, performance",
            key=f"{form_key}_tags",
        )
        submitted = st.form_submit_button(copy["button"], type="primary")

    if not submitted:
        return

    try:
        record = DecisionRecord(
            entity=entity,
            decision=decision,
            reason=reason,
            author=author,
            occurred_at=datetime.combine(occurred_on, time(12, 0), tzinfo=timezone.utc),
            kind=kind,
            evidence=evidence or None,
            tags=[t.strip() for t in tags_raw.split(",")] if tags_raw.strip() else [],
        )
    except PydanticValidationError as exc:
        for error in exc.errors():
            st.error(error["msg"])
        return

    with st.spinner("Writing to Hindsight..."):
        try:
            document_id = agent.record_decision(record)
        except ArchaeologistError as exc:
            st.error(exc.user_message)
            return

    st.success(f"{copy['success']} (document id: `{document_id}`)")
    st.caption(f"Ask \"Why is {record.entity} the way it is?\" to see it recalled.")
