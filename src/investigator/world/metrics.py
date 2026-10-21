import math
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

from investigator.world.randomness import RandomStreams
from investigator.world.scenario import MetricEffect
from investigator.world.topology import Topology, Traffic

MetricValues = dict[tuple[str, str], list[float]]
"""Per-minute values keyed by ``(service, metric)``."""

_MINUTE = timedelta(minutes=1)


class MetricSynthesizer:
    """Builds every metric series: a noisy baseline that follows daily traffic, then effects."""

    def __init__(self, topology: Topology, streams: RandomStreams) -> None:
        self._topology = topology
        self._streams = streams

    def synthesize(
        self, minutes: Sequence[datetime], effects: Iterable[MetricEffect]
    ) -> MetricValues:
        values = {
            (node.name, name): self._baseline(node.name, name, minutes)
            for node in self._topology.nodes
            for name in sorted(self._topology.metric_specs(node.name))
        }
        for effect in effects:
            self._apply(effect, values[(effect.service, effect.metric)], minutes)
        for (service, name), series in values.items():
            self._clamp(service, name, series)
        return values

    def _baseline(self, service: str, name: str, minutes: Sequence[datetime]) -> list[float]:
        spec = self._topology.metric_specs(service)[name]
        rng = self._streams.stream("metric", service, name)
        return [
            spec.baseline
            * (_traffic_factor(self._topology.traffic, ts) if spec.follows_traffic else 1.0)
            * (1 + rng.gauss(0, spec.noise))
            for ts in minutes
        ]

    def _apply(
        self, effect: MetricEffect, series: list[float], minutes: Sequence[datetime]
    ) -> None:
        noise = self._topology.metric_specs(effect.service)[effect.metric].noise
        rng = self._streams.stream(
            "effect", effect.service, effect.metric, effect.start.isoformat()
        )
        first = effect.first_minute()
        for i, minute in enumerate(minutes):
            if not effect.covers_minute(minute):
                continue
            progress = effect.shape.progress((minute - first) // _MINUTE + 1, effect.ramp_minutes)
            series[i] += (effect.target(series[i], noise, rng) - series[i]) * progress

    def _clamp(self, service: str, name: str, series: list[float]) -> None:
        spec = self._topology.metric_specs(service)[name]
        ceiling = math.inf if spec.ceiling is None else spec.ceiling
        series[:] = [min(max(value, spec.floor), ceiling) for value in series]


def _traffic_factor(traffic: Traffic, ts: datetime) -> float:
    hour = ts.hour + ts.minute / 60
    return 1 + traffic.diurnal_amplitude * math.cos(
        2 * math.pi * (hour - traffic.peak_hour_utc) / 24
    )
