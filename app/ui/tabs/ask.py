"""The primary interaction: "Why does this exist?" """

from __future__ import annotations

import streamlit as st

from app.agent.archaeologist import ArchaeologistAgent
from app.domain.errors import ArchaeologistError
from app.ui.components import render_answer

_EXAMPLES = [
    "Why is search_api.rate_limit still 100?",
    "Why is the database connection timeout 30 seconds?",
    "Why does the legacy_api workaround still exist?",
    "Why was the auth token expiry changed?",
]


def render(agent: ArchaeologistAgent) -> None:
    st.subheader("Ask Archaeologist")
    st.caption(
        "Ask why a piece of the codebase is the way it is. Answers are grounded "
        "only in recorded decision memory - never invented."
    )

    with st.expander("Example questions"):
        for example in _EXAMPLES:
            st.markdown(f"- {example}")

    with st.form("ask_form", clear_on_submit=False):
        question = st.text_input(
            "Your question",
            placeholder="Why is search_api.rate_limit still 100?",
            key="ask_question_input",
        )
        submitted = st.form_submit_button("Ask", type="primary")

    if submitted:
        if not question.strip():
            st.error("Please enter a question before asking.")
        else:
            with st.spinner("Recalling relevant history from Hindsight..."):
                try:
                    st.session_state["ask_result"] = agent.ask(question)
                except ArchaeologistError as exc:
                    st.session_state["ask_result"] = None
                    st.error(exc.user_message)

    result = st.session_state.get("ask_result")
    if result is not None:
        st.divider()
        render_answer(result)
