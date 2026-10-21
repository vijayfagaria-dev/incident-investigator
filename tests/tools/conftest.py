from collections.abc import Callable
from typing import Any

import pytest

from investigator.tools.executor import ToolExecutor
from investigator.tools.registry import ToolRegistry, build_tools
from investigator.tracing import MemoryTracer
from investigator.world.dataset import Dataset
from investigator.world.scenario import ToolFault
from investigator.world.store import TelemetryStore

ToolsFactory = Callable[..., ToolRegistry]


def at(clock: str) -> str:
    """A timestamp on the day of incident D2, e.g. ``at("10:04")``."""
    return f"2026-10-20T{clock}:00Z"


def fault(**fields: Any) -> ToolFault:
    return ToolFault.model_validate(fields)


class RecordingSleep:
    """Stands in for ``asyncio.sleep`` so retry backoff is recorded instead of waited for."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


@pytest.fixture(scope="session")
def d2(dataset: Dataset) -> TelemetryStore:
    return dataset.telemetry("D2")


@pytest.fixture
def tools(dataset: Dataset, d2: TelemetryStore) -> ToolsFactory:
    def make(*faults: ToolFault) -> ToolRegistry:
        return build_tools(d2, dataset.topology, dataset.history(), faults)

    return make


@pytest.fixture
def sleep() -> RecordingSleep:
    return RecordingSleep()


@pytest.fixture
def tracer() -> MemoryTracer:
    return MemoryTracer()


@pytest.fixture
def executor(tools: ToolsFactory, tracer: MemoryTracer, sleep: RecordingSleep) -> ToolExecutor:
    return ToolExecutor(tools(), tracer=tracer, timeout_s=0.05, sleep=sleep)
