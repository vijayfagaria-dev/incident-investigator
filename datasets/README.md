# The test incidents

The agents investigate a pretend online brokerage with 13 parts: the website's front door,
login, orders, portfolios, market prices, payments, notifications, two databases, a cache,
a message queue, and two outside companies (a price feed and a bank).

Each incident is a small folder of three files:

| File | What it holds | Who reads it |
|---|---|---|
| `incident.yaml` | The problem as a person on call would report it | The agents |
| `scenario.yaml` | What really happened, used to create realistic logs and measurements | Only the data generator |
| `expected.yaml` | The right answer | Only the scoring |

Automated tests make sure the agents can never read the right answer, and that no incident
report gives it away.

Incidents D1 to D4 were used while building the system. T01 to T10 were kept aside, and
only they count in the results.

| Incident | The trap |
|---|---|
| T01 | None: a new feature has a bug. This is the easy one. |
| T02 | An outside price feed slows down; a software update eight minutes *later* looks guilty. |
| T03 | A cache fails and overloads a database, which looks like the cause. |
| T04 | A feature switch was turned on, on a day with no software updates. |
| T05 | A security certificate expires; a settings change just before looks guilty; some logs are missing. |
| T06 | One data centre has network trouble, which barely shows in the overall numbers. |
| T07 | The market opens and traffic jumps; a recent update logs harmless warnings. |
| T08 | A database password is changed; health checks still say everything is fine. |
| T09 | A memory leak looks just like an old incident that was blamed on traffic. |
| T10 | Most of the evidence is missing. The right answer is "we can't tell". |

`history/` holds 15 reports of past incidents the agents can search. Some deliberately
point the wrong way.

## Adding an incident

Copy one of the incident folders and edit its three files. `scenario.yaml` describes the
changes that happened and how the logs and measurements reacted:

```yaml
seed: 2002                      # the same seed always gives the same data
window: {start: 2026-10-20T08:00:00Z, end: 2026-10-20T11:00:00Z}

changes:                        # software updates, settings, feature switches, and so on
  - id: chg:2290
    ts: 2026-10-20T10:02:05Z
    service: payments-service
    kind: config
    actor: config-bot
    summary: "Apply connection tuning from PR #4821"
    details: {db.pool.max_size: "50 -> 5"}

effects:
  # Move a measurement to a value (`to`) or a multiple of normal (`factor`).
  - {kind: metric, service: payments-service, metric: db_pool_in_use,
     start: 2026-10-20T10:03:00Z, to: 5, noise: 0}
  # Add a log message, at a rate per minute or a fixed number of times.
  - kind: log
    service: payments-service
    level: ERROR
    template: "Connection is not available, request timed out after {ms}ms"
    start: 2026-10-20T10:04:00Z
    rate_per_min: 34
    fields: {ms: {uniform: [3000, 3006]}}

faults:                         # make the agents' tools misbehave
  - {tool: query_metrics, kind: timeout, invocations: [1, 2]}      # first two calls time out
  - {tool: get_change_history, kind: unavailable}                  # down for the whole incident
  - {tool: query_logs, kind: partial, missing_az: az-b}            # one data centre's logs lost
```

Then run `uv run investigator data render <incident>` to check the data tells the story you
meant, and update the incident's fingerprint in `tests/dataset/test_incidents.py`.
