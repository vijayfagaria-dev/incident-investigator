# T02: Portfolio pages slow and failing

**Outcome:** conclusive. Root cause: `dependency_degradation` on **market-data-service**

## Summary

Portfolio and positions pages became slow and returned 5xx errors starting around 14:41 UTC, and some order placements were rejected. The investigation concluded (conclusive) that the primary cause was a degradation in the external quotes‑vendor that caused market‑data‑service latency to jump ~6× and its error rate ~10× at 14:41 UTC; aggressive retries pushed the circuit‑breaker into half‑open at 14:47 UTC, and downstream callers (portfolio‑service, orders‑service) began receiving gRPC DEADLINE_EXCEEDED, which in turn made edge‑gateway time out after its 3 s hard limit. Confidence in this hypothesis (HYP‑1) is 0.65. The exact minute when portfolio‑service latency began to rise remains unknown because per‑minute latency series were not captured (GAP‑4, GAP‑12).

## Hypotheses

### 1. `dependency_degradation` on **market-data-service** (HYP-1)

Confidence 0.65 (medium), critic: accept. The external quotes‑vendor began timing out (800 ms) at ~14:41 UTC. market‑data‑service retried aggressively, its circuit‑breaker entered half‑open at 14:47, and downstream callers (portfolio‑service, orders‑service) received gRPC DEADLINE_EXCEEDED. Edge‑gateway then timed out waiting for portfolio‑service, producing 5xx errors and order rejections.

**Supporting:**
- market-data-service reports quotes‑vendor request timeouts (800 ms) from 14:41:01 UTC (1,072 occurrences) and enters half‑open circuit‑breaker state at 14:47:02 UTC (78 occurrences). (`log:785c94c54006`, `log:a9fa5c6b6926`)
- market-data-service began logging quotes‑vendor request timeouts at 14:41:01 UTC (WARN, 1072 occurrences). (`log:785c94c54006`)
- market-data-service circuit to quotes‑vendor went half‑open at 14:47:02 UTC (WARN, 78 occurrences). (`log:a9fa5c6b6926`)
- portfolio-service started logging gRPC DEADLINE_EXCEEDED to market-data-service (GetQuotes) at 14:42:01 UTC (ERROR, 679 occurrences). (`log:3096c4afe74b`)
- orders-service begins rejecting orders with “market-data-service DEADLINE_EXCEEDED” at 14:42:01 UTC (178 occurrences up to 15:04:53). (`log:6f37ccdbcbc1`)
- edge-gateway logs upstream portfolio‑service timeouts (3 s) starting at 14:43:01 UTC (300 occurrences up to 15:04:55). (`log:5eba6c3c8e7a`)
- portfolio-service p99 latency baseline 415 ms; first recorded point at 14:20 was 412 ms, rose sharply and last point at 15:05 was 3093 ms (metric summary). (`metric:portfolio-service/latency_p99_ms`)
- portfolio-service error_rate baseline 0.22 %; first point 0.25 % at 14:20, last point 5.23 % at 15:05 (metric summary). (`metric:portfolio-service/error_rate`)
- market-data-service latency_p99_ms baseline mean 253 ms; at 14:40 UTC it was 463 ms and at 14:42 UTC jumped to 1,644 ms (≈6.5× baseline). (`metric:market-data-service/latency_p99_ms`)
- latency stayed high (1.7–2.1 s) for the rest of the window, last recorded point 2,282 ms at 15:04 UTC. (`metric:market-data-service/latency_p99_ms`)
- market-data-service error_rate baseline mean 0.197 %; at 14:40 UTC it was 0.305 % and at 14:42 UTC rose to 1.90 % (≈10× baseline). (`metric:market-data-service/error_rate`)
- error_rate remained elevated (2–4 %) through 15:04 UTC, last point 3.64 % at 15:04 UTC. (`metric:market-data-service/error_rate`)
- Logs indicate the circuit‑breaker to the quotes‑vendor entered half‑open state at 14:47:02 UTC (78 occurrences). (`log:a9fa5c6b6926`)
**Assumptions:**
- ASM-5: The latency spike originates in the external quotes‑vendor, not in a market‑data‑service code change.
- ASM-6: market‑data‑service’s circuit‑breaker moves to half‑open at ~14:47 as a direct consequence of the vendor time‑outs.
- ASM-7: Change census shows no deploy/config/flag on market‑data‑service in the incident window.
**Objections:**
- [minor] gap_unaddressed: Per‑minute portfolio‑service latency_p99_ms and error_rate series were not returned (GAP‑4, GAP‑12). Having the minute‑level series would pin the exact onset minute and fully close the timing loop.

