"""The two investigation systems, built the same way so they can be compared."""

from enum import StrEnum
from typing import Protocol

from investigator.baseline import SingleAgentInvestigator
from investigator.domain.incident import IncidentReport
from investigator.domain.report import Report
from investigator.investigation.config import InvestigationConfig
from investigator.investigation.run import MultiAgentInvestigator
from investigator.llm.gateway import ModelGateway
from investigator.tools.registry import ToolRegistry
from investigator.tracing import Tracer


class Investigator(Protocol):
    async def investigate(self, incident: IncidentReport) -> Report: ...


class System(StrEnum):
    MULTI = "multi"
    SINGLE = "single"


def build_investigator(
    system: System,
    gateway: ModelGateway,
    tools: ToolRegistry,
    config: InvestigationConfig,
    tracer: Tracer,
) -> Investigator:
    if system is System.SINGLE:
        return SingleAgentInvestigator(gateway, tools, config, tracer)
    return MultiAgentInvestigator(gateway, tools, config, tracer)
