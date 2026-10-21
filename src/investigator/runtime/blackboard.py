"""Shared state of one investigation.

Agents never write here directly: they return drafts, and the runtime commits them through
these methods. Committing is where the evidence rules are enforced, so nothing reaches the
board citing an artifact no tool returned, or an observation that does not exist.
"""

from collections import Counter
from collections.abc import Container, Iterable, Sequence
from dataclasses import dataclass

from investigator.domain.artifacts import ArtifactKind, artifact_kind
from investigator.domain.base import DomainModel
from investigator.domain.incident import IncidentReport
from investigator.domain.investigation import (
    Assumption,
    AssumptionDraft,
    CriticReview,
    EvidenceGap,
    EvidenceRequest,
    EvidenceRequestDraft,
    GapDraft,
    Hypothesis,
    HypothesisDraft,
    Lead,
    LeadDraft,
    Observation,
    ObservationDraft,
)
from investigator.domain.tools import ToolStatus
from investigator.tools.results import ToolResult


@dataclass(frozen=True)
class Commit:
    """What a commit accepted, and what it refused or changed, in words an agent can act on."""

    accepted: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()


class BoardView(DomainModel):
    """A read-only snapshot for agents."""

    incident: IncidentReport
    round: int
    observations: tuple[Observation, ...]
    assumptions: tuple[Assumption, ...]
    leads: tuple[Lead, ...]
    gaps: tuple[EvidenceGap, ...]
    hypotheses: tuple[Hypothesis, ...]
    """The current version of each hypothesis."""
    reviews: tuple[CriticReview, ...]
    requests: tuple[EvidenceRequest, ...]

    @property
    def latest_review(self) -> CriticReview | None:
        return self.reviews[-1] if self.reviews else None

    def evidence_kinds(self, hypothesis: Hypothesis) -> set[ArtifactKind]:
        """The kinds of artifact (log, metric, chg, ...) behind a hypothesis's support."""
        observations = {o.id: o for o in self.observations}
        kinds: set[ArtifactKind] = set()
        for observation_id in hypothesis.supporting:
            if observation_id in observations:
                kinds |= {artifact_kind(a) for a in observations[observation_id].artifacts}
        return kinds


