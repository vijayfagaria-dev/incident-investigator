import math

from investigator.domain.tools import ErrorKind
from investigator.tools.executor import ToolExecutor
from investigator.tools.metrics import MAX_POINTS

from .conftest import at


async def test_metric_catalog_lists_what_a_service_reports(executor: ToolExecutor) -> None:
    result = await executor.execute("query_metrics", {"service": "payments-service"})

    assert result.output is not None
    names = {metric["name"] for metric in result.output["available"]}
    assert {"error_rate", "db_pool_in_use", "db_pool_max_connections"} <= names


async def test_a_range_without_a_metric_summarises_every_metric(executor: ToolExecutor) -> None:
    result = await executor.execute(
        "query_metrics", {"service": "payments-service", "start": at("10:05"), "end": at("10:35")}
    )

    assert result.output is not None
    summaries = {m["name"]: m["summary"] for m in result.output["available"]}
    assert summaries["db_pool_max_connections"]["mean"] == 5
    assert summaries["db_pool_max_connections"]["baseline_mean"] > 45
    assert "metric:payments-service/db_pool_max_connections" in result.artifacts
    assert len(result.artifacts) == len(summaries)


async def test_metric_summary_compares_against_the_hour_before(executor: ToolExecutor) -> None:
    result = await executor.execute(
        "query_metrics",
        {
            "service": "payments-service",
            "metric": "db_pool_max_connections",
            "start": at("10:05"),
            "end": at("10:35"),
        },
    )

    assert result.output is not None
    summary = result.output["summary"]
    assert summary["baseline_mean"] > 45
    assert summary["max"] == 5
    assert result.artifacts == ("metric:payments-service/db_pool_max_connections",)


async def test_long_ranges_are_downsampled_with_a_warning(executor: ToolExecutor) -> None:
    result = await executor.execute(
        "query_metrics",
        {"service": "edge-gateway", "metric": "rps", "start": at("08:00"), "end": at("11:00")},
    )

    assert result.output is not None
    step = math.ceil(180 / MAX_POINTS)
    assert result.output["step_minutes"] == step
    assert len(result.output["points"]) <= MAX_POINTS
    assert any(f"step raised to {step} minutes" in warning for warning in result.warnings)


async def test_unknown_metric_and_missing_range_are_invalid(executor: ToolExecutor) -> None:
    unknown = await executor.execute(
        "query_metrics",
        {
            "service": "payments-service",
            "metric": "disk_iops",
            "start": at("10:00"),
            "end": at("10:30"),
        },
    )
    no_range = await executor.execute(
        "query_metrics", {"service": "payments-service", "metric": "rps"}
    )

    assert unknown.error is not None
    assert "available:" in unknown.error.message
    assert no_range.error is not None
    assert no_range.error.kind is ErrorKind.INVALID_QUERY
    assert no_range.attempts == 0


async def test_change_history_filters_and_orders_changes(executor: ToolExecutor) -> None:
    everything = await executor.execute(
        "get_change_history", {"start": at("08:00"), "end": at("11:00")}
    )
    configs = await executor.execute(
        "get_change_history",
        {
            "start": at("08:00"),
            "end": at("11:00"),
            "services": ["payments-service"],
            "kinds": ["config"],
        },
    )

    assert everything.output is not None
    assert configs.output is not None
    timestamps = [change["ts"] for change in everything.output["changes"]]
    assert timestamps == sorted(timestamps)
    assert len(timestamps) == 4
    assert configs.artifacts == ("chg:2290",)


async def test_dependencies_follow_the_call_graph_in_both_directions(
    executor: ToolExecutor,
) -> None:
    downstream = await executor.execute(
        "get_service_dependencies", {"service": "payments-service", "direction": "downstream"}
    )
    upstream = await executor.execute(
        "get_service_dependencies",
        {"service": "postgres-orders", "direction": "upstream", "depth": 2},
    )

    assert downstream.output is not None
    assert upstream.output is not None
    assert {d["target"] for d in downstream.output["dependencies"]} == {
        "postgres-payments",
        "bank-rails",
        "kafka",
    }
    assert {s["name"] for s in upstream.output["services"]} == {
        "postgres-orders",
        "orders-service",
        "portfolio-service",
        "edge-gateway",
    }
    assert "dep:payments-service->postgres-payments" in downstream.artifacts
