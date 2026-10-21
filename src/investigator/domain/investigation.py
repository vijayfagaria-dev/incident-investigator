"""What agents exchange during an investigation.

Agents produce drafts. The blackboard checks each draft against what has actually been
observed, then gives it an id. Facts (observations) must cite artifacts returned by tools
in this run; assumptions are kept separate and never count as evidence.
"""

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, Field

from investigator.domain.artifacts import ArtifactId
from investigator.domain.base import DomainModel
from investigator.domain.causes import RootCause


class AgentRole(StrEnum):
    ORCHESTRATOR = "orchestrator"
    OBSERVABILITY = "observability"
    DEPENDENCY = "dependency"
    REASONING = "reasoning"
    CRITIC = "critic"
    REPORTING = "reporting"
    SOLO = "solo"
    """The single-agent baseline, which does every job itself."""


class EvidenceDomain(StrEnum):
    OBSERVABILITY = "observability"
    """Logs and metrics."""
    CHANGES = "changes"
    """Deploys, config and flag changes, and the dependency graph."""
    HISTORY = "history"


class ObservationDraft(DomainModel):
    statement: str = Field(
        description="One fact, stated plainly, e.g. 'p99 rose from 0.5s to 4s at 10:04'."
    )
    artifacts: tuple[ArtifactId, ...] = Field(
        min_length=1, description="Ids of the tool results that show this fact."
    )
    service: str | None = None


class Observation(ObservationDraft):
    id: str
    source: str
    """The task that produced it."""


class AssumptionDraft(DomainModel):
    statement: str
    reason: str = Field(description="Why it is believed without direct evidence.")


class Assumption(AssumptionDraft):
    id: str
    source: str


class LeadDraft(DomainModel):
    """Something worth checking in another evidence domain."""

    domain: EvidenceDomain
    question: str
    service: str | None = None
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None


class Lead(LeadDraft):
    id: str
    source: str


class GapDraft(DomainModel):
    """Evidence that could not be gathered, and why."""

    tool: str
    scope: str
    reason: str


class EvidenceGap(GapDraft):
    id: str
    source: str


class HypothesisDraft(DomainModel):
    id: str | None = Field(
        default=None, description="Id of a hypothesis being revised; omit for new ones."
    )
    root_cause: RootCause
    mechanism: str = Field(description="How the cause produces the observed symptoms.")
    supporting: tuple[str, ...] = Field(default=(), description="Observation ids that support it.")
    contradicting: tuple[str, ...] = Field(
        default=(), description="Observation ids that cut against it."
    )
    assumptions: tuple[str, ...] = Field(default=(), description="Assumption ids it relies on.")
    predictions: tuple[str, ...] = Field(
        default=(), description="What else should be true if it holds; each is checkable."
    )
    confidence: float = Field(ge=0, le=1)


class Hypothesis(HypothesisDraft):
    id: str
    version: int
    round: int


class ObjectionKind(StrEnum):
    UNSUPPORTED_CLAIM = "unsupported_claim"
    TEMPORAL_VIOLATION = "temporal_violation"
    IGNORES_CONTRADICTION = "ignores_contradiction"
    ALTERNATIVE_NOT_EXCLUDED = "alternative_not_excluded"
    SYMPTOM_NOT_CAUSE = "symptom_not_cause"
    ANALOGY_ONLY = "analogy_only"
    GAP_UNADDRESSED = "gap_unaddressed"

    @property
    def is_flaw(self) -> bool:
        """Whether it finds the hypothesis wrong as stated, not merely untested so far."""
        return self not in _OPEN_QUESTIONS


_OPEN_QUESTIONS = frozenset({ObjectionKind.ALTERNATIVE_NOT_EXCLUDED, ObjectionKind.GAP_UNADDRESSED})


class ObjectionSeverity(StrEnum):
    BLOCKING = "blocking"
    """The hypothesis cannot be accepted until this is resolved."""
    MINOR = "minor"


class ObjectionDraft(DomainModel):
    hypothesis_id: str
    kind: ObjectionKind
    severity: ObjectionSeverity
    detail: str
    alternative: str | None = Field(
        default=None,
        description="For alternative_not_excluded: the id of the hypothesis not yet ruled out.",
    )


class Objection(ObjectionDraft):
    source: Literal["rule", "critic"]
    """Raised by a deterministic check, or by the critic agent."""


class EvidenceRequestDraft(DomainModel):
    question: str
    domain: EvidenceDomain
    service: str | None = None
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    discriminates: tuple[str, ...] = Field(
        default=(), description="Hypothesis ids the answer would tell apart."
    )


class EvidenceRequest(EvidenceRequestDraft):
    id: str
    requested_by: str
    round: int


class Verdict(StrEnum):
    ACCEPT = "accept"
    CHALLENGE = "challenge"
    REJECT = "reject"


class CriticReview(DomainModel):
    round: int
    verdicts: dict[str, Verdict]
    objections: tuple[Objection, ...] = ()
    requests: tuple[EvidenceRequest, ...] = ()
