# 1. LangGraph runs the agents

*Decided 21 October 2026.*

**The problem.** Several agents work on one incident at once, share what they find, retry
when something fails, and must stop within a time and cost budget. Whether an
investigation can be trusted depends on these rules, so they need to be easy to read, easy
to test, and visible afterwards.

**What we chose.** [LangGraph](https://langchain-ai.github.io/langgraph/), a widely used
open-source library, runs the steps of an investigation as a graph: plan, gather evidence
in parallel, follow leads, suggest causes, challenge them, then go round again or write the
report. Each agent's own work is a small graph too: think, use tools, answer. The parts
that decide whether an answer can be trusted stay in our own code, where they can be read
and tested without the AI: the shared notebook, the budget, the evidence rules, and the
connection to the AI model.

**The cost.** One more library to keep up to date. LangGraph also decides the order in
which agents that finish at exactly the same moment are handled, which matters only when
a recorded investigation is run again (see [9](0009-record-and-replay.md)).
