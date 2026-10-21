# T08: Deposits and checkout failing overnight

**Outcome:** conclusive. Root cause: `certificate_or_credential` on **payments-service**, triggered by `chg:2581`

## Summary

Deposits and checkout began failing around 02:00 UTC when the postgres‑payments database password for user payments_app was rotated (chg:2581). Payments‑service continued using the old credential, producing thousands of “password authentication failed” errors, draining the DB connection pool and causing 500 responses while health checks stayed green. The investigation concluded this stale‑credential issue (HYP‑1) is the root cause with high confidence. Remaining unknowns are whether the service health‑check exercises the DB connection, whether any pods reloaded the new secret automatically, and the exact behaviour of the bank‑rails dependency during the window.

## Hypotheses

### 1. `certificate_or_credential` on **payments-service**, triggered by `chg:2581` (HYP-1)

Confidence 0.92 (high), critic: accept. The secret rotation for the postgres-payments database user `payments_app` at 02:00:05 UTC (chg:2581) was not automatically reloaded by payments-service. The service continued to use the old password (v31) while the database now expected the new password (v32). Every DB connection attempt therefore failed with “password authentication failed”, causing the pool to empty, the error rate to spike, and the checkout/deposit endpoints to return 500.

**Supporting:**
- secret_rotation on postgres-payments at 02:00:05 UTC by vault-rotator: Rotate database password for payments_app (secret: db/postgres-payments/payments_app, version: v31 -> v32) (`chg:2581`)
- payments‑service logs show 788 “password authentication failed for user payments_app” errors starting 2026‑10‑13T02:02:05Z and continuing to 02:34:53Z. (`log:07bf0979f12c`)
- postgres‑payments logs show 865 identical “FATAL: password authentication failed for user payments_app” errors from 2026‑10‑13T02:02:00Z to 02:34:57Z. (`log:94d1aef944ce`)
- payments‑service error_rate metric rises from 0.002 (baseline) at 01:15 UTC to 0.327 at 02:35 UTC (max 0.406). (`metric:payments-service/error_rate`)
- payments‑service db_pool_in_use falls from 5.28 connections at 01:15 UTC to 2.0 at 02:35 UTC (baseline 5.75). (`metric:payments-service/db_pool_in_use`)
- postgres‑payments active_connections drops from 18.96 at 01:15 UTC to 5.75 at 02:35 UTC (baseline 21.44). (`metric:postgres-payments/active_connections`)
- postgres-payments secret for payments_app rotated from version v31 to v32 at 2026-10-13T02:00:05Z (chg:2581). (`chg:2581`)
- Failure rate began rising shortly after 02:00 UTC, coincident with the postgres-payments secret rotation (chg:2581); the timeout increase (chg:2578) occurred ~22 min earlier and would increase, not decrease, the effective timeout budget. (`chg:2578`, `chg:2581`)
**Assumptions:**
- ASM-1: payments‑service does not automatically pick up a rotated Vault secret; a reload/restart or SIGHUP is required.
- ASM-2: The /healthz endpoint of payments‑service only checks process liveness, not DB connectivity.
**Objections:**
- [minor] gap_unaddressed: Health‑check implementation for payments-service is unknown (GAP-5); the hypothesis assumes checks do not exercise the DB connection. This does not block acceptance but should be verified.
- [minor] gap_unaddressed: No record of a payments-service deploy or config reload after the secret rotation (GAP-6); the hypothesis assumes the old credential persisted. This gap is minor because the observed auth failures already demonstrate the stale credential.

### 2. `dependency_degradation` on **bank-rails** (HYP-2)

Confidence 0.13 (low), critic: reject. An unobserved provider‑side change or maintenance on bank-rails between 01:30‑02:35 UTC increased latency or error rate enough that payments-service calls exceeded the (now 5000 ms) client timeout, resulting in 500 responses for checkout/deposit.

**Supporting:**
- config on payments-service at 01:38:20 UTC by config-bot: Raise bank-rails client timeout (bank_rails.timeout_ms: 4000 -> 5000) (`chg:2578`)
- payments-service config changed bank_rails.timeout_ms from 4000 to 5000 ms at 2026-10-13T01:38:20Z (chg:2578). (`chg:2578`)
- bank‑rails latency p99 rises modestly from 422 ms at 01:15 UTC to 489 ms at 02:35 UTC (baseline 412 ms); no error logs or error‑rate metric are present. (`metric:payments-service/bank_rails_latency_p99_ms`)
**Contradicting:**
- bank‑rails latency p99 rises modestly from 422 ms at 01:15 UTC to 489 ms at 02:35 UTC (baseline 412 ms); no error logs or error‑rate metric are present. (`metric:payments-service/bank_rails_latency_p99_ms`)
- payments‑service logs show 788 “password authentication failed for user payments_app” errors starting 2026‑10‑13T02:02:05Z and continuing to 02:34:53Z. (`log:07bf0979f12c`)
- postgres‑payments logs show 865 identical “FATAL: password authentication failed for user payments_app” errors from 2026‑10‑13T02:02:00Z to 02:34:57Z. (`log:94d1aef944ce`)
- payments‑service error_rate metric rises from 0.002 (baseline) at 01:15 UTC to 0.327 at 02:35 UTC (max 0.406). (`metric:payments-service/error_rate`)
- payments‑service db_pool_in_use falls from 5.28 connections at 01:15 UTC to 2.0 at 02:35 UTC (baseline 5.75). (`metric:payments-service/db_pool_in_use`)
- postgres‑payments active_connections drops from 18.96 at 01:15 UTC to 5.75 at 02:35 UTC (baseline 21.44). (`metric:postgres-payments/active_connections`)
- Failure rate began rising shortly after 02:00 UTC, coincident with the postgres-payments secret rotation (chg:2581); the timeout increase (chg:2578) occurred ~22 min earlier and would increase, not decrease, the effective timeout budget. (`chg:2578`, `chg:2581`)
**Assumptions:**
- ASM-3: bank‑rails did not emit any error‑rate or latency spike that could cause downstream 500s.
**Objections:**
- [blocking] ignores_contradiction: The hypothesis ignores the concrete DB auth‑failure logs (OBS-3, OBS-4) and the correlated pool‑drain metrics (OBS-5,6,7) that directly explain the 500 errors.

