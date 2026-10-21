from datetime import UTC, datetime

import pytest

from investigator.domain.causes import CauseCategory, RootCause
from investigator.domain.incident import IncidentReport, Severity
from investigator.domain.investigation import HypothesisDraft, ObservationDraft
from investigator.domain.tools import ErrorKind, ToolStatus
from investigator.runtime.blackboard import Blackboard
from investigator.tools.results import ToolError, ToolResult

POOL = RootCause(
    service="payments-service", category=CauseCategory.CONFIG_CHANGE, trigger="chg:2290"
)


def result(call_id: str, *artifacts: str, status: ToolStatus = ToolStatus.OK) -> ToolResult:
    error = (
        ToolError(kind=ErrorKind.UNAVAILABLE, message="down", retryable=True)
        if status is ToolStatus.ERROR
        else None
    )
    return ToolResult(
        call_id=call_id,
        tool="query_logs",
        arguments={},
        status=status,
        artifacts=artifacts,
        error=error,
        attempts=1,
        duration_ms=1,
    )


@pytest.fixture
def board() -> Blackboard:
    incident = IncidentReport(
        id="T",
        title="checkout failing",
        severity=Severity.SEV2,
        reported_at=datetime(2026, 10, 20, 10, 9, tzinfo=UTC),
        reported_by="on-call",
        summary="checkout failing",
        symptoms=("5xx",),
    )
    board = Blackboard(incident)
    board.record_tool_results(
        [
            result("call-0001", "log:aa", "chg:2290"),
            result("call-0002", "log:zz", status=ToolStatus.ERROR),
        ]
    )
    return board


def test_observations_may_only_cite_artifacts_a_tool_returned(board: Blackboard) -> None:
    commit = board.add_findings(
        "observability",
        observations=[
            ObservationDraft(statement="pool exhausted", artifacts=("log:aa", "log:made-up")),
            ObservationDraft(statement="invented", artifacts=("log:made-up",)),
            ObservationDraft(statement="from a failed call", artifacts=("log:zz",)),
        ],
    )

    [observation] = board.view().observations
    assert commit.accepted == ("OBS-1",)
    assert observation.artifacts == ("log:aa",)
    assert observation.source == "observability"
    assert len(commit.problems) == 3


def test_hypotheses_cite_known_observations_and_are_versioned(board: Blackboard) -> None:
    board.add_findings(
        "changes",
        observations=[ObservationDraft(statement="pool cut to 5", artifacts=("chg:2290",))],
    )
    board.start_round()
    first = board.add_hypotheses(
        [
            HypothesisDraft(
                root_cause=POOL,
                mechanism="pool too small",
                supporting=("OBS-1", "OBS-9"),
                confidence=0.6,
            )
        ]
    )
    board.start_round()
    second = board.add_hypotheses(
        [
            HypothesisDraft(
                id="HYP-1",
                root_cause=POOL,
                mechanism="pool too small",
                supporting=("OBS-1",),
                confidence=0.85,
            )
        ]
    )

    [current] = board.view().hypotheses
    assert first.accepted == second.accepted == ("HYP-1",)
    assert "OBS-9" in first.problems[0]
    assert (current.version, current.round, current.confidence) == (2, 2, 0.85)


def test_revising_an_unknown_hypothesis_adds_it_as_new(board: Blackboard) -> None:
    commit = board.add_hypotheses(
        [HypothesisDraft(id="HYP-7", root_cause=POOL, mechanism="m", confidence=0.4)]
    )

    assert commit.accepted == ("HYP-1",)
    assert "no hypothesis HYP-7" in commit.problems[0]


def test_a_second_hypothesis_with_the_same_root_cause_is_a_revision(board: Blackboard) -> None:
    board.add_findings(
        "changes", observations=[ObservationDraft(statement="pool cut", artifacts=("chg:2290",))]
    )
    board.add_hypotheses(
        [HypothesisDraft(root_cause=POOL, mechanism="first", supporting=("OBS-1",), confidence=0.5)]
    )

    commit = board.add_hypotheses(
        [
            HypothesisDraft(
                root_cause=POOL, mechanism="restated", supporting=("OBS-1",), confidence=0.7
            )
        ]
    )

    [current] = board.view().hypotheses
    assert commit.accepted == ("HYP-1",)
    assert "merged into HYP-1" in commit.problems[0]
    assert (current.version, current.mechanism) == (2, "restated")


def test_two_drafts_of_one_cause_in_a_commit_keep_the_more_confident(board: Blackboard) -> None:
    board.add_hypotheses([HypothesisDraft(root_cause=POOL, mechanism="first", confidence=0.4)])

    commit = board.add_hypotheses(
        [
            HypothesisDraft(id="HYP-1", root_cause=POOL, mechanism="likely", confidence=0.6),
            HypothesisDraft(id="HYP-3", root_cause=POOL, mechanism="variant", confidence=0.2),
        ]
    )

    [current] = board.view().hypotheses
    assert commit.accepted == ("HYP-1",)
    assert (current.version, current.mechanism) == (2, "likely")
    assert any("more confident of two drafts" in p for p in commit.problems)


def test_a_more_confident_later_draft_replaces_the_earlier_one(board: Blackboard) -> None:
    commit = board.add_hypotheses(
        [
            HypothesisDraft(root_cause=POOL, mechanism="variant", confidence=0.2),
            HypothesisDraft(root_cause=POOL, mechanism="likely", confidence=0.6),
        ]
    )

    [current] = board.view().hypotheses
    assert commit.accepted == ("HYP-1",)
    assert (current.version, current.mechanism) == (1, "likely")
