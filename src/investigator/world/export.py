import csv
import json
from pathlib import Path

from investigator.domain.incident import IncidentReport
from investigator.world.store import TelemetryStore


def export_world(report: IncidentReport, store: TelemetryStore, out_dir: Path) -> list[Path]:
    """Write an incident's rendered telemetry as plain files for a person to read."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = [
        _write_json(out_dir / "incident.json", report.model_dump(mode="json")),
        _write_json(out_dir / "changes.json", [c.model_dump(mode="json") for c in store.changes]),
        _write_json(
            out_dir / "dependencies.json",
            [{"id": e.id, **e.model_dump(mode="json")} for e in store.dependencies],
        ),
    ]

    logs = out_dir / "logs.jsonl"
    with logs.open("w", encoding="utf-8") as handle:
        for record in store.logs:
            handle.write(record.model_dump_json(exclude={"template"}) + "\n")
    written.append(logs)

    metrics = out_dir / "metrics.csv"
    with metrics.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["series", "unit", "ts", "value"])
        for series in store.metrics.values():
            for ts, value in zip(series.timestamps(), series.values, strict=True):
                writer.writerow([series.id, series.unit, ts.isoformat(), value])
    written.append(metrics)
    return written


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
