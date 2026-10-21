from investigator.domain.tools import ErrorKind, ToolStatus
from investigator.tools.executor import ToolExecutor

from .conftest import at

PAYMENTS_ONSET = {"service": "payments-service", "start": at("09:55"), "end": at("10:20")}


async def test_patterns_group_similar_lines_with_citable_examples(executor: ToolExecutor) -> None:
    result = await executor.execute("query_logs", {**PAYMENTS_ONSET, "min_level": "ERROR"})

    assert result.status is ToolStatus.OK
    assert result.output is not None
    top = result.output["patterns"][0]
    assert top["pattern"].startswith("HikariPool-1 - Connection is not available")
    assert "<ms>" in top["pattern"]
    assert top["first_seen"] >= at("10:04")
    assert top["example_id"] in result.artifacts


async def test_filters_narrow_by_level_text_and_zone(executor: ToolExecutor) -> None:
    result = await executor.execute(
        "query_logs",
        {
            **PAYMENTS_ONSET,
            "min_level": "WARN",
            "contains": "HIKARIPOOL",
            "az": "az-b",
            "mode": "records",
        },
    )

    assert result.output is not None
    records = result.output["records"]
    assert records
    assert all(r["level"] == "ERROR" and r["az"] == "az-b" for r in records)
    assert all("HikariPool" in r["message"] for r in records)


async def test_records_page_through_every_match_once(executor: ToolExecutor) -> None:
    query = {**PAYMENTS_ONSET, "min_level": "ERROR", "mode": "records", "limit": 100}
    seen: list[str] = []
    cursor = None
    while True:
        result = await executor.execute("query_logs", {**query, "cursor": cursor})
        assert result.output is not None
        seen += [r["id"] for r in result.output["records"]]
        cursor = result.output["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == len(set(seen)) == result.output["matched"]


async def test_unknown_service_is_an_invalid_query_naming_the_known_ones(
    executor: ToolExecutor,
) -> None:
    result = await executor.execute("query_logs", {**PAYMENTS_ONSET, "service": "payment-service"})

    assert result.error is not None
    assert result.error.kind is ErrorKind.INVALID_QUERY
    assert "known services:" in result.error.message
    assert "payments-service" in result.error.message
    assert result.attempts == 1


async def test_contradictory_arguments_are_rejected(executor: ToolExecutor) -> None:
    backwards = await executor.execute(
        "query_logs", {**PAYMENTS_ONSET, "start": at("10:20"), "end": at("10:00")}
    )
    cursor_without_records = await executor.execute(
        "query_logs", {**PAYMENTS_ONSET, "cursor": "offset:20"}
    )

    assert backwards.error is not None
    assert "end must be after start" in backwards.error.message
    assert cursor_without_records.error is not None
    assert "cursor only applies" in cursor_without_records.error.message


async def test_ranges_outside_the_recorded_window_say_so(executor: ToolExecutor) -> None:
    result = await executor.execute(
        "query_logs", {"service": "payments-service", "start": at("06:00"), "end": at("07:00")}
    )

    assert result.status is ToolStatus.OK
    assert result.output is not None
    assert result.output["matched"] == 0
    assert any("only recorded from" in warning for warning in result.warnings)
