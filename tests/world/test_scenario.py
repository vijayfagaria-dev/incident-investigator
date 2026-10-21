import pytest
from pydantic import ValidationError

from investigator.world.scenario import Scenario, Shape
from investigator.world.topology import Topology

from .conftest import ScenarioFactory


def test_ramp_progress_grows_linearly_then_holds() -> None:
    assert [Shape.RAMP.progress(m, 4) for m in (1, 2, 4, 9)] == [0.25, 0.5, 1.0, 1.0]
    assert Shape.STEP.progress(1, 4) == 1.0


def test_metric_effect_needs_exactly_one_target(make_scenario: ScenarioFactory) -> None:
    effect = {
        "kind": "metric",
        "service": "db",
        "metric": "cpu_util",
        "start": "2026-10-20T10:10:00Z",
    }
    with pytest.raises(ValidationError, match="exactly one of 'to' or 'factor'"):
        make_scenario(effect)
    with pytest.raises(ValidationError, match="exactly one of 'to' or 'factor'"):
        make_scenario({**effect, "to": 0.9, "factor": 2})


def test_log_effect_needs_exactly_one_volume(make_scenario: ScenarioFactory) -> None:
    effect = {
        "kind": "log",
        "service": "api",
        "level": "WARN",
        "template": "x",
        "start": "2026-10-20T10:10:00Z",
    }
    with pytest.raises(ValidationError, match="exactly one of 'rate_per_min' or 'count'"):
        make_scenario(effect)


@pytest.mark.parametrize(
    ("effect", "message"),
    [
        (
            {
                "kind": "metric",
                "service": "cache",
                "metric": "cpu_util",
                "start": "2026-10-20T10:10:00Z",
                "to": 1,
            },
            "unknown service 'cache'",
        ),
        (
            {
                "kind": "metric",
                "service": "db",
                "metric": "disk_util",
                "start": "2026-10-20T10:10:00Z",
                "to": 1,
            },
            "db has no metric 'disk_util'",
        ),
        (
            {
                "kind": "metric",
                "service": "db",
                "metric": "cpu_util",
                "start": "2026-10-20T12:00:00Z",
                "to": 1,
            },
            "starts outside the scenario window",
        ),
        (
            {
                "kind": "log",
                "service": "api",
                "level": "WARN",
                "template": "x",
                "start": "2026-10-20T10:10:00Z",
                "count": 1,
                "az": "az-z",
            },
            "unknown zone 'az-z'",
        ),
    ],
)
def test_check_against_rejects_references_the_topology_lacks(
    topology: Topology, make_scenario: ScenarioFactory, effect: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        make_scenario(effect).check_against(topology)


def test_topology_rejects_edges_to_unknown_nodes(topology: Topology) -> None:
    data = topology.model_dump()
    data["edges"] = [
        *data["edges"],
        {"source": "api", "target": "ghost", "protocol": "http", "criticality": "soft"},
    ]
    with pytest.raises(ValidationError, match="dep:api->ghost references an unknown node"):
        Topology.model_validate(data)


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ({"tool": "query_logs", "kind": "partial"}, "must say what is missing"),
        ({"tool": "query_logs", "kind": "timeout", "missing_az": "az-b"}, "only partial faults"),
        (
            {"tool": "query_metrics", "kind": "partial", "missing_az": "az-b"},
            "cannot be missing",
        ),
        (
            {"tool": "query_logs", "kind": "partial", "missing_az": "az-b", "invocations": [1]},
            "apply to every invocation",
        ),
    ],
)
def test_tool_faults_must_be_coherent(
    make_scenario: ScenarioFactory, fault: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Scenario.model_validate({**make_scenario().model_dump(), "faults": [fault]})


def test_check_against_rejects_faults_in_unknown_zones(
    topology: Topology, make_scenario: ScenarioFactory
) -> None:
    scenario = Scenario.model_validate(
        {
            **make_scenario().model_dump(),
            "faults": [{"tool": "query_logs", "kind": "partial", "missing_az": "az-z"}],
        }
    )
    with pytest.raises(ValueError, match="unknown zone 'az-z'"):
        scenario.check_against(topology)
