# incident-investigator

When an online service breaks, an engineer has to work out why, often under pressure and
with misleading clues. This project gets a team of six AI agents to do that investigation:
they look through the service's logs, measurements and recent changes, argue about possible
causes, and write a report that shows the evidence for each conclusion. When the evidence
isn't enough, the report says so instead of guessing.

The agents work on a pretend online brokerage, with problems we created on purpose and
clues that point the wrong way. Their results are compared with a single AI agent doing the
same job alone.

## Results

Ten incidents kept aside while building, three runs each:

| | Agent team | Single agent |
|---|---|---|
| Right | 47% | 47% |
| Wrong answer given as the conclusion | 13% | 43% |
| Right when it gave a conclusion | 76% | 52% |
| Said "we can't tell" when it could have answered | 44% | 11% |
| AI calls per investigation | 48 | 13 |

The team is right as often as a single agent, but it rarely commits to a wrong
answer. The price is that it holds back more often, and costs more. The full comparison is
in [docs/evaluation.md](docs/evaluation.md).

## Try it

You need Python 3.12 or newer and [uv](https://docs.astral.sh/uv/). Nothing costs money.

```sh
uv sync --extra ui
uv run investigator ui     # watch recorded investigations in your browser
make check                 # run the automated tests
```

To run new investigations you need a free key from NVIDIA; see
[docs/usage.md](docs/usage.md).

## How it works

- Each agent has one job: plan, read the logs and measurements, check what changed, suggest
  causes, challenge those causes, or write the report.
- They share one notebook. Anything they write must point to real evidence they found, or
  it is thrown out.
- A critic agent questions every suggested cause and asks for more evidence, which starts
  another round of investigation.
- Simple fixed rules, not the AI, decide whether the evidence is strong enough for a
  conclusion.
- Every investigation is recorded, so it can be watched again later without the AI.

[docs/architecture.md](docs/architecture.md) explains this in more detail.

## More

- [How to use it](docs/usage.md)
- [Results in detail](docs/evaluation.md)
- [Technical note](docs/technical-note.md): the main choices and their limits
- [The test incidents](datasets/README.md)
- [Why we made each design choice](docs/decisions/)
