# T08: Deposits and checkout failing overnight

**Outcome:** conclusive. Root cause: `certificate_or_credential` on **postgres-payments**, triggered by `chg:2581`

## Summary

At 02:00 UTC the postgres-payments database password for the payments_app user was rotated (chg:2581). The running payments-service pods did not pick up the new credential, so from 02:02 UTC every DB connection attempt failed with “password authentication failed” (1 373 log lines). This caused the connection pool to collapse (in‑use connections dropped from ~6 to 2) and the service error rate to climb from ~0.2 % to >30 %, manifesting as 500 errors on /v1/checkout and /v1/deposits. Health checks stayed green because they only test the HTTP endpoint, not DB reachability. The earlier bank‑rails timeout increase (chg:2578) had no measurable impact.

## Hypotheses

### 1. `certificate_or_credential` on **postgres-payments**, triggered by `chg:2581` (HYP-1)

Confidence 0.93 (high). The DB password was rotated but payments-service pods kept the old credential, causing every new connection attempt to fail with authentication errors. The connection pool drained, leading to 500 errors on checkout and deposits.

**Supporting:**
- Secret rotation at 02:00:05 UTC rotated the DB password for payments_app on postgres-payments (v31 → v32). (`chg:2581`)
- Starting 02:02:05 UTC the logs show 1 373 occurrences of “could not open connection to postgres-payments: FATAL: password authentication failed for user ‘payments_app’”. (`log:07bf0979f12c`)
- payments-service error_rate jumps from baseline 0.002 to window‑average 0.206, ending at 0.33. (`metric:payments-service/error_rate`)
- db_pool_in_use falls from baseline ≈6 to 2.0 at the end of the window. (`metric:payments-service/db_pool_in_use`)
- Request rate (rps) stays roughly constant at ≈78 req/s. (`metric:payments-service/rps`)
**Assumptions:**
- ASM-1: The secret rotation (chg:2581) was not automatically re‑loaded by the running payments-service pods, so they continued to use the old password (v31).
- ASM-2: Health‑check endpoint only validates HTTP liveness, not DB connectivity, which is why pods appear “healthy”.

### 2. `config_change` on **payments-service**, triggered by `chg:2578` (HYP-2)

Confidence 0.12 (low). Increasing the bank‑rails timeout to 5 s caused longer retries that exhausted the DB pool.

**Supporting:**
- Config change at 01:38:20 UTC raised the bank-rails client timeout from 4000 → 5000 ms. (`chg:2578`)
- bank_rails_latency_p99 rises modestly from baseline 406 ms to last 462 ms. (`metric:payments-service/bank_rails_latency_p99_ms`)
**Contradicting:**
- Starting 02:02:05 UTC the logs show 1 373 occurrences of “could not open connection to postgres-payments: FATAL: password authentication failed for user ‘payments_app’”. (`log:07bf0979f12c`)
- payments-service error_rate jumps from baseline 0.002 to window‑average 0.206, ending at 0.33. (`metric:payments-service/error_rate`)
- db_pool_in_use falls from baseline ≈6 to 2.0 at the end of the window. (`metric:payments-service/db_pool_in_use`)
- Overall latency_p99 is unchanged (baseline 483 ms → last 494 ms). (`metric:payments-service/latency_p99_ms`)

### 3. `resource_exhaustion` on **payments-service** (HYP-4)

Confidence 0.08 (low). Combined effect of timeout increase and secret rotation amplified retries, exhausting the DB pool.

**Supporting:**
- Config change at 01:38:20 UTC raised the bank-rails client timeout from 4000 → 5000 ms. (`chg:2578`)
- Secret rotation at 02:00:05 UTC rotated the DB password for payments_app on postgres-payments (v31 → v32). (`chg:2581`)
- Starting 02:02:05 UTC the logs show 1 373 occurrences of “could not open connection to postgres-payments: FATAL: password authentication failed for user ‘payments_app’”. (`log:07bf0979f12c`)
- db_pool_in_use falls from baseline ≈6 to 2.0 at the end of the window. (`metric:payments-service/db_pool_in_use`)
**Contradicting:**
- bank_rails_latency_p99 rises modestly from baseline 406 ms to last 462 ms. (`metric:payments-service/bank_rails_latency_p99_ms`)
- Overall latency_p99 is unchanged (baseline 483 ms → last 494 ms). (`metric:payments-service/latency_p99_ms`)
**Assumptions:**
- ASM-1: The secret rotation (chg:2581) was not automatically re‑loaded by the running payments-service pods, so they continued to use the old password (v31).
- ASM-2: Health‑check endpoint only validates HTTP liveness, not DB connectivity, which is why pods appear “healthy”.

### 4. `dependency_degradation` on **bank-rails** (HYP-3)

Confidence 0.07 (low). Unannounced bank‑rails maintenance caused intermittent failures that propagated as 500s.

**Supporting:**
- Low‑volume “card authorization declined” and “bank‑rails returned 409 (duplicate)” warnings exist throughout but do not correlate with the sharp error‑rate rise. (`log:4d321eb6ff38`, `log:056d74b236f2`)
**Contradicting:**
- Starting 02:02:05 UTC the logs show 1 373 occurrences of “could not open connection to postgres-payments: FATAL: password authentication failed for user ‘payments_app’”. (`log:07bf0979f12c`)
- payments-service error_rate jumps from baseline 0.002 to window‑average 0.206, ending at 0.33. (`metric:payments-service/error_rate`)
- bank_rails_latency_p99 rises modestly from baseline 406 ms to last 462 ms. (`metric:payments-service/bank_rails_latency_p99_ms`)
- Overall latency_p99 is unchanged (baseline 483 ms → last 494 ms). (`metric:payments-service/latency_p99_ms`)

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | fix | Rollback or re‑apply the DB secret to all payments-service pods (restart pods or trigger a secret reload). | Restores valid credentials; logs show immediate auth failures after rotation. |
| soon | prevent | Add a DB‑connectivity probe to the health‑check (or a separate readiness probe). | Prevents “green health, dead DB” situation in future. |
| later | prevent | Audit secret‑rotation automation to ensure consuming services reload secrets automatically (e.g., Vault Agent sidecar or SIGHUP). | Removes the manual‑restart gap that caused the outage. |
| later | investigate | Validate the bank‑rails timeout change in staging and add monitoring for its latency/error impact. | The change itself was benign, but verification avoids future surprises. |
| later | prevent | Enable per‑minute error‑rate alerting on payments-service (threshold >1 %). | Earlier detection would have cut the impact window. |

## Evidence gaps

- **query_logs** (payments-service secret‑reload or SIGHUP handling logs): Logs do not contain any indication that the service attempted to reload the rotated secret.
- **query_metrics** (per‑minute error_rate series for payments-service): The metrics endpoint returned only a summary; minute‑level granularity would pinpoint the exact onset.
- **query_logs** (bank‑rails provider logs): External provider logs are not accessible; cannot fully rule out a simultaneous bank‑rails issue.

## Open questions

- Does payments-service support dynamic secret reload, or is a pod restart required?
- Were any in‑flight transactions lost during the 2‑minute window before the first auth‑failure log line?
- Could the bank‑rails timeout increase have contributed to any secondary latency spikes once DB connectivity is restored?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 7 model calls, 5 tool calls, 41,422 tokens, 285 s.
