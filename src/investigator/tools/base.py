"""What every investigation tool looks like to the rest of the system."""

from typing import Any, Protocol

from investigator.domain.base import DomainModel
from investigator.domain.tools import ToolName


class ToolArgs(DomainModel):
    """Arguments an agent passes to a tool."""


class ToolOutput(DomainModel):
    notices: tuple[str, ...] = ()
    """Data the backend could not return. Any notice makes the result partial."""
    warnings: tuple[str, ...] = ()
    """Caveats that do not mean data is missing, such as truncated results."""

    def artifacts(self) -> tuple[str, ...]:
        """Ids of the records in this output that a report may cite."""
        return ()


class Tool(Protocol):
    @property
    def name(self) -> ToolName: ...

    @property
    def description(self) -> str: ...

    @property
    def args_model(self) -> type[ToolArgs]: ...

    async def run(self, args: Any) -> ToolOutput:
        """Answer the query, or raise a ``ToolFailure``."""
        ...
