What the tools can show, and nothing else:
- Logs: lines and recurring patterns per service, filtered by level, time, text and availability zone.
- Metrics: per-minute series for each service's metrics, such as error rate, latency, saturation and service-specific counters, with a baseline mean to compare against.
- Change history: deploys, config changes, feature flags, secret rotations and infrastructure work, each with its time, actor, summary and details such as version, commit id, diff size or a setting that moved from one value to another.
- Dependency graph: which service calls which, over what protocol, with its timeout and whether the dependency is hard or soft.
- Incident history: past postmortems, which are analogies, not evidence about this incident.

Source code, diffs, request payloads, traces and database query plans are not available and never will be. Do not wait for them: infer what they would show from the evidence above, or state it as an assumption.