### 2. `code_regression` on **portfolio-service**, triggered by `chg:2512` (HYP-2)

Confidence 0.15 (low), critic: reject. The v5.4.0 deploy added a sector‑breakdown feature. The new code path introduces additional work (extra query / cache miss) that increases latency and produces “sector‑mapping missing” warnings, pushing portfolio‑service p99 past the edge‑gateway 3 s timeout and raising error rates.

**Supporting:**
- deploy on portfolio-service at 14:48:30 UTC by ci/deploy-bot: portfolio-service v5.4.0: add sector breakdown to performance page (version: 5.4.0, previous_version: 5.3.2, commit: 3c7d0aa, diff: +410 / -88) (`chg:2512`)
- portfolio-service deploy v5.4.0 occurred at 14:48:30 UTC (change census). (`chg:2512`)
- portfolio-service was deployed to v5.4.0 at 2026-10-06T14:48:30Z (commit 3c7d0aa, +410/-88). (`chg:2512`)
- portfolio-service began emitting sector‑mapping missing warnings at 14:49:05 UTC (WARN, 161 occurrences), after the deploy. (`log:e481388daa5a`)
**Contradicting:**
- portfolio-service p99 latency baseline 415 ms; first recorded point at 14:20 was 412 ms, rose sharply and last point at 15:05 was 3093 ms (metric summary). (`metric:portfolio-service/latency_p99_ms`)
- portfolio-service error_rate baseline 0.22 %; first point 0.25 % at 14:20, last point 5.23 % at 15:05 (metric summary). (`metric:portfolio-service/error_rate`)
- market-data-service reports quotes‑vendor request timeouts (800 ms) from 14:41:01 UTC (1,072 occurrences) and enters half‑open circuit‑breaker state at 14:47:02 UTC (78 occurrences). (`log:785c94c54006`, `log:a9fa5c6b6926`)
- market-data-service began logging quotes‑vendor request timeouts at 14:41:01 UTC (WARN, 1072 occurrences). (`log:785c94c54006`)
- market-data-service circuit to quotes‑vendor went half‑open at 14:47:02 UTC (WARN, 78 occurrences). (`log:a9fa5c6b6926`)
- portfolio-service started logging gRPC DEADLINE_EXCEEDED to market-data-service (GetQuotes) at 14:42:01 UTC (ERROR, 679 occurrences). (`log:3096c4afe74b`)
- orders-service begins rejecting orders with “market-data-service DEADLINE_EXCEEDED” at 14:42:01 UTC (178 occurrences up to 15:04:53). (`log:6f37ccdbcbc1`)
- edge-gateway logs upstream portfolio‑service timeouts (3 s) starting at 14:43:01 UTC (300 occurrences up to 15:04:55). (`log:5eba6c3c8e7a`)
**Assumptions:**
- ASM-8: The new sector‑breakdown code adds measurable work (extra DB query / cache miss) that can push latency past the 3 s gateway timeout.
**Objections:**
- [blocking] temporal_violation: The deploy (14:48:30) occurs after the first downstream symptoms (market‑data latency jump at 14:41, portfolio DEADLINE_EXCEEDED at 14:42, edge‑gateway timeouts at 14:43). Cause cannot follow effect.
- [blocking] ignores_contradiction: Observations OBS‑4, OBS‑6, OBS‑7, OBS‑8, OBS‑22‑25 show a clear upstream degradation in market‑data‑service that precedes the portfolio‑service deploy. HYP‑2 does not account for this evidence.

### 3. `data_issue` on **postgres-orders** (HYP-3)

Confidence 0.07 (low), critic: reject. A hidden schema migration (e.g., missing index on positions_history) makes the portfolio performance query run sequential scans, inflating latency for the /v1/portfolio path and causing downstream timeouts.

