# 5. A shared notebook and a budget

*Decided 21 October 2026.*

**The problem.** Agents work at the same time and need one shared picture of the evidence,
with firm limits on spending, and protection against the AI inventing evidence or giving
malformed answers.

**What we chose.**
- **A shared notebook only the program writes to.** Agents hand back findings, and the
  program records them. Any evidence a tool never returned is dropped.
- **A time limit and one retry for every agent step.** An agent that still fails becomes
  missing evidence, and the others carry on.
- **A budget** for AI calls, tool calls, words and time, with a reserve kept back so the
  report can always be written.
- **Two steps per agent:** first it uses its tools, then it gives its answer in a fixed
  format, which is checked and can be corrected once.

**The cost.** The separate answer step costs one extra AI call per agent.
