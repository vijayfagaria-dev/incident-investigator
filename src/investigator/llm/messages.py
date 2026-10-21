"""Provider-neutral chat types. Gateways translate them to and from each provider's wire format."""

from enum import StrEnum
from typing import Any

from investigator.domain.base import DomainModel
from investigator.domain.runs import FinishReason


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCallRequest(DomainModel):
    """A tool call the model asked for. ``arguments`` is raw JSON and may be malformed."""

    id: str
    name: str
    arguments: str


class Message(DomainModel):
    role: Role
    content: str = ""
    tool_calls: tuple[ToolCallRequest, ...] = ()
    tool_call_id: str | None = None

    @classmethod
    def system(cls, content: str) -> "Message":
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> "Message":
        return cls(role=Role.USER, content=content)

    @classmethod
    def tool_result(cls, call_id: str, content: str) -> "Message":
        return cls(role=Role.TOOL, content=content, tool_call_id=call_id)


class Usage(DomainModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ToolDefinition(DomainModel):
    name: str
    description: str
    parameters: dict[str, Any]


class ChatRequest(DomainModel):
    purpose: str
    """Who is asking, e.g. ``observability``; recorded in the trace."""
    messages: tuple[Message, ...]
    tools: tuple[ToolDefinition, ...] = ()
    response_schema: dict[str, Any] | None = None
    """When set, the reply must be one JSON object matching this schema."""
    max_tokens: int = 4096


class ChatResponse(DomainModel):
    message: Message
    finish_reason: FinishReason
    usage: Usage
    model: str
    latency_ms: float
