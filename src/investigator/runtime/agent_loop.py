"""One agent's conversation: gather evidence with tools, then state a structured conclusion."""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ValidationError

from investigator.domain.runs import FinishReason, StopReason
from investigator.domain.tools import ToolName
from investigator.llm.gateway import ModelGateway, StructuredOutputError
from investigator.llm.messages import (
    ChatRequest,
    ChatResponse,
    Message,
    ToolCallRequest,
    ToolDefinition,
)
from investigator.runtime.budget import Budget
from investigator.tools.executor import ToolExecutor
from investigator.tools.results import CallRefused, InvalidQuery, ToolResult

CONCLUDE = (
    "Stop calling tools. Using only what you found, reply with one JSON object that matches "
    "this schema, and nothing else:\n{schema}"
)
REPAIR = "That reply was not usable: {problem}. Reply again with only the corrected JSON object."
TRUNCATED = (
    "That reply was cut off before the JSON was complete. Reply again with only the JSON "
    "object, keeping every text field short."
)
STEP_LIMIT = "You have used all your tool steps. Conclude with what you have."


@dataclass(frozen=True)
class AgentSpec[O: BaseModel]:
    role: str
    system_prompt: str
    output_model: type[O]
    tools: tuple[ToolName, ...] = ()
    max_steps: int = 6
    max_tokens: int = 16_000


@dataclass(frozen=True)
class AgentRun[O: BaseModel]:
    output: O
    tool_results: tuple[ToolResult, ...]
    stop_reason: StopReason


@dataclass
class _Conversation:
    spec: AgentSpec[Any]
    messages: list[Message]
    tool_results: list[ToolResult] = field(default_factory=list)


class _AgentState(TypedDict, total=False):
    conversation: _Conversation
    tools: tuple[ToolDefinition, ...]
    calls: tuple[ToolCallRequest, ...]
    steps: int
    stop: StopReason | None
    output: BaseModel


