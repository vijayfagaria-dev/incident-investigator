from enum import StrEnum


class ToolName(StrEnum):
    QUERY_LOGS = "query_logs"
    QUERY_METRICS = "query_metrics"
    GET_CHANGE_HISTORY = "get_change_history"
    GET_SERVICE_DEPENDENCIES = "get_service_dependencies"
    SEARCH_INCIDENT_HISTORY = "search_incident_history"


class ToolStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    """Returned data, but the backend reported some of it missing."""
    ERROR = "error"


class ErrorKind(StrEnum):
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    INVALID_QUERY = "invalid_query"
    REFUSED = "refused"
    """The runtime declined to make the call, e.g. because the budget is spent."""
    INTERNAL = "internal"

    @property
    def retryable(self) -> bool:
        return self in _RETRYABLE


_RETRYABLE = frozenset({ErrorKind.TIMEOUT, ErrorKind.UNAVAILABLE, ErrorKind.RATE_LIMITED})
