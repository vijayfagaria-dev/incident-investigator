from enum import StrEnum

from pydantic import AwareDatetime, Field

from investigator.domain.base import DomainModel


class Severity(StrEnum):
    SEV1 = "sev1"
    SEV2 = "sev2"
    SEV3 = "sev3"
    SEV4 = "sev4"


class IncidentReport(DomainModel):
    """What on-call knows when an investigation starts. It may be incomplete or wrong."""

    id: str
    title: str
    severity: Severity
    reported_at: AwareDatetime
    reported_by: str
    summary: str
    symptoms: tuple[str, ...] = Field(min_length=1)
    reported_services: tuple[str, ...] = ()
    responder_notes: tuple[str, ...] = ()
