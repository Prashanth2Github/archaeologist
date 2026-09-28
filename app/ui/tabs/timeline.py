"""Decision Timeline tab: full recorded history for one entity, plus the raw
memory panel it was built from.
"""

from __future__ import annotations

import streamlit as st

from app.agent.archaeologist import ArchaeologistAgent
from app.agent.timeline import build_timeline
from app.domain.errors import ArchaeologistError
from app.domain.models import RecalledMemory, normalize_entity
from app.ui.components import render_memory_panel, render_timeline


def render(agent: ArchaeologistAgent) -> None:
    st.subheader("Decision timeline")
    st.caption(
        "Look up the full recorded history for one entity: original decision, "
        "every later update, oldest first."
    )

    with st.form("timeline_form"):
        entity = st.text_input(
            "Entity / code identifier",
            placeholder="search_api.rate_limit",
            key="timeline_entity_input",
        )
        submitted = st.form_submit_button("Show timeline", type="primary")

    if submitted:
        if not entity.strip():
            st.error("Please enter an entity to look up.")
        else:
            with st.spinner("Recalling history from Hindsight..."):
                try:
                    fetched = agent.entity_history(normalize_entity(entity))
                    st.session_state["timeline_entity"] = entity.strip()
                    st.session_state["timeline_memories"] = fetched
                except ArchaeologistError as exc:
                    st.session_state["timeline_memories"] = None
                    st.error(exc.user_message)

    memories: list[RecalledMemory] | None = st.session_state.get("timeline_memories")
    shown_entity = st.session_state.get("timeline_entity")
    if memories is None:
        return

    st.divider()
    if not memories:
        st.info(
            f"I don't have recorded historical context for \"{shown_entity}\".",
            icon=":material/history_edu:",
        )
        return

    unit = "memory" if len(memories) == 1 else "memories"
    st.markdown(f"**{shown_entity}** - {len(memories)} recorded {unit}")
    render_timeline(build_timeline(memories))

    st.divider()
    st.subheader("Retrieved memories")
    render_memory_panel(memories)