class Blackboard:
    def __init__(self, incident: IncidentReport) -> None:
        self.incident = incident
        self.round = 0
        self._counters: Counter[str] = Counter()
        self._artifacts: dict[str, str] = {}
        self._tool_results: list[ToolResult] = []
        self._observations: dict[str, Observation] = {}
        self._assumptions: dict[str, Assumption] = {}
        self._leads: list[Lead] = []
        self._gaps: list[EvidenceGap] = []
        self._hypotheses: dict[str, Hypothesis] = {}
        self._reviews: list[CriticReview] = []
        self._requests: list[EvidenceRequest] = []

    def record_tool_results(self, results: Iterable[ToolResult]) -> None:
        """Make the artifacts these results returned citable."""
        for result in results:
            self._tool_results.append(result)
            if result.status is not ToolStatus.ERROR:
                for artifact in result.artifacts:
                    self._artifacts.setdefault(artifact, result.call_id)

    def knows_artifact(self, artifact: str) -> bool:
        return artifact in self._artifacts

    def tool_results(self) -> tuple[ToolResult, ...]:
        return tuple(self._tool_results)

    def add_findings(
        self,
        source: str,
        observations: Sequence[ObservationDraft] = (),
        assumptions: Sequence[AssumptionDraft] = (),
        leads: Sequence[LeadDraft] = (),
        gaps: Sequence[GapDraft] = (),
    ) -> Commit:
        accepted: list[str] = []
        problems: list[str] = []
        for draft in observations:
            known: list[str] = []
            unknown: list[str] = []
            for artifact in draft.artifacts:
                (known if self.knows_artifact(artifact) else unknown).append(artifact)
            if not known:
                problems.append(
                    f"dropped observation citing nothing returned by a tool: {draft.statement!r}"
                )
                continue
            if unknown:
                problems.append(f"removed citations no tool returned: {', '.join(unknown)}")
            observation = Observation(
                **draft.model_dump(exclude={"artifacts"}),
                artifacts=tuple(known),
                id=self._next_id("OBS"),
                source=source,
            )
            self._observations[observation.id] = observation
            accepted.append(observation.id)
        for assumption_draft in assumptions:
            assumption = Assumption(
                **assumption_draft.model_dump(), id=self._next_id("ASM"), source=source
            )
            self._assumptions[assumption.id] = assumption
            accepted.append(assumption.id)
        for lead_draft in leads:
            lead = Lead(**lead_draft.model_dump(), id=self._next_id("LEAD"), source=source)
            self._leads.append(lead)
            accepted.append(lead.id)
        for gap_draft in gaps:
            gap = EvidenceGap(**gap_draft.model_dump(), id=self._next_id("GAP"), source=source)
            self._gaps.append(gap)
            accepted.append(gap.id)
        return Commit(tuple(accepted), tuple(problems))

    def add_hypotheses(self, drafts: Sequence[HypothesisDraft]) -> Commit:
        """Add hypotheses, citing only known evidence.

        A draft revises the hypothesis it names by id. Without a known id, it revises the
        hypothesis that already names the same root cause, so one explanation is never
        counted twice; otherwise it is new. When one commit holds two drafts of the same
        hypothesis, the more confident one stands: a cause is at least as likely as its
        best explanation.
        """
        accepted: list[str] = []
        problems: list[str] = []
        for draft in drafts:
            hypothesis_id = self._hypothesis_to_revise(draft, problems)
            if hypothesis_id is None:
                hypothesis_id, version = self._next_id("HYP"), 1
            elif hypothesis_id in accepted:
                earlier = self._hypotheses[hypothesis_id]
                problems.append(f"kept the more confident of two drafts of {hypothesis_id}")
                if draft.confidence <= earlier.confidence:
                    continue
                version = earlier.version
            else:
                version = self._hypotheses[hypothesis_id].version + 1
            supporting = self._drop_unknown_ids(draft.supporting, self._observations, problems)
            contradicting = self._drop_unknown_ids(
                draft.contradicting, self._observations, problems
            )
            assumptions = self._drop_unknown_ids(draft.assumptions, self._assumptions, problems)
            self._hypotheses[hypothesis_id] = Hypothesis(
                **draft.model_dump(exclude={"id", "supporting", "contradicting", "assumptions"}),
                id=hypothesis_id,
                version=version,
                round=self.round,
                supporting=supporting,
                contradicting=contradicting,
                assumptions=assumptions,
            )
            if hypothesis_id not in accepted:
                accepted.append(hypothesis_id)
        return Commit(tuple(accepted), tuple(problems))

    def add_requests(
        self, drafts: Sequence[EvidenceRequestDraft], requested_by: str
    ) -> list[EvidenceRequest]:
        requests = []
        for draft in drafts:
            requests.append(
                EvidenceRequest(
                    **draft.model_dump(),
                    id=self._next_id("REQ"),
                    requested_by=requested_by,
                    round=self.round,
                )
            )
        self._requests += requests
        return requests

    def add_review(self, review: CriticReview) -> None:
        self._reviews.append(review)

    def start_round(self) -> int:
        self.round += 1
        return self.round

    def view(self) -> BoardView:
        return BoardView(
            incident=self.incident,
            round=self.round,
            observations=tuple(self._observations.values()),
            assumptions=tuple(self._assumptions.values()),
            leads=tuple(self._leads),
            gaps=tuple(self._gaps),
            hypotheses=tuple(self._hypotheses.values()),
            reviews=tuple(self._reviews),
            requests=tuple(self._requests),
        )

    def _next_id(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return f"{prefix}-{self._counters[prefix]}"

    def _hypothesis_to_revise(self, draft: HypothesisDraft, problems: list[str]) -> str | None:
        if draft.id is not None and draft.id in self._hypotheses:
            return draft.id
        for hypothesis_id, hypothesis in self._hypotheses.items():
            if hypothesis.root_cause == draft.root_cause:
                problems.append(f"merged into {hypothesis_id}, which names the same root cause")
                return hypothesis_id
        if draft.id is not None:
            problems.append(f"no hypothesis {draft.id} to revise; added it as new")
        return None

    @staticmethod
    def _drop_unknown_ids(
        ids: Iterable[str], known: Container[str], problems: list[str]
    ) -> tuple[str, ...]:
        kept: list[str] = []
        unknown: list[str] = []
        for i in ids:
            (kept if i in known else unknown).append(i)
        if unknown:
            problems.append(f"removed references to unknown ids: {', '.join(unknown)}")
        return tuple(kept)