### 3. `resource_exhaustion` on **payments-service** (HYP-3)

Confidence 0.02 (low), critic: reject. A burst of retries caused the DB connection pool to saturate, leading to request failures.

**Contradicting:**
- payments‑service db_pool_in_use falls from 5.28 connections at 01:15 UTC to 2.0 at 02:35 UTC (baseline 5.75). (`metric:payments-service/db_pool_in_use`)
- postgres‑payments active_connections drops from 18.96 at 01:15 UTC to 5.75 at 02:35 UTC (baseline 21.44). (`metric:postgres-payments/active_connections`)
**Objections:**
- [blocking] unsupported_claim: cites no observations
- [blocking] unsupported_claim: The hypothesis cites no observations; the only pool‑related metrics (OBS-6, OBS-7) show the opposite of the predicted saturation.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Perform a rolling restart (or send SIGHUP) of all payments‑service pods to force reload of the rotated database password. | The service is still using the old password (v31); a restart will load the new secret (v32) and stop auth failures immediately. (HYP-1) |
| soon | fix | Implement automatic secret reloading for the postgres‑payments credential (e.g., Vault agent sidecar, config‑watcher, or SIGHUP handler) so future rotations are picked up without manual restarts. | The root cause was the lack of automatic credential refresh; automating it removes the failure mode. (HYP-1) |
| later | prevent | Add a health‑check endpoint that performs a lightweight DB query (or connection test) so that stale credentials cause the health check to fail and trigger alerts. | Current health checks stay green because they do not exercise the DB connection (GAP‑5); a DB‑aware check would surface the problem early. (HYP-1) |
| later | prevent | Create an alert on database authentication‑failure log rate or on a sudden drop in db_pool_in_use / active_connections metrics. | Observed auth‑failure spikes (OBS‑3, OBS‑4) and pool drain (OBS‑6, OBS‑7) are clear leading indicators. (HYP-1) |
| later | investigate | Verify the payments‑service health‑check implementation to confirm it does not test the DB connection (GAP‑5). | Critic flagged this as a minor gap; confirming will validate the assumption that health checks stay green despite DB auth failures. (HYP-1) |
| later | investigate | Confirm whether any payments‑service pods performed a config reload or deploy after the secret rotation (GAP‑6). | Partial rollout could leave some instances on the old timeout or credential; ruling this out solidifies the conclusion. (HYP-1) |
| later | investigate | Obtain bank‑rails error‑rate, latency, and log data for 01:30‑02:35 UTC (GAP‑1, GAP‑8, GAP‑9) and end‑to‑end traces (GAP‑7) to fully exclude a provider‑side issue (HYP‑2). | Although HYP‑2 was rejected, missing bank‑rails observability leaves a small residual uncertainty. (HYP-2) |

## Evidence gaps

- **query_metrics** (bank-rails service metrics (error_rate, request_latency, HTTP 5xx)): bank‑rails returned no metric series; cannot directly correlate its error‑rate with payments‑service 500s.
- **query_logs** (payments‑service logs filtered to /v1/checkout and /v1/deposits 500 responses): Pattern search only surfaced generic 504 on withdrawals; need explicit checkout/deposit error logs to tie 500s to DB failures.
- **get_change_history** (bank-rails config/feature-flag/infra changes 01:15‑02:35 UTC): No change records for bank-rails were returned; a silent provider‑side change could affect latency.
- **get_change_history** (Infra changes (connection‑pool settings, DNS, TLS certs, network policies) for edge-gateway, payments-service, bank-rails, postgres-payments, kafka): Such changes are not captured by the config/secret‑rotation kinds queried.
- **get_service_dependencies** (Health‑check implementation details for payments-service): Dependency view does not indicate whether health checks hit downstream DB or bank-rails calls.
- **get_change_history** (Deployment or config‑reload events for payments-service after chg:2578): No deploy record shows the timeout config rollout; partial rollout could leave some pods on the old 4000 ms value.
- **observability** (End‑to‑end request traces/metrics for edge-gateway → payments-service → bank-rails/postgres-payments at failure onset): Needed to pinpoint whether failures originate at DB auth or bank-rails latency.
- **query_logs** (bank‑rails logs (WARN+ and INFO) 01:30‑02:35 UTC): Returned zero matched records; logs may not be ingested or service may not emit them.
- **query_metrics** (bank‑rails metric summary 01:30‑02:35 UTC): Returned empty series list; metrics may be missing or not exported.

## Open questions

- Does the payments‑service health‑check perform a DB connection test? (GAP‑5)
- Did any payments‑service pods automatically reload the rotated secret or receive a config reload after 02:00 UTC? (GAP‑6)
- What were the bank‑rails error rates, latencies, and log entries during the incident window? (GAP‑1, GAP‑8, GAP‑9)
- Are there end‑to‑end request traces showing the failure point at DB authentication versus bank‑rails latency? (GAP‑7)
- Were there any infrastructure changes (network policies, DNS, TLS certs, pool settings) not captured in the change census that could affect connectivity? (GAP‑4)

## How the investigation ran

Stopped because the critic accepted HYP-1, after 1 round(s): 19 model calls, 12 tool calls, 72,370 tokens, 708 s.
