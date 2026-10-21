"""File-backed repository for the synthetic incident dataset.

Layout::

    <root>/topology.yaml                    the platform shared by every incident
    <root>/history/<id>.yaml                past postmortems
    <root>/incidents/<id>/incident.yaml     the investigator's only input
    <root>/incidents/<id>/scenario.yaml     how to render the world; read only here
    <root>/incidents/<id>/expected.yaml     ground truth; read only by investigator.eval
"""

from functools import cached_property
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from investigator.domain.incident import IncidentReport
from investigator.domain.telemetry import PastIncident
from investigator.world.generator import TelemetryGenerator
from investigator.world.scenario import Scenario, ToolFault
from investigator.world.store import TelemetryStore
from investigator.world.topology import Topology

TOPOLOGY_FILE = "topology.yaml"
HISTORY_DIR = "history"
INCIDENTS_DIR = "incidents"
INCIDENT_FILE = "incident.yaml"
SCENARIO_FILE = "scenario.yaml"


class DatasetError(Exception):
    """A dataset file is missing or does not match its schema."""


def load_yaml_model[M: BaseModel](model: type[M], path: Path) -> M:
    try:
        with path.open(encoding="utf-8") as handle:
            data: Any = yaml.safe_load(handle)
        return model.model_validate(data)
    except FileNotFoundError as exc:
        raise DatasetError(f"{path}: file not found") from exc
    except (yaml.YAMLError, ValidationError) as exc:
        raise DatasetError(f"{path}: {exc}") from exc


class Dataset:
    def __init__(self, root: Path) -> None:
        self.root = root

    @cached_property
    def topology(self) -> Topology:
        return load_yaml_model(Topology, self.root / TOPOLOGY_FILE)

    @cached_property
    def _generator(self) -> TelemetryGenerator:
        return TelemetryGenerator(self.topology)

    def incident_ids(self) -> list[str]:
        incidents = self.root / INCIDENTS_DIR
        if not incidents.is_dir():
            raise DatasetError(f"{incidents}: not a directory")
        return sorted(path.parent.name for path in incidents.glob(f"*/{INCIDENT_FILE}"))

    def incident_dir(self, incident_id: str) -> Path:
        path = self.root / INCIDENTS_DIR / incident_id
        if not (path / INCIDENT_FILE).is_file():
            raise DatasetError(f"unknown incident {incident_id!r} in {self.root}")
        return path

    def incident_report(self, incident_id: str) -> IncidentReport:
        return load_yaml_model(IncidentReport, self.incident_dir(incident_id) / INCIDENT_FILE)

    def scenario(self, incident_id: str) -> Scenario:
        return load_yaml_model(Scenario, self.incident_dir(incident_id) / SCENARIO_FILE)

    def telemetry(self, incident_id: str) -> TelemetryStore:
        return self._generator.render(self.scenario(incident_id))

    def tool_faults(self, incident_id: str) -> tuple[ToolFault, ...]:
        scenario = self.scenario(incident_id)
        scenario.check_against(self.topology)
        return scenario.faults

    def history(self) -> tuple[PastIncident, ...]:
        incidents = [
            load_yaml_model(PastIncident, path)
            for path in sorted((self.root / HISTORY_DIR).glob("*.yaml"))
        ]
        return tuple(sorted(incidents, key=lambda incident: incident.date))
