"""Gateway for any OpenAI-compatible chat-completions endpoint (NVIDIA, Ollama, ...)."""

import time
from typing import Any, Protocol, cast

import openai

from investigator.domain.runs import FinishReason
from investigator.llm.gateway import ModelError, ModelRateLimited, ModelRejected, ModelUnavailable
from investigator.llm.messages import (
    ChatRequest,
    ChatResponse,
    Message,
    Role,
    ToolCallRequest,
    Usage,
)
from investigator.llm.profiles import ProviderProfile
from investigator.llm.ratelimit import RateLimiter
from investigator.tracing import MemoryTracer, ModelCalled, Tracer


class CompletionsAPI(Protocol):
    """The slice of the ``openai`` client this gateway uses: ``client.chat.completions``."""

    async def create(self, **params: Any) -> Any: ...


class OpenAICompatGateway:
    def __init__(
        self,
        profile: ProviderProfile,
        completions: CompletionsAPI,
        *,
        limiter: RateLimiter | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self._profile = profile
        self._completions = completions
        self._limiter = limiter or RateLimiter(profile.requests_per_minute)
        self._tracer = tracer or MemoryTracer()
        self._schema_mode = profile.structured_output

    @classmethod
    def connect(
        cls,
        profile: ProviderProfile,
        api_key: str,
        *,
        limiter: RateLimiter | None = None,
        tracer: Tracer | None = None,
    ) -> "OpenAICompatGateway":
        client = openai.AsyncOpenAI(
            base_url=profile.base_url, api_key=api_key, timeout=profile.timeout_s, max_retries=0
        )
        # The SDK's create() is heavily overloaded; this gateway only needs it as CompletionsAPI.
        completions = cast(CompletionsAPI, client.chat.completions)
        return cls(profile, completions, limiter=limiter, tracer=tracer)

    async def complete(self, request: ChatRequest) -> ChatResponse:
        try:
            return await self._complete(request)
        except ModelRejected:
            if request.response_schema is None or self._schema_mode != "json_schema":
                raise
        # Some endpoints reject schema-constrained output for complex schemas. The schema is
        # also in the prompt, so plain JSON mode still works; use it from now on.
        self._schema_mode = "json_object"
        return await self._complete(request)

    async def _complete(self, request: ChatRequest) -> ChatResponse:
        waited_s = await self._limiter.acquire()
        started = time.monotonic()
        try:
            raw = await self._completions.create(**self._params(request))
        except Exception as exc:
            error = _to_model_error(exc)
            self._trace(request, None, started, waited_s, error=f"{type(error).__name__}: {error}")
            raise error from exc
        response = self._response(raw, started)
        self._trace(request, response, started, waited_s)
        return response

    def _params(self, request: ChatRequest) -> dict[str, Any]:
        profile = self._profile
        params: dict[str, Any] = {
            "model": profile.model,
            "messages": [_to_openai_message(message) for message in request.messages],
            "max_tokens": request.max_tokens,
        }
        if request.tools:
            params["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
            params["tool_choice"] = "auto"
        if request.response_schema is not None:
            params["response_format"] = _response_format(self._schema_mode, request.response_schema)
        if profile.temperature is not None:
            params["temperature"] = profile.temperature
        if profile.top_p is not None:
            params["top_p"] = profile.top_p
        if profile.extra_body:
            params["extra_body"] = profile.extra_body
        return params

    def _response(self, raw: Any, started: float) -> ChatResponse:
        choice = raw.choices[0]
        calls = tuple(
            ToolCallRequest(
                id=call.id, name=call.function.name, arguments=call.function.arguments or "{}"
            )
            for call in (choice.message.tool_calls or ())
        )
        usage = raw.usage
        return ChatResponse(
            message=Message(
                role=Role.ASSISTANT, content=choice.message.content or "", tool_calls=calls
            ),
            finish_reason=_finish_reason(choice.finish_reason),
            usage=Usage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
            ),
            model=raw.model or self._profile.model,
            latency_ms=round((time.monotonic() - started) * 1000, 1),
        )

    def _trace(
        self,
        request: ChatRequest,
        response: ChatResponse | None,
        started: float,
        waited_s: float,
        error: str | None = None,
    ) -> None:
        latency_ms = round((time.monotonic() - started) * 1000, 1)
        wait_ms = round(waited_s * 1000, 1)
        if response is None:
            event = ModelCalled(
                purpose=request.purpose,
                model=self._profile.model,
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=latency_ms,
                rate_limit_wait_ms=wait_ms,
                finish_reason=None,
                tool_calls=0,
                error=error,
            )
        else:
            event = ModelCalled(
                purpose=request.purpose,
                model=response.model,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                latency_ms=latency_ms,
                rate_limit_wait_ms=wait_ms,
                finish_reason=response.finish_reason,
                tool_calls=len(response.message.tool_calls),
                error=error,
            )
        self._tracer.record(event)


def _to_openai_message(message: Message) -> dict[str, Any]:
    wire: dict[str, Any] = {"role": message.role.value, "content": message.content}
    if message.tool_calls:
        wire["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in message.tool_calls
        ]
    if message.tool_call_id is not None:
        wire["tool_call_id"] = message.tool_call_id
    return wire


def _response_format(mode: str, schema: dict[str, Any]) -> dict[str, Any]:
    if mode == "json_schema":
        return {
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": schema, "strict": True},
        }
    return {"type": "json_object"}


def _finish_reason(raw: str | None) -> FinishReason:
    if raw is None:
        return FinishReason.OTHER
    try:
        return FinishReason(raw)
    except ValueError:
        return FinishReason.OTHER


def _to_model_error(exc: Exception) -> ModelError:
    if isinstance(exc, openai.RateLimitError):
        return ModelRateLimited(str(exc))
    if isinstance(exc, openai.APIConnectionError):  # includes timeouts
        return ModelUnavailable(str(exc))
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code >= 500:
            return ModelUnavailable(str(exc))
        return ModelRejected(str(exc))
    return ModelUnavailable(f"unexpected {type(exc).__name__}: {exc}")
