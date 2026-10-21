"""The investigation report: the system's answer, and everything needed to check it."""

from enum import StrEnum
from typing import Literal

from pydantic import Field

from investigator.domain.base import DomainModel
from investigator.domain.causes import Outcome, RootCause
from investigator.domain.investigation import (
    Assumption,
    EvidenceGap,
    Hypothesis,
    Objection,
    Observation,
    Verdict,
)


class ActionKind(StrEnum):
    MITIGATE = "mitigate"
    """Stop the impact now."""
    FIX = "fix"
    """Remove the cause."""
    PREVENT = "prevent"
    """Stop it from happening again."""
    INVESTIGATE = "investigate"
    """Close a question the evidence left open."""


class Action(DomainModel):
    kind: ActionKind
    description: str
    rationale: str
    hypothesis_id: str | None = Field(
        default=None, description="The hypothesis it addresses, if any."
    )
    urgency: Literal["now", "soon", "later"]


ConfidenceBand = Literal["high", "medium", "low"]


class RankedHypothesis(DomainModel):
    rank: int
    hypothesis: Hypothesis
    confidence: float
    """Calibrated: the stated confidence, capped by what the evidence can bear."""
    calibration: tuple[str, ...] = ()
    """Why the stated confidence was capped, if it was."""
    confidence_band: ConfidenceBand
    verdict: Verdict | None
    """The critic's latest verdict, if it reviewed this hypothesis."""
    objections: tuple[Objection, ...] = ()


class RunStats(DomainModel):
    rounds: int
    model_calls: int
    tool_calls: int
    tokens: int
    elapsed_s: float


class Report(DomainModel):
    incident_id: str
    title: str
    outcome: Outcome
    outcome_reasons: tuple[str, ...] = ()
    """Why the outcome is inconclusive; empty when it is conclusive."""
    summary: str
    root_cause: RootCause | None
    hypotheses: tuple[RankedHypothesis, ...]
    facts: tuple[Observation, ...]
    """Observations cited by the hypotheses."""
    assumptions: tuple[Assumption, ...]
    gaps: tuple[EvidenceGap, ...]
    actions: tuple[Action, ...]
    open_questions: tuple[str, ...]
    termination: str
    """Why the investigation stopped."""
    stats: RunStats
