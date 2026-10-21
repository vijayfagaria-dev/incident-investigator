"""What every agent shares: the loop it runs through, its prompt, and committing its answer."""

from collections.abc import Iterable, Sequence
from importlib.resources import files

from pydantic import BaseModel

from investigator.agents.outputs import KeyedAssumption, KeyedObservation
from investigator.domain.investigation import (
    AssumptionDraft,
    GapDraft,
    HypothesisDraft,
    ObservationDraft,
)
from investigator.domain.tools import ErrorKind, ToolStatus
from investigator.runtime.agent_loop import AgentLoop, AgentRun, AgentSpec
from investigator.runtime.blackboard import Blackboard, Commit
from investigator.tools.results import ToolResult


class Agent[O: BaseModel]:
    """An agent is a fixed spec (role, prompt, tools, output) run through the shared loop."""

    def __init__(self, loop: AgentLoop, spec: AgentSpec[O]) -> None:
        self._loop = loop
        self.spec = spec

    @property
    def role(self) -> str:
        return self.spec.role

    async def run(self, brief: str) -> AgentRun[O]:
        return await self._loop.run(self.spec, brief)


def gaps_from(results: Iterable[ToolResult]) -> list[GapDraft]:
    """Evidence gaps implied by failed or partial tool calls, whether or not the agent noticed."""
    gaps: dict[tuple[str, str, str], GapDraft] = {}
    for result in results:
        if result.status is ToolStatus.PARTIAL:
            reason = "; ".join(result.notices)
        elif result.error is not None and result.error.kind is not ErrorKind.INVALID_QUERY:
            reason = f"{result.error.kind}: {result.error.message}"
        else:
            continue
        gap = GapDraft(tool=result.tool, scope=_scope(result.arguments), reason=reason)
        gaps[(gap.tool, gap.scope, gap.reason)] = gap
    return list(gaps.values())


def load_prompt(name: str, **values: str) -> str:
    """A system prompt from ``agents/prompts/<name>.md``, with ``{placeholders}`` filled in."""
    text = (files("investigator.agents") / "prompts" / f"{name}.md").read_text(encoding="utf-8")
    return text.format(**values) if values else text


def commit_with_keys(
    board: Blackboard,
    source: str,
    *,
    observations: Sequence[KeyedObservation] = (),
    assumptions: Sequence[KeyedAssumption] = (),
    hypotheses: Sequence[HypothesisDraft] = (),
) -> Commit:
    """Commit an answer whose hypotheses cite labels (F1, A1, N1) rather than board ids.

    An agent that reports evidence and hypotheses in one answer cannot know the ids the board
    will assign, so it labels each item and cites the labels. They are resolved here, once
    the board has accepted the items they name.
    """
    keys: dict[str, str] = {}
    problems: list[str] = []
    accepted: list[str] = []
    for observation in observations:
        commit = board.add_findings(
            source, observations=[ObservationDraft(**observation.model_dump(exclude={"key"}))]
        )
        problems += commit.problems
        if commit.accepted:
            keys[observation.key] = commit.accepted[0]
    for assumption in assumptions:
        draft = AssumptionDraft(**assumption.model_dump(exclude={"key"}))
        keys[assumption.key] = board.add_findings(source, assumptions=[draft]).accepted[0]
    accepted += keys.values()

    def resolve(refs: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(keys.get(ref, ref) for ref in refs)

    commit = board.add_hypotheses(
        [
            draft.model_copy(
                update={
                    "supporting": resolve(draft.supporting),
                    "contradicting": resolve(draft.contradicting),
                    "assumptions": resolve(draft.assumptions),
                }
            )
            for draft in hypotheses
        ]
    )
    return Commit((*accepted, *commit.accepted), (*problems, *commit.problems))


def _scope(arguments: dict[str, object]) -> str:
    keys = ("service", "metric", "services", "start", "end")
    return ", ".join(f"{k}={arguments[k]}" for k in keys if arguments.get(k)) or "all"