**Contradicting:**
- Change history for 2026-10-06 14:20–15:05 shows no deploy, config, feature‑flag, secret‑rotation, or infra changes for market-data-service, postgres-orders, edge-gateway, orders-service, or redis-cache. (`chg:2512`)
- portfolio-service p99 latency baseline 415 ms; first recorded point at 14:20 was 412 ms, rose sharply and last point at 15:05 was 3093 ms (metric summary). (`metric:portfolio-service/latency_p99_ms`)
- portfolio-service error_rate baseline 0.22 %; first point 0.25 % at 14:20, last point 5.23 % at 15:05 (metric summary). (`metric:portfolio-service/error_rate`)
**Assumptions:**
- ASM-3: Postgres‑orders metrics are truly normal (CPU, connections, query latency).
**Objections:**
- [blocking] unsupported_claim: cites no observations
- [blocking] unsupported_claim: The hypothesis cites no observations; all available evidence (change history, metrics, logs) points elsewhere.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Add a short‑circuit fallback in market‑data‑service to serve cached/stale quotes when the quotes‑vendor times out, and increase the portfolio‑service gRPC deadline slightly above the vendor timeout. | Immediately reduces downstream DEADLINE_EXCEEDED errors while the vendor issue is resolved. (HYP-1) |
| soon | fix | Retune market‑data‑service retry policy (exponential back‑off with jitter) and adjust circuit‑breaker thresholds to avoid rapid half‑open transitions under sustained vendor latency. | Removes the aggressive retry loop that amplified the vendor degradation into downstream timeouts. (HYP-1) |
| later | prevent | Deploy alerting on market‑data‑service latency_p99_ms and error_rate spikes (e.g., >3× baseline) and expose circuit‑breaker state as a metric. | Gives early warning before downstream services are impacted. (HYP-1) |
| later | investigate | Retrieve per‑minute portfolio‑service latency_p99_ms and error_rate series to pinpoint the exact onset minute and verify the timing loop. | Closes the remaining timing gap (GAP‑4, GAP‑12) and confirms the causal chain. (HYP-1) |
| later | investigate | Query edge‑gateway request‑level logs for /v1/portfolio to capture detailed timeout components (network, gateway, downstream). | Validates that edge‑gateway timeouts are purely downstream and not contributed by gateway processing (GAP‑5, GAP‑13). (HYP-1) |
| later | investigate | Confirm no hidden schema migrations or DB‑level changes occurred on postgres‑orders during the window. | Rules out the rejected HYP‑3 data‑issue hypothesis (GAP‑6). (HYP-3) |

## Evidence gaps

- **query_metrics** (orders-service, market-data-service, edge-gateway, postgres-orders latency, error rate, circuit‑breaker state, connection‑pool saturation): Tool step budget exhausted; metrics needed to quantify onset and magnitude of latency spikes and to confirm circuit‑breaker transitions.
- **query_metrics** (edge-gateway latency, error_rate, timeout counters for /v1/portfolio): Step budget exhausted before querying edge-gateway metrics.
- **query_metrics** (postgres-orders CPU, connections, query latency, error_rate): Step budget exhausted before querying postgres-orders metrics.
- **query_metrics** (portfolio-service per‑minute latency_p99_ms and error_rate series): Only summary returned; need high‑resolution series to pin onset minute.
- **query_logs** (edge-gateway WARN/ERROR logs for portfolio path): Step budget exhausted before querying edge-gateway logs.
- **get_change_history** (schema migrations or DB‑level changes for postgres-orders): The change‑history endpoint does not surface schema migrations; they may have been applied without a recorded change.
- **get_change_history** (feature‑flag or config flips for any of the six services): The tool returned no config/flag events, but the audit source might be incomplete.
- **get_change_history** (infrastructure events (node‑pool scaling, network‑policy changes)): Infrastructure work is not captured as a change type in the current census.
- **get_service_dependencies** (deeper transitive dependencies beyond depth 2 (e.g., market-data-service → quotes‑vendor)): Only depth 2 was requested; further upstream calls could affect latency but were not examined.
- **query_metrics** (circuit‑breaker state (open/half‑open/closed) for market-data-service): No metric named circuit_breaker_state or similar is exposed for market-data-service; only latency, error_rate, vendor_* metrics are available.
- **query_metrics** (edge‑gateway upstream latency breakdown (network / gateway / downstream) per minute for /v1/portfolio): Metric not available in the current catalog; only aggregate latency_p99_ms is exposed.
- **query_metrics** (portfolio‑service per‑minute latency_p99_ms and error_rate): Only summary baseline values were returned; minute‑level series not fetched.
- **query_logs** (edge‑gateway request‑level latency components (e.g., X‑Request‑Time headers) for /v1/portfolio): Log patterns captured only timeout warnings, not detailed timing fields.

## Open questions

- At what exact minute did portfolio‑service latency_p99_ms begin to rise sharply?
- What caused the quotes‑vendor to start timing out at 14:41 UTC?
- Are there any unrecorded configuration or feature‑flag changes that could have affected market‑data‑service behavior?
- Can circuit‑breaker state be exposed as a metric for future observability?
- Did any infrastructure events (node‑pool scaling, network policy changes) coincide with the vendor degradation?

## How the investigation ran

Stopped because the critic accepted HYP-1, after 2 round(s): 32 model calls, 16 tool calls, 151,299 tokens, 1082 s.
