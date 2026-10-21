"""Root-cause vocabulary shared by investigations, past postmortems and scoring."""

from enum import StrEnum

from investigator.domain.artifacts import ArtifactId
from investigator.domain.base import DomainModel


class CauseCategory(StrEnum):
    """The kind of fault that started an incident, not the symptoms it produced.

    A connection pool shrunk by a config change is ``config_change``; the same pool
    exhausted by a traffic surge is ``capacity_saturation``.
    """

    CODE_REGRESSION = "code_regression"
    CONFIG_CHANGE = "config_change"
    FEATURE_FLAG = "feature_flag"
    DEPENDENCY_DEGRADATION = "dependency_degradation"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    CAPACITY_SATURATION = "capacity_saturation"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    CERTIFICATE_OR_CREDENTIAL = "certificate_or_credential"
    DATA_ISSUE = "data_issue"
    UNKNOWN = "unknown"


class RootCause(DomainModel):
    service: str
    category: CauseCategory
    trigger: ArtifactId | None = None
    """The change that set the incident off, when there was one."""


class Outcome(StrEnum):
    CONCLUSIVE = "conclusive"
    INCONCLUSIVE = "inconclusive"
