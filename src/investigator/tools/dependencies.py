from typing import Literal

from pydantic import Field

from investigator.domain.base import DomainModel
from investigator.domain.telemetry import CallProtocol, Criticality, DependencyEdge
from investigator.domain.tools import ToolName
from investigator.tools.base import ToolArgs, ToolOutput
from investigator.tools.sources import ServiceCatalog, ServiceInfo
from investigator.tools.validation import require_services


class DependencyQuery(ToolArgs):
    service: str = Field(description="Service to start from.")
    direction: Literal["downstream", "upstream", "both"] = Field(
        default="both",
        description="'downstream': what it calls; 'upstream': what calls it.",
    )
    depth: int = Field(default=1, ge=1, le=3, description="How many hops to follow.")


class Dependency(DomainModel):
    id: str
    source: str
    target: str
    protocol: CallProtocol
    criticality: Criticality
    timeout_ms: int | None

    @classmethod
    def of(cls, edge: DependencyEdge) -> "Dependency":
        return cls(id=edge.id, **edge.model_dump())


class DependencyQueryResult(ToolOutput):
    service: str
    services: tuple[ServiceInfo, ...]
    dependencies: tuple[Dependency, ...]

    def artifacts(self) -> tuple[str, ...]:
        return tuple(dependency.id for dependency in self.dependencies)


class ServiceDependenciesTool:
    name = ToolName.GET_SERVICE_DEPENDENCIES
    description = (
        "Show which services a service calls (downstream) and which call it (upstream), with "
        "protocol, timeout and whether each dependency is hard (its failure fails the caller) "
        "or soft. Use it to trace how a failure could spread. Dependency ids can be cited."
    )
    args_model = DependencyQuery

    def __init__(self, catalog: ServiceCatalog) -> None:
        self._catalog = catalog

    async def run(self, args: DependencyQuery) -> DependencyQueryResult:
        require_services(self._catalog, [args.service])
        edges: dict[str, DependencyEdge] = {}
        frontier, seen = {args.service}, {args.service}
        for _ in range(args.depth):
            reached = set()
            for edge in self._catalog.edges():
                if args.direction in ("downstream", "both") and edge.source in frontier:
                    edges[edge.id] = edge
                    reached.add(edge.target)
                if args.direction in ("upstream", "both") and edge.target in frontier:
                    edges[edge.id] = edge
                    reached.add(edge.source)
            frontier = reached - seen
            seen |= reached
        return DependencyQueryResult(
            service=args.service,
            services=tuple(self._catalog.service(name) for name in sorted(seen)),
            dependencies=tuple(Dependency.of(edge) for _, edge in sorted(edges.items())),
        )
