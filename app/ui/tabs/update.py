"""Update Decision tab."""

from __future__ import annotations

from app.agent.archaeologist import ArchaeologistAgent
from app.domain.models import DecisionKind
from app.ui.tabs import decision_form


def render(agent: ArchaeologistAgent) -> None:
    decision_form.render(agent, DecisionKind.UPDATE)
