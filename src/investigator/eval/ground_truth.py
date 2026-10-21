from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from investigator.domain.artifacts import ArtifactId, artifact_kind
from investigator.domain.base import DomainModel
from investigator.domain.causes import Outcome, RootCause
from investigator.world.dataset import Dataset, load_yaml_model

EXPECTED_FILE = "expected.yaml"


class Split(StrEnum):
    DEV = "dev"
    """Used while tuning prompts and thresholds."""
    TEST = "test"
    """Held out; the only incidents whose results are reported."""


class Tag(StrEnum):
    CONTROL = "control"
    MISLEADING = "misleading"
    CONFLICTING = "conflicting"
    TOOL_FAILURE = "tool-failure"
    INCONCLUSIVE = "inconclusive"


class LogPattern(DomainModel):
    service: str
    contains: str


class KeyEvidence(DomainModel):
    """What a well-grounded report should cite in support of the true cause."""

    changes: tuple[ArtifactId, ...] = ()
    metrics: tuple[ArtifactId, ...] = ()
    log_patterns: tuple[LogPattern, ...] = ()

    @model_validator(mode="after")
    def _kinds(self) -> Self:
        if any(artifact_kind(ref) != "chg" for ref in self.changes):
            raise ValueError("key_evidence.changes must be chg: ids")
        if any(artifact_kind(ref) != "metric" for ref in self.metrics):
            raise ValueError("key_evidence.metrics must be metric: ids")
        return self


class GroundTruth(DomainModel):
    split: Split
    tags: tuple[Tag, ...] = Field(min_length=1)
    expected_outcome: Outcome
    root_cause: RootCause | None
    acceptable_alternates: tuple[RootCause, ...] = ()
    key_evidence: KeyEvidence
    red_herrings: tuple[ArtifactId, ...] = ()
    """Artifacts placed to mislead; citing them as support for the answer is a mistake."""
    notes: str

    @model_validator(mode="after")
    def _outcome_matches_cause(self) -> Self:
        if (self.expected_outcome is Outcome.CONCLUSIVE) != (self.root_cause is not None):
            raise ValueError(
                "a root cause is given exactly when the expected outcome is conclusive"
            )
        return self


def load_ground_truth(dataset: Dataset, incident_id: str) -> GroundTruth:
    return load_yaml_model(GroundTruth, dataset.incident_dir(incident_id) / EXPECTED_FILE)
