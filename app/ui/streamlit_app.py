"""Archaeologist - Streamlit entry point.

Run with:
    streamlit run app/ui/streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allows `streamlit run app/ui/streamlit_app.py` to import the `app` package
# without requiring the project to be pip-installed first.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st  # noqa: E402

from app.config.settings import Settings  # noqa: E402
from app.ui.state import get_agent_or_stop, load_configuration_or_none  # noqa: E402
from app.ui.tabs import ask, record, timeline, update  # noqa: E402

st.set_page_config(
    page_title="Archaeologist",
    page_icon=":material/history_edu:",
    layout="centered",
)


def _render_setup_panel(problems: list[str]) -> None:
    st.title("Archaeologist")
    st.caption("The AI that remembers why your code exists.")
    st.error("Setup is incomplete.", icon=":material/settings:")
    for problem in problems:
        st.markdown(f"- {problem}")
    st.markdown(
        "Copy `.env.example` to `.env`, fill in the values above, and restart "
        "the app. See the README for full setup instructions."
    )


def _render_sidebar(settings: Settings) -> None:
    with st.sidebar:
        st.title("Archaeologist")
        st.caption("Your codebase remembers the decisions that created it.")
        st.divider()
        st.caption("Configuration")
        for label, value in settings.describe_redacted().items():
            st.text(f"{label}: {value}")
        st.divider()
        st.caption(
            "Memory is powered by Hindsight (RETAIN / RECALL). Answers are grounded "
            "only in what has been recorded - never invented."
        )


def main() -> None:
    settings, problems = load_configuration_or_none()
    if problems:
        _render_setup_panel(problems)
        return

    _render_sidebar(settings)
    agent = get_agent_or_stop(settings)

    st.title("Archaeologist")
    st.caption("The AI that remembers why your code exists.")

    tab_ask, tab_record, tab_update, tab_timeline = st.tabs(
        ["Ask", "Record decision", "Update decision", "Timeline"]
    )
    with tab_ask:
        ask.render(agent)
    with tab_record:
        record.render(agent)
    with tab_update:
        update.render(agent)
    with tab_timeline:
        timeline.render(agent)


main()