class AgentLoop:
    """Runs an agent as a small LangGraph graph: think, act on its tool calls, repeat, answer.

    The agent thinks (one model call with its tools), acts on the tools it asked for, and
    repeats up to its step limit or until it stops asking. Then it answers in its fixed
    format, in a separate call without tools.
    """

    def __init__(self, gateway: ModelGateway, executor: ToolExecutor, budget: Budget) -> None:
        self._gateway = gateway
        self._executor = executor
        self._budget = budget
        graph = StateGraph(_AgentState)
        graph.add_node("think", self._think)
        graph.add_node("act", self._act)
        graph.add_node("answer", self._answer)
        graph.add_conditional_edges(START, _answer_if_stopped("think"), ["think", "answer"])
        graph.add_conditional_edges("think", _answer_if_stopped("act"), ["act", "answer"])
        graph.add_conditional_edges("act", _answer_if_stopped("think"), ["think", "answer"])
        graph.add_edge("answer", END)
        self._graph = graph.compile()

    async def run[O: BaseModel](self, spec: AgentSpec[O], task: str) -> AgentRun[O]:
        conversation = _Conversation(spec, [Message.system(spec.system_prompt), Message.user(task)])
        tools = tuple(self._executor.registry.definitions(spec.tools))
        stop = None
        if not tools:
            stop = StopReason.CONCLUDED
        elif spec.max_steps < 1:
            stop = StopReason.STEP_LIMIT
        state: _AgentState = {
            "conversation": conversation,
            "tools": tools,
            "steps": 0,
            "stop": stop,
        }
        final = await self._graph.ainvoke(state, {"recursion_limit": 2 * spec.max_steps + 5})
        output: O = final["output"]
        return AgentRun(output, tuple(conversation.tool_results), final["stop"])

    async def _think(self, state: _AgentState) -> _AgentState:
        if self._budget.exploration_stop_reason() is not None:
            return {"stop": StopReason.BUDGET}
        reply = await self._ask(state["conversation"], tools=state["tools"])
        if not reply.message.tool_calls:
            return {"stop": StopReason.CONCLUDED}
        return {"calls": reply.message.tool_calls}

    async def _act(self, state: _AgentState) -> _AgentState:
        conversation, calls = state["conversation"], state["calls"]
        results = await asyncio.gather(*(self._call_tool(conversation.spec, c) for c in calls))
        conversation.tool_results += results
        for call, result in zip(calls, results, strict=True):
            conversation.messages.append(Message.tool_result(call.id, _render(result)))
        steps = state["steps"] + 1
        return {
            "steps": steps,
            "stop": StopReason.STEP_LIMIT if steps >= conversation.spec.max_steps else None,
        }

    async def _answer(self, state: _AgentState) -> _AgentState:
        conversation = state["conversation"]
        prefix = STEP_LIMIT + " " if state["stop"] is StopReason.STEP_LIMIT else ""
        return {
            "output": await self._conclude(conversation, conversation.spec.output_model, prefix)
        }

    async def _ask(
        self,
        conversation: _Conversation,
        tools: tuple[ToolDefinition, ...] = (),
        schema: dict[str, object] | None = None,
    ) -> ChatResponse:
        self._budget.require_model_call(concluding=schema is not None)
        reply = await self._gateway.complete(
            ChatRequest(
                purpose=conversation.spec.role,
                messages=tuple(conversation.messages),
                tools=tools,
                response_schema=schema,
                max_tokens=conversation.spec.max_tokens,
            )
        )
        self._budget.record_model_call(reply.usage)
        conversation.messages.append(reply.message)
        return reply

    async def _call_tool(self, spec: AgentSpec[Any], call: ToolCallRequest) -> ToolResult:
        try:
            arguments = json.loads(call.arguments or "{}")
        except json.JSONDecodeError as exc:
            return self._executor.reject(
                call.name, {}, InvalidQuery(f"arguments are not valid JSON: {exc}"), spec.role
            )
        if not isinstance(arguments, dict):
            return self._executor.reject(
                call.name, {}, InvalidQuery("arguments must be a JSON object"), spec.role
            )
        if not self._budget.take_tool_call():
            return self._executor.reject(
                call.name, arguments, CallRefused("tool call budget exhausted"), spec.role
            )
        return await self._executor.execute(
            call.name, arguments, allowed=spec.tools, caller=spec.role
        )

    async def _conclude[O: BaseModel](
        self, conversation: _Conversation, model: type[O], prefix: str
    ) -> O:
        """Ask for the structured answer, with one retry if it does not parse."""
        schema = model.model_json_schema()
        prompt = prefix + CONCLUDE.format(schema=json.dumps(schema))
        conversation.messages.append(Message.user(prompt))
        reply = await self._ask(conversation, schema=schema)
        try:
            return parse_structured(reply.message.content, model)
        except StructuredOutputError as first:
            truncated = reply.finish_reason is FinishReason.LENGTH
            retry = TRUNCATED if truncated else REPAIR.format(problem=first)
            conversation.messages.append(Message.user(retry))
        reply = await self._ask(conversation, schema=schema)
        return parse_structured(reply.message.content, model)


def _answer_if_stopped(otherwise: str) -> Callable[[_AgentState], str]:
    def route(state: _AgentState) -> str:
        return "answer" if state.get("stop") else otherwise

    return route


def _render(result: ToolResult) -> str:
    """What the model sees of a tool result: everything it can use, without bookkeeping."""
    return result.model_dump_json(
        include={"call_id", "status", "output", "notices", "warnings", "error"}, exclude_none=True
    )


def parse_structured[M: BaseModel](text: str, model: type[M]) -> M:
    """Parse a reply that should be one JSON object, tolerating code fences and stray prose."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise StructuredOutputError("the reply contains no JSON object")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise StructuredOutputError(f"the reply is not valid JSON: {exc}") from exc
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        problems = []
        for issue in exc.errors():
            where = ".".join(str(part) for part in issue["loc"]) or "object"
            problems.append(f"{where}: {issue['msg']}")
        raise StructuredOutputError(
            f"the JSON does not match the schema: {'; '.join(problems)}"
        ) from exc
