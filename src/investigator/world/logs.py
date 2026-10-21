"""Log lines: request logs that follow the metrics, background noise, and what a scenario adds.

Each kind of line draws from its own random stream in a fixed order, which is what keeps
an incident's telemetry identical from run to run.
"""

import hashlib
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from random import Random

from investigator.domain.telemetry import LogLevel, LogRecord
from investigator.world.metrics import MetricValues
from investigator.world.randomness import RandomStreams, poisson
from investigator.world.scenario import LogEffect
from investigator.world.topology import ChoiceField, FieldSpec, Node, NodeKind, UniformField

ACCESS_LOG_TEMPLATE = "{method} {path} {status} {duration_ms}ms"

_FAILURE_STATUSES = (500, 502, 503, 504)
_SUCCESS_STATUS = {"POST": 201}
_MINUTE = timedelta(minutes=1)
_Z_99 = 2.326
"""Standard normal quantile at the 99th percentile."""
_POD_ALPHABET = "bcdfghjklmnpqrstvwxz2456789"

FieldValue = str | int | float


@dataclass(frozen=True)
class Pod:
    name: str
    az: str


@dataclass(frozen=True)
class LogLine:
    ts: datetime
    service: str
    pod: Pod
    level: LogLevel
    template: str
    fields: dict[str, FieldValue]
    trace_id: str

    @property
    def message(self) -> str:
        return self.template.format(**self.fields)


def layout_pods(node: Node, zones: Sequence[str]) -> list[Pod]:
    """Spread a node's pods across zones, named the way Kubernetes would name them.

    Services get Deployment-style names; datastores and queues get StatefulSet ordinals.
    Names depend only on the node, so they are the same in every incident.
    """
    if node.kind is not NodeKind.SERVICE:
        return [Pod(f"{node.name}-{i}", zones[i % len(zones)]) for i in range(node.pods)]
    rng = Random(f"pods/{node.name}")
    replica_set = "".join(rng.choices(_POD_ALPHABET, k=10))
    pods = []
    for i in range(node.pods):
        suffix = "".join(rng.choices(_POD_ALPHABET, k=5))
        pods.append(Pod(f"{node.name}-{replica_set}-{suffix}", zones[i % len(zones)]))
    return pods


def access_lines(
    node: Node, pods: Sequence[Pod], metrics: MetricValues, rng: Random, minutes: Sequence[datetime]
) -> list[LogLine]:
    """Sampled request logs whose status and latency follow the node's own metrics."""
    error_rates = metrics[(node.name, "error_rate")]
    p50s = metrics[(node.name, "latency_p50_ms")]
    p99s = metrics[(node.name, "latency_p99_ms")]
    lines = []
    for i, minute in enumerate(minutes):
        # Log-normal latency whose median and 99th percentile match the metrics.
        p50 = p50s[i]
        sigma = max(0.05, math.log(max(p99s[i], p50 * 1.01) / p50) / _Z_99)
        for pod in pods:
            for _ in range(poisson(rng, node.access_logs_per_pod_minute)):
                lines.append(_request(node, pod, minute, error_rates[i], p50, sigma, rng))
    return lines


def background_lines(
    node: Node, pods: Sequence[Pod], streams: RandomStreams, minutes: Sequence[datetime]
) -> list[LogLine]:
    """Messages a node emits in normal operation: the noise every investigation wades through."""
    lines = []
    for spec in node.background_logs:
        rng = streams.stream("background", node.name, spec.template)
        for minute in minutes:
            for _ in range(poisson(rng, spec.rate_per_hour / 60)):
                ts = minute + _offset(rng, _MINUTE)
                pod = rng.choice(pods)
                lines.append(
                    _templated_line(rng, ts, node.name, pod, spec.level, spec.template, spec.fields)
                )
    return lines


