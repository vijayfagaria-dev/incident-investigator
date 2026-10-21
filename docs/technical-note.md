# Technical note

## The problem

Find the root cause of a production incident from logs, metrics, changes, dependencies
and past incidents, despite misleading clues and failing tools, within a budget, and say
"we can't tell" when the evidence doesn't support a conclusion.

## Design

**Six agents, one shared notebook.** An orchestrator plans; observability and dependency
specialists gather evidence in parallel; a reasoning agent proposes causes; a critic
challenges them and asks for more evidence; a reporting agent writes the report. Agents
never message each other: each returns typed findings, and only the program writes them to
the notebook, dropping any citation of data no tool returned.

**LangGraph runs the flow.** The investigation is a graph: plan, gather in parallel, follow
leads, propose, critique, then another round or the report. Each agent's own work is a
small graph: think, use tools, answer in a checked structure. What decides whether an
answer can be trusted stays in plain, tested code: the notebook, the budget and the rules.

**The AI judges, fixed rules check.** Every recent change is listed before anyone
guesses. A change made after the problem was reported can't be its cause. A cause seen
only in old incidents, or with no logs or measurements behind it, is held to a lower
confidence. An answer is conclusive only if it is confident enough, clearly ahead of the
next cause, and has no unresolved objection.

**Failure is expected.** Tools time out, go down or return partial data on purpose. One
executor retries them, stops calling a tool that keeps failing, and turns every failure
into missing evidence in the report. Each agent step has a time limit and one retry. Rate
limits pause every caller; a request the main model still fails goes to a backup model.
A reserve in the budget guarantees a report.

**Free and repeatable.** The AI is NVIDIA's free Nemotron 3 Ultra. Every reply is
recorded, so any investigation can be watched again without a key.

## Results

Ten held-out incidents, three runs each, against a single agent with the same tools,
model, budget and rules ([details](evaluation.md)). Both are
right equally often (47%), but the team gives a wrong conclusion far less often (13%
against 43%), and when it concludes it is right 76% of the time, against 52%. The price
is caution and cost: it says "we can't tell" on 44% of incidents that had an answer, and
makes about three and a half times as many AI calls.

## Limits

- The rules that prevent wrong answers also hold back right ones: in several runs the
  team had the true cause ranked first but would not commit to it.
- Ten incidents we wrote ourselves give a direction, not proof, and only one model was
  tested.

## Next steps

- Tune the conclusion rule and the critic on more development incidents, to keep the low
  error rate while committing more often.
- More incidents, more runs per incident, and a second model.
