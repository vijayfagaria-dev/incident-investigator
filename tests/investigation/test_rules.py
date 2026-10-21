"""Policies, critic rules, follow-up planning and report rendering: the deterministic parts."""

from datetime import UTC, datetime

from investigator.agents.critic import CriticAgent, demote_dismissed_alternatives, rule_objections
from investigator.agents.outputs import PlannedTask, ReportNarrative
from investigator.domain.causes import CauseCategory, Outcome, RootCause
from investigator.domain.investigation import (
    AgentRole,
    CriticReview,
    EvidenceDomain,
    EvidenceRequestDraft,
    Lead,
    Objection,
    ObjectionKind,
    ObjectionSeverity,
    Verdict,
)
from investigator.domain.report import RunStats
from investigator.investigation.assembly import assemble
from investigator.investigation.planning import FollowUpPlanner
from investigator.investigation.policy import (
    CAP_ANALOGY_ONLY,
    CAP_BLOCKED,
    CAP_NO_RUNTIME_EVIDENCE,
    OutcomeDecision,
    decide_outcome,
    rank_hypotheses,
    requests_to_pursue,
    stop_reason,
)
from investigator.markdown import render_markdown
from investigator.runtime.agent_loop import AgentLoop
from investigator.runtime.blackboard import Blackboard, BoardView
from investigator.runtime.budget import Budget, BudgetLimits
from investigator.tools.executor import ToolExecutor
from investigator.tools.registry import build_tools
from investigator.world.dataset import Dataset

from ..scripted import ScriptedGateway
from .conftest import DECOY, POOL_CHANGE, hypothesis

LATE_DEPLOY = RootCause(
    service="orders-service", category=CauseCategory.CODE_REGRESSION, trigger="chg:9999"
)


def decide(view: BoardView) -> OutcomeDecision:
    return decide_outcome(view, min_confidence=0.5, min_margin=0.15)


def review(board: Blackboard, verdicts: dict[str, Verdict], *objections: Objection) -> None:
    board.add_review(CriticReview(round=board.round, verdicts=verdicts, objections=objections))


def test_a_clear_well_supported_leader_is_conclusive(board: Blackboard) -> None:
    board.add_hypotheses([hypothesis(POOL_CHANGE, 0.85), hypothesis(DECOY, 0.2, ("OBS-2",))])

    decision = decide(board.view())

    assert decision.outcome is Outcome.CONCLUSIVE
    assert decision.top is not None
    assert decision.top.hypothesis.root_cause == POOL_CHANGE


def test_weak_close_or_contested_leaders_are_inconclusive(board: Blackboard) -> None:
    board.add_hypotheses([hypothesis(POOL_CHANGE, 0.45), hypothesis(DECOY, 0.4)])
    blocking = Objection(
        hypothesis_id="HYP-1",
        kind=ObjectionKind.ALTERNATIVE_NOT_EXCLUDED,
        severity=ObjectionSeverity.BLOCKING,
        detail="decoy not ruled out",
        source="critic",
    )
    review(board, {"HYP-1": Verdict.CHALLENGE}, blocking)

    reasons = decide(board.view()).reasons

    assert any("below 0.5" in r for r in reasons)
    assert any("too close" in r for r in reasons)
    assert any("blocking objections" in r for r in reasons)


def test_termination_stops_on_acceptance_rounds_budget_and_silence(board: Blackboard) -> None:
    board.add_hypotheses([hypothesis(POOL_CHANGE, 0.9)])
    budget = Budget(BudgetLimits())

    review(board, {"HYP-1": Verdict.ACCEPT})
    assert stop_reason(board.view(), budget, 1, max_rounds=3) == "the critic accepted HYP-1"

    review(board, {"HYP-1": Verdict.CHALLENGE})
    assert stop_reason(board.view(), budget, 1, max_rounds=3) == "no further evidence was requested"
    board.add_requests(
        [EvidenceRequestDraft(question="db?", domain=EvidenceDomain.OBSERVABILITY)], "critic"
    )
    assert stop_reason(board.view(), budget, 1, max_rounds=3) is None

    spent = Budget(BudgetLimits(model_calls=2, reserve_model_calls=2))
    assert stop_reason(board.view(), spent, 1, max_rounds=3) == "model call budget reached"
    board.start_round()
    assert (
        stop_reason(board.view(), budget, 0, max_rounds=3)
        == "the last round produced no new evidence"
    )
    board.start_round()
    assert stop_reason(board.view(), budget, 1, max_rounds=3) == "reached the limit of 3 rounds"


