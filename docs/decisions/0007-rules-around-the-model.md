# 7. The AI judges the evidence; fixed rules do the checking

*Decided 21 October 2026.*

**The problem.** In early test runs the AI made mistakes that better instructions didn't
reliably fix. An agent ignored the update that caused the problem, because it only looked
at the services it was told about. The critic blocked a correct answer by asking for
something no tool can provide. Two possible causes blocked each other forever.

**What we chose.** The AI decides what evidence means; plain rules handle everything that
can be checked mechanically:
- every recent change is listed before anyone guesses;
- evidence no tool returned is dropped;
- a change made after the problem was reported can't be its cause;
- a cause the critic has itself dismissed can't hold another one back;
- a cause backed only by old incidents, or with no logs or measurements behind it, is held
  to a lower confidence;
- the answer counts as conclusive only if it is confident, clearly ahead of the next best
  cause, and has no unresolved objection.

**The cost.** Strict rules sometimes hold back a correct answer. The evaluation counts
those cases separately.
