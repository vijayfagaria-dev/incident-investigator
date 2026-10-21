"""The tools an investigation can use, and how to build them for one incident."""

from collections.abc import Collection, Iterable, Sequence

from investigator.domain.telemetry import PastIncident
from investigator.domain.tools import ToolName
from investigator.llm.messages import ToolDefinition
from investigator.tools.base import Tool
from investigator.tools.changes import ChangeHistoryTool
from investigator.tools.dependencies import ServiceDependenciesTool
from investigator.tools.faults import FaultInjectingTool
from investigator.tools.history import IncidentHistoryTool, KeywordHistoryIndex
from investigator.tools.logs import QueryLogsTool
from investigator.tools.metrics import QueryMetricsTool
from investigator.tools.missing_data import with_missing_logs, with_missing_metrics
from investigator.tools.sources import (
    ServiceCatalog,
    StoreChangeSource,
    StoreLogSource,
    StoreMetricSource,
)
from investigator.world.dataset import Dataset
from investigator.world.scenario import ToolFault
from investigator.world.store import TelemetryStore
from investigator.world.topology import Topology


class ToolRegistry:
    """The tools available to a caller, looked up by name."""

    def __init__(self, tools: Iterable[Tool]) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"duplicate tool {tool.name}")
            self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def definitions(self, names: Collection[ToolName]) -> list[ToolDefinition]:
        """How the named tools are presented to a model, in registry order."""
        return [
            ToolDefinition(
                name=tool.name,
                description=tool.description,
                parameters=tool.args_model.model_json_schema(),
            )
            for tool in self._tools.values()
            if tool.name in names
        ]


def build_tools(
    telemetry: TelemetryStore,
    topology: Topology,
    history: Sequence[PastIncident],
    faults: Sequence[ToolFault] = (),
) -> ToolRegistry:
    catalog = ServiceCatalog(topology)
    tools: list[Tool] = [
        QueryLogsTool(with_missing_logs(StoreLogSource(telemetry), faults), catalog),
        QueryMetricsTool(with_missing_metrics(StoreMetricSource(telemetry), faults), catalog),
        ChangeHistoryTool(StoreChangeSource(telemetry), catalog),
        ServiceDependenciesTool(catalog),
        IncidentHistoryTool(KeywordHistoryIndex(history)),
    ]
    return ToolRegistry(FaultInjectingTool(tool, faults) for tool in tools)


def incident_tools(dataset: Dataset, incident_id: str) -> ToolRegistry:
    """The tools for one incident, failing the way its scenario says."""
    return build_tools(
        dataset.telemetry(incident_id),
        dataset.topology,
        dataset.history(),
        dataset.tool_faults(incident_id),
    )
