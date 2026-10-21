import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from investigator.domain.telemetry import (
    ChangeEvent,
    DependencyEdge,
    LogRecord,
    MetricSeries,
    TimeWindow,
)


@dataclass(frozen=True)
class TelemetryStore:
    """Everything observable about the platform during one incident window."""

    window: TimeWindow
    logs: tuple[LogRecord, ...]
    metrics: Mapping[str, MetricSeries]
    changes: tuple[ChangeEvent, ...]
    dependencies: tuple[DependencyEdge, ...]

    def fingerprint(self) -> str:
        """Stable hash of the full contents, used to detect unintended generator changes."""
        payload = {
            "window": self.window.model_dump(mode="json"),
            "logs": [record.model_dump(mode="json") for record in self.logs],
            "metrics": {key: s.model_dump(mode="json") for key, s in sorted(self.metrics.items())},
            "changes": [change.model_dump(mode="json") for change in self.changes],
            "dependencies": [edge.model_dump(mode="json") for edge in self.dependencies],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()
