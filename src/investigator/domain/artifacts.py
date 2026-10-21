"""Identifiers for the evidence tools return and agents cite.

Every record a tool can return carries an id of the form ``<kind>:<local-id>``. A claim
in a report points at these ids, which is what makes its grounding checkable.
"""

import re
from typing import Annotated, Literal, cast, get_args

from pydantic import StringConstraints

ArtifactKind = Literal["log", "metric", "chg", "dep", "pir"]

_PATTERN = rf"^({'|'.join(get_args(ArtifactKind))}):\S+$"

ArtifactId = Annotated[str, StringConstraints(pattern=_PATTERN)]


def artifact_kind(artifact_id: str) -> ArtifactKind:
    if not re.fullmatch(_PATTERN, artifact_id):
        raise ValueError(f"not an artifact id: {artifact_id!r}")
    return cast(ArtifactKind, artifact_id.split(":", 1)[0])


def metric_id(service: str, metric: str) -> str:
    return f"metric:{service}/{metric}"


def dependency_id(source: str, target: str) -> str:
    return f"dep:{source}->{target}"
