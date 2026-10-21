"""Partial faults: backends that answer, but without some of their data."""

from investigator.domain.tools import ToolStatus
from investigator.tools.executor import ToolExecutor

from .conftest import ToolsFactory, at, fault


async def test_zone_outage_drops_that_zone_and_marks_the_result_partial(
    tools: ToolsFactory,
) -> None:
    executor = ToolExecutor(tools(fault(tool="query_logs", kind="partial", missing_az="az-b")))
    result = await executor.execute(
        "query_logs",
        {
            "service": "payments-service",
            "start": at("10:00"),
            "end": at("10:30"),
            "mode": "records",
            "limit": 100,
        },
    )

    assert result.status is ToolStatus.PARTIAL
    assert result.output is not None
    assert {r["az"] for r in result.output["records"]} <= {"az-a", "az-c"}
    assert any("az-b is unavailable" in notice for notice in result.notices)


async def test_expired_logs_only_affect_queries_reaching_before_the_cutoff(
    tools: ToolsFactory,
) -> None:
    executor = ToolExecutor(
        tools(fault(tool="query_logs", kind="partial", missing_before=at("10:00")))
    )
    query = {"service": "payments-service", "mode": "records", "limit": 100}
    spanning = await executor.execute(
        "query_logs", {**query, "start": at("09:50"), "end": at("10:10")}
    )
    recent = await executor.execute(
        "query_logs", {**query, "start": at("10:00"), "end": at("10:10")}
    )

    assert spanning.status is ToolStatus.PARTIAL
    assert spanning.output is not None
    assert all(r["ts"] >= at("10:00") for r in spanning.output["records"])
    assert recent.status is ToolStatus.OK


async def test_metric_outage_returns_no_points_for_that_service(tools: ToolsFactory) -> None:
    executor = ToolExecutor(
        tools(fault(tool="query_metrics", kind="partial", missing_services=["payments-service"]))
    )
    result = await executor.execute(
        "query_metrics",
        {
            "service": "payments-service",
            "metric": "error_rate",
            "start": at("10:00"),
            "end": at("10:30"),
        },
    )

    assert result.status is ToolStatus.PARTIAL
    assert result.output is not None
    assert result.output["points"] == []
    assert result.artifacts == ()
