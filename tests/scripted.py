"""A gateway that replays prepared replies, for tests that must not touch a real model."""

import itertools
import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from investigator.domain.base import DomainModel
from investigator.domain.runs import FinishReason
from investigator.llm.messages import (
    ChatRequest,
    ChatResponse,
    Message,
    Role,
    ToolCallRequest,
    Usage,
)

Script = Callable[[ChatRequest], ChatResponse]

_ids = itertools.count(1)


def say(text: str, tokens: int = 10) -> ChatResponse:
    return _response(Message(role=Role.ASSISTANT, content=text), FinishReason.STOP, tokens)


def call(*calls: tuple[str, Mapping[str, Any] | str], tokens: int = 10) -> ChatResponse:
    """A reply asking for tools; arguments given as a string are passed through verbatim."""
    requests = tuple(
        ToolCallRequest(
            id=f"tc-{next(_ids)}",
            name=name,
            arguments=arguments if isinstance(arguments, str) else json.dumps(arguments),
        )
        for name, arguments in calls
    )
    message = Message(role=Role.ASSISTANT, tool_calls=requests)
    return _response(message, FinishReason.TOOL_CALLS, tokens)


def answer(payload: DomainModel | Mapping[str, Any], tokens: int = 10) -> ChatResponse:
    text = payload.model_dump_json() if isinstance(payload, DomainModel) else json.dumps(payload)
    return say(text, tokens)


def _response(message: Message, finish: FinishReason, tokens: int) -> ChatResponse:
    return ChatResponse(
        message=message,
        finish_reason=finish,
        usage=Usage(prompt_tokens=tokens, completion_tokens=tokens),
        model="scripted",
        latency_ms=0.0,
    )


class ScriptedGateway:
    """Replies from a fixed sequence, or from a function of the request; records every request."""

    def __init__(self, script: Iterable[ChatResponse] | Script) -> None:
        self._script: Script
        if callable(script):
            self._script = script
        else:
            replies = iter(list(script))
            self._script = lambda _request: next(replies)
        self.requests: list[ChatRequest] = []

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        try:
            return self._script(request)
        except StopIteration:
            raise AssertionError("the script ran out of replies") from None