def effect_lines(
    effect: LogEffect, pods: Sequence[Pod], rng: Random, minutes: Sequence[datetime]
) -> list[LogLine]:
    """Messages a scenario injects: the symptoms, and the red herrings, of the incident."""
    eligible = [pod for pod in pods if effect.az is None or pod.az == effect.az]
    if not eligible:
        raise ValueError(f"{effect.service} has no pods in zone {effect.az!r}")

    def line(ts: datetime, pod: Pod) -> LogLine:
        return _templated_line(
            rng, ts, effect.service, pod, effect.level, effect.template, effect.fields
        )

    lines = []
    if effect.count is not None:
        end = effect.end or effect.start + _MINUTE
        span = end - effect.start
        for k in range(effect.count):
            lines.append(line(effect.start + _offset(rng, span), eligible[k % len(eligible)]))
        return lines
    assert effect.rate_per_min is not None
    for minute in minutes:
        if not effect.covers_minute(minute):
            continue
        for _ in range(poisson(rng, effect.rate_per_min)):
            ts = minute + _offset(rng, _MINUTE)
            if effect.covers(ts):
                lines.append(line(ts, rng.choice(eligible)))
    return lines


def to_records(lines: Iterable[LogLine]) -> tuple[LogRecord, ...]:
    """Order lines by time and give each a content-derived, collision-free id."""
    records = []
    seen: set[str] = set()
    for line in sorted(lines, key=lambda x: (x.ts, x.service, x.pod.name, x.template)):
        message = line.message
        digest = hashlib.sha1(
            f"{line.ts.isoformat()}|{line.pod.name}|{message}".encode()
        ).hexdigest()
        record_id, suffix = f"log:{digest[:12]}", 0
        while record_id in seen:
            suffix += 1
            record_id = f"log:{digest[:12]}-{suffix}"
        seen.add(record_id)
        records.append(
            LogRecord(
                id=record_id,
                ts=line.ts,
                service=line.service,
                pod=line.pod.name,
                az=line.pod.az,
                level=line.level,
                message=message,
                template=line.template,
                trace_id=line.trace_id,
                attrs=line.fields,
            )
        )
    return tuple(records)


def draw_fields(fields: Mapping[str, FieldSpec], rng: Random) -> dict[str, FieldValue]:
    """Fill a template's fields, drawing the random ones."""
    values: dict[str, FieldValue] = {}
    for name, spec in fields.items():
        if isinstance(spec, UniformField):
            low, high = spec.uniform
            if low.is_integer() and high.is_integer():
                values[name] = rng.randint(int(low), int(high))
            else:
                values[name] = round(rng.uniform(low, high), 2)
        elif isinstance(spec, ChoiceField):
            values[name] = rng.choice(spec.choice)
        else:
            values[name] = spec
    return values


def _request(
    node: Node, pod: Pod, minute: datetime, error_rate: float, p50: float, sigma: float, rng: Random
) -> LogLine:
    method, path = rng.choice(node.routes).split(" ", 1)
    failed = rng.random() < error_rate
    status = rng.choice(_FAILURE_STATUSES) if failed else _SUCCESS_STATUS.get(method, 200)
    ts = minute + _offset(rng, _MINUTE)
    duration_ms = max(1, round(p50 * math.exp(rng.gauss(0, sigma))))
    return LogLine(
        ts=ts,
        service=node.name,
        pod=pod,
        level=LogLevel.ERROR if failed else LogLevel.INFO,
        template=ACCESS_LOG_TEMPLATE,
        fields={"method": method, "path": path, "status": status, "duration_ms": duration_ms},
        trace_id=_trace_id(rng),
    )


def _templated_line(
    rng: Random,
    ts: datetime,
    service: str,
    pod: Pod,
    level: LogLevel,
    template: str,
    fields: Mapping[str, FieldSpec],
) -> LogLine:
    return LogLine(
        ts=ts,
        service=service,
        pod=pod,
        level=level,
        template=template,
        fields=draw_fields(fields, rng),
        trace_id=_trace_id(rng),
    )


def _offset(rng: Random, span: timedelta) -> timedelta:
    return timedelta(milliseconds=round(rng.uniform(0, span.total_seconds() * 1000)))


def _trace_id(rng: Random) -> str:
    return f"{rng.getrandbits(64):016x}"
