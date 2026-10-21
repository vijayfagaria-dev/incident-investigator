import math
import re
from collections import Counter
from collections.abc import Sequence
from datetime import date

from pydantic import Field

from investigator.domain.base import DomainModel
from investigator.domain.causes import RootCause
from investigator.domain.telemetry import PastIncident
from investigator.domain.tools import ToolName
from investigator.tools.base import ToolArgs, ToolOutput

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into", "is", "it"}
    | {"its", "of", "on", "or", "that", "the", "to", "was", "were", "with"}
)


class KeywordHistoryIndex:
    """BM25 ranking over each postmortem's title, services, symptoms and summary."""

    K1 = 1.2
    B = 0.75
    SERVICE_BOOST = 1.25

    def __init__(self, incidents: Sequence[PastIncident]) -> None:
        self._incidents = incidents
        self._documents = [Counter(_tokens(_text(incident))) for incident in incidents]
        self._lengths = [sum(document.values()) for document in self._documents]
        self._average_length = sum(self._lengths) / len(self._lengths) if incidents else 0.0
        frequencies = Counter(term for document in self._documents for term in document)
        total = len(incidents)
        self._idf = {
            term: math.log(1 + (total - count + 0.5) / (count + 0.5))
            for term, count in frequencies.items()
        }

    def search(
        self, text: str, services: Sequence[str], limit: int
    ) -> list[tuple[PastIncident, float]]:
        terms = set(_tokens(text))
        scored = []
        for incident, document, length in zip(
            self._incidents, self._documents, self._lengths, strict=True
        ):
            score = sum(self._term_score(term, document, length) for term in terms)
            if services and set(services) & set(incident.services):
                score *= self.SERVICE_BOOST
            if score > 0:
                scored.append((incident, round(score, 3)))
        scored.sort(key=lambda pair: (-pair[1], pair[0].id))
        return scored[:limit]

    def _term_score(self, term: str, document: Counter[str], length: int) -> float:
        frequency = document[term]
        if not frequency:
            return 0.0
        norm = self.K1 * (1 - self.B + self.B * length / self._average_length)
        return self._idf[term] * frequency * (self.K1 + 1) / (frequency + norm)


class HistoryQuery(ToolArgs):
    query: str = Field(min_length=3, description="Symptoms or keywords to look for.")
    services: tuple[str, ...] = Field(default=(), description="Prefer incidents on these services.")
    limit: int = Field(default=5, ge=1, le=10)


class HistoryMatch(DomainModel):
    id: str
    date: date
    title: str
    services: tuple[str, ...]
    symptoms: tuple[str, ...]
    root_cause: RootCause
    summary: str
    resolution: str
    score: float


class HistoryQueryResult(ToolOutput):
    matches: tuple[HistoryMatch, ...]

    def artifacts(self) -> tuple[str, ...]:
        return tuple(match.id for match in self.matches)


class IncidentHistoryTool:
    name = ToolName.SEARCH_INCIDENT_HISTORY
    description = (
        "Search past postmortems by symptoms or keywords. A similar past incident suggests "
        "where to look; it is an analogy, not evidence about the current incident, and "
        "similar symptoms often had different causes."
    )
    args_model = HistoryQuery

    def __init__(self, history: KeywordHistoryIndex) -> None:
        self._history = history

    async def run(self, args: HistoryQuery) -> HistoryQueryResult:
        matches = self._history.search(args.query, args.services, args.limit)
        return HistoryQueryResult(
            matches=tuple(
                HistoryMatch(**incident.model_dump(), score=score) for incident, score in matches
            )
        )


def _text(incident: PastIncident) -> str:
    return " ".join((incident.title, *incident.services, *incident.symptoms, incident.summary))


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]
