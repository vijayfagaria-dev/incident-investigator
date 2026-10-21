"""The one thing agents need from a language model, and the ways a call can fail."""

from typing import Protocol

from investigator.llm.messages import ChatRequest, ChatResponse


class ModelGateway(Protocol):
    """One chat completion. Raises ``ModelError`` when the call fails."""

    async def complete(self, request: ChatRequest) -> ChatResponse: ...


class ModelError(Exception):
    retryable = False


class ModelUnavailable(ModelError):
    """Timeouts, connection failures and server errors."""

    retryable = True


class ModelRateLimited(ModelError):
    retryable = True


class ModelRejected(ModelError):
    """The provider refused the request as malformed, unauthorised or unsupported."""


class StructuredOutputError(ModelError):
    """The model's answer did not parse into the required structure."""
