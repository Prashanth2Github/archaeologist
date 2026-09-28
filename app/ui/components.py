"""Reusable rendering for the parts of the UI that appear on multiple tabs.

The timeline and memory panel are the visual centerpiece of the product, so they
live here rather than inline in the tab scripts: the "Ask" tab and the
"Timeline" tab both render the same history, just for a question versus for an
entity.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from app.domain.models import (
    AnswerResult,
    DecisionKind,
    DriftAssessment,
    DriftStatus,
    MemoryConflict,
    MemoryType,
    RecalledMemory,
    TimelineEvent,
)

_DRIFT_ICON = {
    DriftStatus.NO_EVIDENCE: ":material/help:",
    DriftStatus.LIKELY_CURRENT: ":material/check_circle:",
    DriftStatus.NEEDS_REVIEW: ":material/warning:",
    DriftStatus.MAY_BE_OUTDATED: ":material/error:",
}

_KIND_LABEL = {
    DecisionKind.ORIGINAL: "Original decision",
    DecisionKind.UPDATE: "Update",
}

_TYPE_LABEL = {
    MemoryType.WORLD: "fact",
    MemoryType.EXPERIENCE: "event",
    MemoryType.OBSERVATION: "observation",
}


def _format_date(event_time: datetime | None) -> str:
    return event_time.date().isoformat() if event_time else "date not recorded"


def render_drift(assessment: DriftAssessment) -> None:
    """Cautiously worded badge for whether old reasoning may still hold."""
    icon = _DRIFT_ICON.get(assessment.status, ":material/help:")
    if assessment.status is DriftStatus.MAY_BE_OUTDATED:
        st.warning(f"**{assessment.label}**", icon=":material/error:")
    elif assessment.status is DriftStatus.NEEDS_REVIEW:
        st.warning(f"**{assessment.label}**", icon=":material/warning:")
    elif assessment.status is DriftStatus.LIKELY_CURRENT:
        st.success(f"**{assessment.label}**", icon=":material/check_circle:")
    else:
        st.info(f"**{assessment.label}**", icon=icon)

    if assessment.rationale:
        st.caption(assessment.rationale)


def render_conflicts(conflicts: list[MemoryConflict]) -> None:
    """Surface disagreements between memories without picking a side."""
    if not conflicts:
        return
    st.warning(
        f"{len(conflicts)} unresolved conflict(s) in the record below. "
        "Archaeologist does not choose between them.",
        icon=":material/report:",
    )
    for conflict in conflicts:
        with st.container(border=True):
            st.markdown(conflict.summary)
            if conflict.memory_ids:
                st.caption("Memories: " + ", ".join(conflict.memory_ids))


def render_timeline(events: list[TimelineEvent]) -> None:
    """Chronological, oldest-first view of a decision's history.

    Every row is one retrieved memory - nothing here is synthesised.
    """
    if not events:
        st.caption("No timeline to show yet.")
        return

    for i, event in enumerate(events):
        is_last = i == len(events) - 1
        col_marker, col_body = st.columns([1, 11], gap="small")
        with col_marker:
            st.markdown("●" if not event.is_undated else "○")
            if not is_last:
                st.markdown(
                    "<div style='border-left:2px solid var(--st-color-border,#888);"
                    "height:100%;margin-left:8px'></div>",
                    unsafe_allow_html=True,
                )
        with col_body:
            kind_label = (
                _KIND_LABEL[event.kind] if event.kind else _TYPE_LABEL[event.memory_type]
            )
            meta_bits = [f"**{_format_date(event.occurred_at)}**", kind_label]
            if event.author:
                meta_bits.append(f"by {event.author}")
            st.markdown(" &nbsp;·&nbsp; ".join(meta_bits))
            st.markdown(event.text)
            if not is_last:
                st.markdown("")


def render_memory_panel(memories: list[RecalledMemory]) -> None:
    """The evidence panel: exactly what Hindsight returned, never a paraphrase.

    Never renders `metadata` blindly - only the specific fields the product
    promises to show (entity, author, date, decision/reason text) so nothing
    unexpected (or sensitive) that a future field addition might carry leaks in.
    """
    if not memories:
        st.caption("No memories were used for this answer.")
        return

    st.caption(f"{len(memories)} memor{'y' if len(memories) == 1 else 'ies'} used, oldest first.")
    for memory in memories:
        with st.container(border=True):
            top = st.columns([3, 2, 2, 2])
            top[0].markdown(f"**{memory.entity or 'entity unrecorded'}**")
            top[1].caption(memory.author or "author unrecorded")
            top[2].caption(_format_date(memory.effective_time))
            top[3].caption(_TYPE_LABEL[memory.memory_type])
            st.markdown(memory.text)
            if memory.context:
                st.caption(f"Context: {memory.context}")


def render_answer(result: AnswerResult) -> None:
    """Full render of an Ask result: answer, drift, conflicts, timeline, memories."""
    if not result.has_memory:
        st.info(result.answer, icon=":material/history_edu:")
        return

    if result.degraded_reason:
        st.warning(
            f"Answer synthesis is unavailable ({result.degraded_reason}). "
            "Showing raw recorded evidence instead.",
            icon=":material/report:",
        )
    else:
        st.markdown(result.answer)

    render_drift(result.drift)
    render_conflicts(result.conflicts)

    st.divider()
    st.subheader("Timeline")
    render_timeline(result.timeline)

    st.divider()
    st.subheader("Retrieved memories")
    render_memory_panel(result.memories)
