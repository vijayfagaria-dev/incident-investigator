"""What each agent must return. Drafts reach the board only after the runtime checks them."""

from typing import Literal

from pydantic import AwareDatetime, Field

from investigator.domain.base import DomainModel
from investigator.domain.investigation import (
    AgentRole,
    AssumptionDraft,
    EvidenceRequestDraft,
    GapDraft,
    HypothesisDraft,
    LeadDraft,
    ObjectionDraft,
    ObservationDraft,
    Verdict,
)
from investigator.domain.report import Action

Specialty = Literal[AgentRole.OBSERVABILITY, AgentRole.DEPENDENCY]


class PlannedTask(DomainModel):
    agent: Specialty
    focus: str = Field(description="One sentence: what this task should establish.")
    services: tuple[str, ...] = Field(min_length=1)
    start: AwareDatetime
    end: AwareDatetime


class InvestigationPlan(DomainModel):
    rationale: str
    tasks: tuple[PlannedTask, ...] = Field(min_length=1, max_length=3)


class FollowUpPlan(DomainModel):
    tasks: tuple[PlannedTask, ...] = ()
    dropped: tuple[str, ...] = Field(default=(), description="Requests not pursued, and why.")


class Findings(DomainModel):
    summary: str
    observations: tuple[ObservationDraft, ...] = ()
    leads: tuple[LeadDraft, ...] = ()
    gaps: tuple[GapDraft, ...] = ()


class KeyedAssumption(AssumptionDraft):
    key: str = Field(description="A label such as A1 that hypotheses use to reference it.")


class KeyedObservation(ObservationDraft):
    """An observation reported together with the hypotheses that cite it."""

    key: str = Field(description="A label such as F1 that hypotheses use to reference it.")


class KeyedAnalogy(KeyedObservation):
    """A past incident that resembles this one, citing its pir: id."""

    key: str = Field(description="A label such as N1 that hypotheses use to reference it.")


class HypothesisSet(DomainModel):
    hypotheses: tuple[HypothesisDraft, ...] = Field(min_length=1, max_length=4)
    assumptions: tuple[KeyedAssumption, ...] = ()
    analogies: tuple[KeyedAnalogy, ...] = ()
    requests: tuple[EvidenceRequestDraft, ...] = Field(default=(), max_length=3)


class VerdictDraft(DomainModel):
    hypothesis_id: str
    verdict: Verdict
    reason: str


class Assessment(DomainModel):
    verdicts: tuple[VerdictDraft, ...]
    objections: tuple[ObjectionDraft, ...] = ()
    requests: tuple[EvidenceRequestDraft, ...] = Field(default=(), max_length=3)


class ReportNarrative(DomainModel):
    summary: str
    actions: tuple[Action, ...] = ()
    open_questions: tuple[str, ...] = ()


class SoloAnswer(DomainModel):
    """Everything the single-agent baseline concludes, in one answer."""

    summary: str
    observations: tuple[KeyedObservation, ...] = ()
    assumptions: tuple[KeyedAssumption, ...] = ()
    hypotheses: tuple[HypothesisDraft, ...] = Field(default=(), max_length=4)
    gaps: tuple[GapDraft, ...] = ()
    actions: tuple[Action, ...] = ()
    open_questions: tuple[str, ...] = ()
