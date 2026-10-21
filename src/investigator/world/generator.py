from datetime import datetime

from investigator.domain.artifacts import metric_id
from investigator.domain.telemetry import MetricSeries, TimeWindow
from investigator.world.logs import (
    LogLine,
    access_lines,
    background_lines,
    effect_lines,
    layout_pods,
    to_records,
)
from investigator.world.metrics import MetricSynthesizer, MetricValues
from investigator.world.randomness import RandomStreams
from investigator.world.scenario import Scenario
from investigator.world.store import TelemetryStore
from investigator.world.topology import Topology


class TelemetryGenerator:
    """Renders an incident scenario over the platform topology into telemetry."""

    def __init__(self, topology: Topology) -> None:
        self._topology = topology
        self._pods = {
            node.name: layout_pods(node, topology.availability_zones)
            for node in topology.nodes
            if node.pods
        }

    def render(self, scenario: Scenario) -> TelemetryStore:
        scenario.check_against(self._topology)
        streams = RandomStreams(scenario.seed)
        minutes = scenario.window.minutes()
        metrics = MetricSynthesizer(self._topology, streams).synthesize(
            minutes, scenario.metric_effects()
        )
        return TelemetryStore(
            window=scenario.window,
            logs=to_records(self._log_lines(scenario, metrics, streams, minutes)),
            metrics=self._series(metrics, scenario.window),
            changes=tuple(sorted(scenario.changes, key=lambda change: change.ts)),
            dependencies=self._topology.edges,
        )

    def _log_lines(
        self,
        scenario: Scenario,
        metrics: MetricValues,
        streams: RandomStreams,
        minutes: list[datetime],
    ) -> list[LogLine]:
        lines = []
        for node in self._topology.nodes:
            pods = self._pods.get(node.name, [])
            if node.routes:
                rng = streams.stream("access", node.name)
                lines += access_lines(node, pods, metrics, rng, minutes)
            if node.background_logs:
                lines += background_lines(node, pods, streams, minutes)
        for effect in scenario.log_effects():
            rng = streams.stream(
                "effect", effect.service, effect.template, effect.start.isoformat()
            )
            lines += effect_lines(effect, self._pods.get(effect.service, []), rng, minutes)
        return lines

    def _series(self, metrics: MetricValues, window: TimeWindow) -> dict[str, MetricSeries]:
        return {
            metric_id(service, name): MetricSeries(
                id=metric_id(service, name),
                service=service,
                name=name,
                unit=self._topology.metric_specs(service)[name].unit,
                start=window.start,
                values=tuple(float(f"{value:.4g}") for value in values),
            )
            for (service, name), values in metrics.items()
        }
