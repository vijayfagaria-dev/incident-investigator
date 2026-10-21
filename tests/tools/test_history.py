from investigator.tools.executor import ToolExecutor


async def test_symptom_search_finds_the_closest_past_incident(executor: ToolExecutor) -> None:
    result = await executor.execute(
        "search_incident_history",
        {"query": "checkout failing, Connection is not available, payments latency"},
    )

    assert result.output is not None
    assert result.output["matches"][0]["id"] == "pir:2025-007"
    assert result.artifacts[0] == "pir:2025-007"


async def test_service_filter_boosts_incidents_on_those_services(executor: ToolExecutor) -> None:
    plain = await executor.execute(
        "search_incident_history", {"query": "latency timeouts", "limit": 10}
    )
    boosted = await executor.execute(
        "search_incident_history",
        {"query": "latency timeouts", "services": ["market-data-service"], "limit": 10},
    )

    assert plain.output is not None
    assert boosted.output is not None
    rank = [m["id"] for m in boosted.output["matches"]].index("pir:2025-024")
    assert rank < [m["id"] for m in plain.output["matches"]].index("pir:2025-024") or rank == 0


async def test_unrelated_queries_return_no_matches(executor: ToolExecutor) -> None:
    result = await executor.execute("search_incident_history", {"query": "quantum flux capacitor"})

    assert result.output == {"matches": []}
