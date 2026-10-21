from datetime import UTC, datetime

from investigator.domain.telemetry import LogLevel
from investigator.world.generator import TelemetryGenerator
from investigator.world.logs import ACCESS_LOG_TEMPLATE
from investigator.world.topology import Topology

from .conftest import ScenarioFactory


def at(minute: int, second: int = 0) -> datetime:
    return datetime(2026, 10, 20, 10, minute, second, tzinfo=UTC)


def cpu_effect(**overrides: object) -> dict[str, object]:
    return {
        "kind": "metric",
        "service": "db",
        "metric": "cpu_util",
        "start": "2026-10-20T10:10:00Z",
        **overrides,
    }


def test_same_scenario_renders_identical_telemetry(
    topology: Topology, make_scenario: ScenarioFactory
) -> None:
    generator = TelemetryGenerator(topology)
    scenario = make_scenario(cpu_effect(to=0.9))
    assert generator.render(scenario).fingerprint() == generator.render(scenario).fingerprint()


def test_seed_changes_the_sampled_logs(topology: Topology, make_scenario: ScenarioFactory) -> None:
    generator = TelemetryGenerator(topology)
    first = generator.render(make_scenario(seed=1))
    second = generator.render(make_scenario(seed=2))
    assert first.fingerprint() != second.fingerprint()


def test_step_effect_holds_its_target_only_inside_its_window(
    topology: Topology, make_scenario: ScenarioFactory
) -> None:
    store = TelemetryGenerator(topology).render(
        make_scenario(cpu_effect(to=0.9, noise=0, end="2026-10-20T10:20:00Z"))
    )
    values = store.metrics["metric:db/cpu_util"].values
    assert values[9] == 0.5
    assert set(values[10:20]) == {0.9}
    assert values[20] == 0.5


def test_ramp_effect_reaches_its_target_after_the_ramp(
    topology: Topology, make_scenario: ScenarioFactory
) -> None:
    store = TelemetryGenerator(topology).render(
        make_scenario(cpu_effect(to=0.9, noise=0, shape="ramp", ramp_minutes=4))
    )
    values = store.metrics["metric:db/cpu_util"].values
    assert values[10:15] == (0.6, 0.7, 0.8, 0.9, 0.9)


def test_factor_scales_normal_values_and_ceiling_caps_them(
    topology: Topology, make_scenario: ScenarioFactory
) -> None:
    scaled = TelemetryGenerator(topology).render(make_scenario(cpu_effect(factor=1.5)))
    capped = TelemetryGenerator(topology).render(make_scenario(cpu_effect(to=1.7, noise=0)))
    assert scaled.metrics["metric:db/cpu_util"].values[30] == 0.75
    assert capped.metrics["metric:db/cpu_util"].values[30] == 1.0


def test_access_logs_fail_when_the_error_rate_says_so(
    topology: Topology, make_scenario: ScenarioFactory
) -> None:
    store = TelemetryGenerator(topology).render(
        make_scenario(
            {
                "kind": "metric",
                "service": "api",
                "metric": "error_rate",
                "start": "2026-10-20T10:20:00Z",
                "end": "2026-10-20T10:30:00Z",
                "to": 1.0,
                "noise": 0,
            }
        )
    )
    access = [r for r in store.logs if r.template == ACCESS_LOG_TEMPLATE]
    inside = [r for r in access if at(20) <= r.ts < at(30)]
    outside = [r for r in access if not at(20) <= r.ts < at(30)]
    assert inside
    assert outside
    assert all(r.level is LogLevel.ERROR and int(r.attrs["status"]) >= 500 for r in inside)
    assert all(r.level is LogLevel.INFO and int(r.attrs["status"]) < 300 for r in outside)


def test_counted_log_effect_emits_exactly_that_many_lines_in_its_span(
    topology: Topology, make_scenario: ScenarioFactory
) -> None:
    store = TelemetryGenerator(topology).render(
        make_scenario(
            {
                "kind": "log",
                "service": "api",
                "level": "INFO",
                "template": "api {version} started",
                "start": "2026-10-20T10:05:00Z",
                "end": "2026-10-20T10:05:30Z",
                "count": 4,
                "fields": {"version": "1.2.0"},
            }
        )
    )
    started = [r for r in store.logs if r.message == "api 1.2.0 started"]
    assert len(started) == 4
    assert all(at(5) <= r.ts <= at(5, 30) for r in started)
    assert len({r.pod for r in started}) == 4


def test_zoned_log_effect_only_uses_pods_in_that_zone(
    topology: Topology, make_scenario: ScenarioFactory
) -> None:
    store = TelemetryGenerator(topology).render(
        make_scenario(
            {
                "kind": "log",
                "service": "api",
                "level": "ERROR",
                "template": "connection reset by peer",
                "start": "2026-10-20T10:30:30Z",
                "end": "2026-10-20T10:40:00Z",
                "rate_per_min": 20,
                "az": "az-b",
            }
        )
    )
    resets = [r for r in store.logs if r.template == "connection reset by peer"]
    assert resets
    assert {r.az for r in resets} == {"az-b"}
    assert all(at(30, 30) <= r.ts < at(40) for r in resets)


def test_logs_are_time_ordered_with_unique_ids(
    topology: Topology, make_scenario: ScenarioFactory
) -> None:
    store = TelemetryGenerator(topology).render(make_scenario())
    timestamps = [r.ts for r in store.logs]
    assert timestamps == sorted(timestamps)
    assert len({r.id for r in store.logs}) == len(store.logs)
