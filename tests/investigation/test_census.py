from datetime import UTC, datetime

from investigator.investigation.census import take_change_census
from investigator.runtime.blackboard import Blackboard
from investigator.tools.executor import ToolExecutor
from investigator.tools.registry import build_tools
from investigator.world.dataset import Dataset
from investigator.world.scenario import ToolFault

PLAN_START = datetime(2026, 10, 20, 9, 45, tzinfo=UTC)
PLAN_END = datetime(2026, 10, 20, 10, 9, tzinfo=UTC)


async def census_board(dataset: Dataset, *faults: ToolFault) -> Blackboard:
    tools = build_tools(dataset.telemetry("D2"), dataset.topology, dataset.history(), faults)
    board = Blackboard(dataset.incident_report("D2"))
    await take_change_census(ToolExecutor(tools), board, PLAN_START, PLAN_END)
    return board


async def test_every_change_in_the_window_becomes_a_citable_observation(dataset: Dataset) -> None:
    observations = (await census_board(dataset)).view().observations

    cited = {artifact for o in observations for artifact in o.artifacts}
    assert cited == {"chg:2284", "chg:2290", "chg:2291"}
    pool = next(o for o in observations if o.artifacts == ("chg:2290",))
    assert "db.pool.max_size: 50 -> 5" in pool.statement
    assert pool.source == "change-census"


async def test_a_change_feed_outage_leaves_a_gap_instead_of_failing(dataset: Dataset) -> None:
    outage = ToolFault.model_validate({"tool": "get_change_history", "kind": "unavailable"})

    view = (await census_board(dataset, outage)).view()

    assert view.observations == ()
    assert [g.tool for g in view.gaps] == ["get_change_history"]
