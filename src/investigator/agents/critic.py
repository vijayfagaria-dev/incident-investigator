"""The critic: deterministic checks first, then a model that challenges what the checks cannot."""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime

from investigator.agents import briefing
from investigator.agents.base import Agent, load_prompt
from investigator.agents.outputs import Assessment
from investigator.domain.investigation import (
    AgentRole,
    CriticReview,
    EvidenceRequest,
    Hypothesis,
    Objection,
    ObjectionKind,
    ObjectionSeverity,
    Verdict,
)
from investigator.domain.tools import ToolName
from investigator.runtime.agent_loop import AgentLoop, AgentRun, AgentSpec
from investigator.runtime.blackboard import Blackboard, BoardView
from investigator.tools.changes import ChangeQueryResult
from investigator.tools.results import ToolResult


def observed_changes(results: Iterable[ToolResult]) -> dict[str, datetime]:
    """Every change a change-history call returned in this run, with when it happened."""
    changes: dict[str, datetime] = {}
    for result in results:
        if result.tool == ToolName.GET_CHANGE_HISTORY and result.output is not None:
            for change in ChangeQueryResult.model_validate(result.output).changes:
                changes[change.id] = change.ts
    return changes


def rule_objections(view: BoardView, changes: Mapping[str, datetime]) -> list[Objection]:
    """Objections that need no judgement, so they never depend on a model getting them right."""
    objections = []
    for hypothesis in view.hypotheses:
        objections += _trigger_problems(hypothesis, view, changes)
        if not hypothesis.supporting:
            objections.append(
                _blocking(hypothesis.id, ObjectionKind.UNSUPPORTED_CLAIM, "cites no observations")
            )
            continue
        kinds = view.evidence_kinds(hypothesis)
        if kinds and kinds <= {"pir"}:
            detail = "supported only by past incidents, not by evidence from this one"
            objections.append(_blocking(hypothesis.id, ObjectionKind.ANALOGY_ONLY, detail))
    return objections


def _trigger_problems(
    hypothesis: Hypothesis, view: BoardView, changes: Mapping[str, datetime]
) -> list[Objection]:
    """A triggering change must be one a tool returned, and must precede the report."""
    trigger = hypothesis.root_cause.trigger
    if trigger is None:
        return []
    if trigger not in changes:
        detail = f"names {trigger} as the trigger, but no change-history query returned it"
        return [_blocking(hypothesis.id, ObjectionKind.UNSUPPORTED_CLAIM, detail)]
    if changes[trigger] > view.incident.reported_at:
        detail = f"{trigger} happened after the incident was reported, so it cannot have caused it"
        return [_blocking(hypothesis.id, ObjectionKind.TEMPORAL_VIOLATION, detail)]
    return []


def _blocking(hypothesis_id: str, kind: ObjectionKind, detail: str) -> Objection:
    return Objection(
        hypothesis_id=hypothesis_id,
        kind=kind,
        severity=ObjectionSeverity.BLOCKING,
        detail=detail,
        source="rule",
    )


def demote_dismissed_alternatives(
    objections: Sequence[Objection], verdicts: Mapping[str, Verdict]
) -> list[Objection]:
    """Stop an alternative from blocking a hypothesis once the review has dismissed it.

    An alternative blocks acceptance only while it still stands: it is on the board, and the
    same review neither rejected it nor found a blocking flaw in it. Without this, two
    hypotheses can block each other indefinitely even when one has nothing behind it.
    """
    fallen = {h for h, verdict in verdicts.items() if verdict is Verdict.REJECT} | {
        o.hypothesis_id
        for o in objections
        if o.severity is ObjectionSeverity.BLOCKING and o.kind.is_flaw
    }
    settled = []
    for objection in objections:
        reason = _dismissal_reason(objection, verdicts, fallen)
        if reason is not None:
            objection = objection.model_copy(
                update={
                    "severity": ObjectionSeverity.MINOR,
                    "detail": f"{objection.detail} (not blocking: {reason})",
                }
            )
        settled.append(objection)
    return settled


def _dismissal_reason(
    objection: Objection, verdicts: Mapping[str, Verdict], fallen: set[str]
) -> str | None:
    if (
        objection.kind is not ObjectionKind.ALTERNATIVE_NOT_EXCLUDED
        or objection.severity is not ObjectionSeverity.BLOCKING
    ):
        return None
    alternative = objection.alternative
    if alternative is None or alternative not in verdicts:
        return "it names no hypothesis on the board"
    if alternative in fallen:
        return f"this review rejected {alternative} or found it flawed"
    return None


class CriticAgent(Agent[Assessment]):
    def __init__(self, loop: AgentLoop) -> None:
        super().__init__(
            loop,
            AgentSpec(
                role=AgentRole.CRITIC,
                system_prompt=load_prompt("critic", evidence=load_prompt("evidence")),
                output_model=Assessment,
            ),
        )

    def brief(self, view: BoardView, rule_objections: list[Objection]) -> str:
        found = "\n".join(f"- {o.hypothesis_id}: {o.kind}: {o.detail}" for o in rule_objections)
        return "\n\n".join(
            (
                briefing.incident(view.incident),
                f"Round {view.round}.",
                f"Observations:\n{briefing.observations(view.observations)}",
                f"Evidence gaps:\n{briefing.gaps(view.gaps)}",
                f"Hypotheses to review:\n{briefing.hypotheses(view.hypotheses)}",
                f"Problems automated checks already found:\n{found or briefing.NONE}",
            )
        )

    def review(
        self,
        board: Blackboard,
        run: AgentRun[Assessment] | None,
        rule_objections: list[Objection],
    ) -> CriticReview:
        """Commit a review. Without a model assessment, every hypothesis stays challenged."""
        view = board.view()
        verdicts = {h.id: Verdict.CHALLENGE for h in view.hypotheses}
        known = set(verdicts)
        objections = list(rule_objections)
        requests: tuple[EvidenceRequest, ...] = ()
        if run is not None:
            assessment = run.output
            verdicts |= {
                v.hypothesis_id: v.verdict for v in assessment.verdicts if v.hypothesis_id in known
            }
            objections += [
                Objection(**o.model_dump(), source="critic")
                for o in assessment.objections
                if o.hypothesis_id in known
            ]
            requests = tuple(board.add_requests(assessment.requests, requested_by=AgentRole.CRITIC))
        # A blocking objection from the checks overrides acceptance by the model.
        for objection in rule_objections:
            if verdicts.get(objection.hypothesis_id) is Verdict.ACCEPT:
                verdicts[objection.hypothesis_id] = Verdict.CHALLENGE
        review = CriticReview(
            round=view.round,
            verdicts=verdicts,
            objections=tuple(demote_dismissed_alternatives(objections, verdicts)),
            requests=requests,
        )
        board.add_review(review)
        return review
