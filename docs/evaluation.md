# Results

## What was tested

Ten incidents that were kept aside while the system was built (T01 to T10, described in
[the test incidents](../datasets/README.md)). Each one was investigated three times by the
agent team and three times by the single agent, because the AI gives slightly different
answers each time: 60 investigations in all. Both used the same AI model (Nemotron 3
Ultra), the same tools, the same budget and the same rules for deciding.

A run counts as **right** if it names the true cause (the right service and the right kind
of problem), or, on T10, if it says "we can't tell", because there the evidence really
can't tell.

## The main numbers

| | Agent team | Single agent |
|---|---|---|
| Right | 14 of 30 (47%) | 14 of 30 (47%) |
| Wrong answer given as the conclusion | 4 of 30 (13%) | 13 of 30 (43%) |
| Wrong, and confident about it | 2 of 30 (7%) | 8 of 30 (27%) |
| Said "we can't tell" when it could have answered | 12 of 27 (44%) | 3 of 27 (11%) |
| Right when it did give a conclusion | 13 of 17 (76%) | 14 of 27 (52%) |
| True cause ranked first | 17 of 27 (63%) | 14 of 27 (52%) |
| True cause in its top three | 21 of 27 (78%) | 15 of 27 (56%) |
| AI calls per investigation | 48 | 13 |
| Time per investigation (median) | 14 minutes | 4.5 minutes |

Every table, for every incident, is in [results/test/summary.md](../results/test/summary.md).

## What it means

**Both are right equally often, but they fail differently.** The single agent nearly
always commits to an answer, and almost half the time it is the wrong one. The team holds
back much more: when it isn't sure enough, it says "we can't tell". So when the team does
give a conclusion, it can be trusted far more: three times in four, against one in two.

**The team often finds the cause but doesn't commit to it.** It ranks the true cause first
more often than the single agent does. In 4 of the runs where it said "we can't tell", the
true cause was already at the top of its list; the critic's objections or the confidence
rules held it back. The easy control incident (T01) shows this most: the team concluded
correctly once in three runs, the single agent every time.

**Where both fail.** Neither system got T03 (a cache failure overloads a database, which
looks guilty), T06 (network trouble in one data centre that barely shows in the overall
numbers) or T07 (a traffic jump at market open, with harmless warnings from a recent
update) right in any run. On those the team said "we can't tell"; the single agent mostly
named the wrong cause.

**The cost.** The team makes about three and a half times as many AI calls and takes about
three times as long. Most of that time is spent waiting for answers from the free AI
service.

## How far to trust this

- Ten incidents we wrote ourselves, three runs each, give a direction, not proof. A
  difference of one or two runs can be chance.
- Only one AI model was tested.
- The same people built the system and wrote the incidents, even though T01 to T10 were
  kept aside.

## Checking it yourself

Every run's report, step-by-step record and AI replies are in [results/test](../results/test).
`uv run investigator eval report results/test` recalculates every number above from those
files, and `uv run investigator ui` plays any of the runs back.
