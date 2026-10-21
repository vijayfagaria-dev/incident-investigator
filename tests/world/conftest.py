from collections.abc import Callable
from typing import Any

import pytest

from investigator.world.scenario import Scenario
from investigator.world.topology import Topology

WINDOW = {"start": "2026-10-20T10:00:00Z", "end": "2026-10-20T11:00:00Z"}

ScenarioFactory = Callable[..., Scenario]


@pytest.fixture
def topology() -> Topology:
    """Two nodes with noise-free metrics, so effects produce exact values."""
    return Topology.model_validate(
        {
            "availability_zones": ["az-a", "az-b"],
            "traffic": {"diurnal_amplitude": 0.0, "peak_hour_utc": 12},
            "metric_profiles": {
                "web": {
                    "error_rate": {"unit": "ratio", "baseline": 0.0, "noise": 0, "ceiling": 1},
                    "latency_p50_ms": {"unit": "ms", "baseline": 40, "noise": 0},
                    "latency_p99_ms": {"unit": "ms", "baseline": 200, "noise": 0},
                }
            },
            "nodes": [
                {
                    "name": "api",
                    "kind": "service",
                    "pods": 4,
                    "profile": "web",
                    "routes": ["GET /items"],
                },
                {
                    "name": "db",
                    "kind": "datastore",
                    "pods": 1,
                    "metrics": {
                        "cpu_util": {"unit": "ratio", "baseline": 0.5, "noise": 0, "ceiling": 1}
                    },
                },
            ],
            "edges": [{"source": "api", "target": "db", "protocol": "sql", "criticality": "hard"}],
        }
    )


@pytest.fixture
def make_scenario() -> ScenarioFactory:
    def make(
        *effects: dict[str, Any], seed: int = 7, changes: tuple[dict[str, Any], ...] = ()
    ) -> Scenario:
        return Scenario.model_validate(
            {"seed": seed, "window": WINDOW, "changes": list(changes), "effects": list(effects)}
        )

    return make