def test_rules_flag_unsupported_and_analogy_only_hypotheses(board: Blackboard) -> None:
    board.add_hypotheses(
        [hypothesis(POOL_CHANGE, 0.5, supporting=()), hypothesis(DECOY, 0.4, supporting=("OBS-3",))]
    )

    changes = {
        "chg:2290": datetime(2026, 10, 20, 10, 2, tzinfo=UTC),
        "chg:2291": datetime(2026, 10, 20, 10, 3, tzinfo=UTC),
    }
    kinds = {(o.hypothesis_id, o.kind) for o in rule_objections(board.view(), changes)}

    assert kinds == {
        ("HYP-1", ObjectionKind.UNSUPPORTED_CLAIM),
        ("HYP-2", ObjectionKind.ANALOGY_ONLY),
    }


def test_leads_only_become_tasks_where_nobody_has_looked() -> None:
    start, end = datetime(2026, 10, 20, 9, tzinfo=UTC), datetime(2026, 10, 20, 10, 30, tzinfo=UTC)
    planner = FollowUpPlanner(["payments-service"], start=start, end=end)
    done = [
        PlannedTask(
            agent=AgentRole.DEPENDENCY,
            focus="changes",
            services=("payments-service", "kafka"),
            start=start,
            end=end,
        )
    ]
    leads = [
        Lead(
            domain=EvidenceDomain.CHANGES,
            question="What changed?",
            service="payments-service",
            id="LEAD-1",
            source="t",
        ),
        Lead(
            domain=EvidenceDomain.OBSERVABILITY,
            question="Is the pool full?",
            service="payments-service",
            id="LEAD-2",
            source="t",
        ),
        Lead(domain=EvidenceDomain.HISTORY, question="Seen before?", id="LEAD-3", source="t"),
    ]

    tasks = planner.from_leads(leads, done, limit=2)

    assert [(t.agent, t.focus, t.start, t.end) for t in tasks] == [
        (AgentRole.OBSERVABILITY, "Is the pool full?", start, end)
    ]


def test_markdown_resolves_citations_and_explains_inconclusive_outcomes(board: Blackboard) -> None:
    board.add_hypotheses([hypothesis(POOL_CHANGE, 0.85), hypothesis(DECOY, 0.2, ("OBS-2",))])
    stats = RunStats(rounds=1, model_calls=9, tool_calls=4, tokens=12000, elapsed_s=42)
    conclusive = assemble(
        board.view(),
        decide(board.view()),
        ReportNarrative(summary="Pool cut."),
        "the critic accepted HYP-1",
        stats,
    )

    weak = Blackboard(board.incident)
    weak.start_round()
    inconclusive = assemble(
        weak.view(),
        decide(weak.view()),
        ReportNarrative(summary="Unknown."),
        "no further evidence was requested",
        stats,
    )

    text = render_markdown(conclusive)
    assert "**Outcome:** conclusive" in text
    assert "`config_change` on **payments-service**, triggered by `chg:2290`" in text
    assert "pool max fell to 5 (`metric:payments-service/db_pool_max_connections`)" in text
    assert "9 model calls, 4 tool calls, 12,000 tokens" in text
    assert "- no hypothesis was established" in render_markdown(inconclusive)


def test_requests_about_rejected_hypotheses_are_not_pursued(board: Blackboard) -> None:
    board.add_hypotheses([hypothesis(POOL_CHANGE, 0.7), hypothesis(DECOY, 0.2, ("OBS-2",))])
    board.add_requests(
        [
            EvidenceRequestDraft(
                question="vendor latency?",
                domain=EvidenceDomain.OBSERVABILITY,
                discriminates=("HYP-2",),
            ),
            EvidenceRequestDraft(
                question="db load?",
                domain=EvidenceDomain.OBSERVABILITY,
                discriminates=("HYP-1", "HYP-2"),
            ),
            EvidenceRequestDraft(
                question="queries per request?", domain=EvidenceDomain.OBSERVABILITY
            ),
        ],
        "reasoning",
    )
    review(board, {"HYP-1": Verdict.CHALLENGE, "HYP-2": Verdict.REJECT})

    kept = [r.question for r in requests_to_pursue(board.view(), board.round)]

    assert kept == ["db load?", "queries per request?"]


