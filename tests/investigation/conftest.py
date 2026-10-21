import re
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from investigator.domain.causes import CauseCategory, RootCause
from investigator.domain.incident import IncidentReport, Severity
from investigator.domain.investigation import HypothesisDraft, ObservationDraft
from investigator.domain.tools import ToolStatus
from investigator.llm.messages import ChatRequest, ChatResponse
from investigator.runtime.blackboard import Blackboard
from investigator.tools.results import ToolResult

Step = ChatResponse | Callable[[ChatRequest], ChatResponse]


class RoleScript:
    """Replies per agent role, in order, so concurrent agents each follow their own script."""

    def __init__(self, steps: dict[str, list[Step]]) -> None:
        self.steps = {role: list(queue) for role, queue in steps.items()}

    def __call__(self, request: ChatRequest) -> ChatResponse:
        queue = self.steps.get(request.purpose)
        if not queue:
            raise AssertionError(f"no scripted reply left for {request.purpose}")
        step = queue.pop(0)
        return step(request) if callable(step) else step

    def leftover(self) -> dict[str, int]:
        return {role: len(queue) for role, queue in self.steps.items() if queue}


def observation_id(request: ChatRequest, fragment: str) -> str:
    """The id the board gave an observation, found in the agent's brief by its wording."""
    brief = request.messages[1].content
    match = re.search(rf"^(OBS-\d+) .*{re.escape(fragment)}", brief, re.MULTILINE)
    if match is None:
        raise AssertionError(f"no observation mentioning {fragment!r} in the brief")
    return match.group(1)


def at(clock: str) -> str:
    return f"2026-10-20T{clock}:00Z"


POOL_CHANGE = RootCause(
    service="payments-service", category=CauseCategory.CONFIG_CHANGE, trigger="chg:2290"
)
DECOY = RootCause(
    service="notification-service", category=CauseCategory.CODE_REGRESSION, trigger="chg:2291"
)


@pytest.fixture
def board() -> Blackboard:
    """A board with three observations already backed by tool results."""
    board = Blackboard(
        IncidentReport(
            id="T",
            title="Checkout failing",
            severity=Severity.SEV2,
            reported_at=datetime(2026, 10, 20, 10, 9, tzinfo=UTC),
            reported_by="on-call",
            summary="Checkout failing",
            symptoms=("5xx on checkout",),
            reported_services=("payments-service",),
        )
    )
    board.record_tool_results(
        [
            ToolResult(
                call_id="call-0001",
                tool="query_metrics",
                arguments={},
                status=ToolStatus.OK,
                artifacts=(
                    "metric:payments-service/db_pool_max_connections",
                    "chg:2290",
                    "pir:2025-007",
                ),
                attempts=1,
                duration_ms=1,
            )
        ]
    )
    board.start_round()
    board.add_findings(
        "seed",
        observations=[
            ObservationDraft(
                statement="pool max fell to 5",
                artifacts=("metric:payments-service/db_pool_max_connections",),
            ),
            ObservationDraft(statement="pool cut by chg:2290", artifacts=("chg:2290",)),
            ObservationDraft(statement="a past incident looked alike", artifacts=("pir:2025-007",)),
        ],
    )
    return board


def hypothesis(
    cause: RootCause, confidence: float, supporting: tuple[str, ...] = ("OBS-1", "OBS-2")
) -> HypothesisDraft:
    return HypothesisDraft(
        root_cause=cause, mechanism="m", supporting=supporting, confidence=confidence
    )