def test_confidence_is_capped_by_the_kind_of_evidence_behind_it(board: Blackboard) -> None:
    board.add_hypotheses(
        [
            hypothesis(POOL_CHANGE, 0.8, supporting=("OBS-1", "OBS-2")),
            hypothesis(DECOY, 0.9, supporting=("OBS-2",)),
        ]
    )
    calibrated = {c.hypothesis.id: c for c in rank_hypotheses(board.view())}

    assert calibrated["HYP-1"].confidence == 0.8
    assert calibrated["HYP-1"].cap_reasons == ()
    assert calibrated["HYP-2"].confidence == CAP_NO_RUNTIME_EVIDENCE
    assert calibrated["HYP-2"].cap_reasons == ("no log or metric evidence supports it",)
    assert rank_hypotheses(board.view())[0].hypothesis.id == "HYP-1"


def test_analogies_and_blocking_objections_cap_confidence_further(board: Blackboard) -> None:
    board.add_hypotheses(
        [hypothesis(POOL_CHANGE, 0.9), hypothesis(DECOY, 0.9, supporting=("OBS-3",))]
    )
    blocking = Objection(
        hypothesis_id="HYP-1",
        kind=ObjectionKind.GAP_UNADDRESSED,
        severity=ObjectionSeverity.BLOCKING,
        detail="db metrics missing",
        source="critic",
    )
    review(board, {"HYP-1": Verdict.CHALLENGE}, blocking)
    calibrated = {c.hypothesis.id: c.confidence for c in rank_hypotheses(board.view())}

    assert calibrated == {
        "HYP-1": CAP_BLOCKED,
        "HYP-2": CAP_ANALOGY_ONLY,
    }


def test_rules_check_that_a_trigger_was_observed_and_came_before_the_report(
    board: Blackboard,
) -> None:
    late = RootCause(
        service="payments-service", category=CauseCategory.CODE_REGRESSION, trigger="chg:9999"
    )
    invented = RootCause(
        service="payments-service", category=CauseCategory.CONFIG_CHANGE, trigger="chg:1234"
    )
    board.add_hypotheses(
        [hypothesis(POOL_CHANGE, 0.8), hypothesis(late, 0.5), hypothesis(invented, 0.4)]
    )
    changes = {
        "chg:2290": datetime(2026, 10, 20, 10, 2, tzinfo=UTC),
        "chg:9999": datetime(2026, 10, 20, 10, 30, tzinfo=UTC),
    }

    kinds = {(o.hypothesis_id, o.kind) for o in rule_objections(board.view(), changes)}

    assert kinds == {
        ("HYP-2", ObjectionKind.TEMPORAL_VIOLATION),
        ("HYP-3", ObjectionKind.UNSUPPORTED_CLAIM),
    }


def objection(hypothesis_id: str, kind: ObjectionKind, alternative: str | None = None) -> Objection:
    return Objection(
        hypothesis_id=hypothesis_id,
        kind=kind,
        severity=ObjectionSeverity.BLOCKING,
        detail="d",
        alternative=alternative,
        source="critic",
    )


def test_an_alternative_blocks_only_while_the_review_leaves_it_standing() -> None:
    verdicts = {f"HYP-{n}": Verdict.CHALLENGE for n in (1, 2, 3)} | {"HYP-4": Verdict.REJECT}
    alternative = ObjectionKind.ALTERNATIVE_NOT_EXCLUDED
    objections = [
        objection("HYP-1", alternative, alternative="HYP-2"),
        objection("HYP-2", ObjectionKind.UNSUPPORTED_CLAIM),
        objection("HYP-2", alternative, alternative="HYP-1"),
        objection("HYP-3", alternative, alternative="HYP-4"),
        objection("HYP-3", alternative),
        objection("HYP-1", alternative, alternative="HYP-3"),
    ]

    settled = demote_dismissed_alternatives(objections, verdicts)

    assert [o.severity for o in settled] == [
        ObjectionSeverity.MINOR,
        ObjectionSeverity.BLOCKING,
        ObjectionSeverity.BLOCKING,
        ObjectionSeverity.MINOR,
        ObjectionSeverity.MINOR,
        ObjectionSeverity.BLOCKING,
    ]
    assert "rejected HYP-2 or found it flawed" in settled[0].detail
    assert "names no hypothesis on the board" in settled[4].detail


def test_the_review_lists_verdicts_in_board_order(board: Blackboard, dataset: Dataset) -> None:
    board.add_hypotheses(
        [hypothesis(POOL_CHANGE, 0.5), hypothesis(DECOY, 0.3), hypothesis(LATE_DEPLOY, 0.2)]
    )
    tools = build_tools(dataset.telemetry("D2"), dataset.topology, dataset.history())
    loop = AgentLoop(ScriptedGateway([]), ToolExecutor(tools), Budget(BudgetLimits()))

    review = CriticAgent(loop).review(board, None, [])

    assert list(review.verdicts) == ["HYP-1", "HYP-2", "HYP-3"]
