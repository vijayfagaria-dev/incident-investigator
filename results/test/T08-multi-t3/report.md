# T08: Deposits and checkout failing overnight

**Outcome:** conclusive. Root cause: `certificate_or_credential` on **postgres-payments**, triggered by `chg:2581`

## Summary

Deposits and checkout began failing shortly after 02:00 UTC when Vault rotated the PostgreSQL password for the payments_app user (v31→v32). Payments‑service pods do not automatically reload the secret, so existing connections started failing with “FATAL: password authentication failed”, the DB connection pool drained, and request handlers for /v1/checkout and /v1/deposits returned 500. Health checks remained green because they do not execute a DB query. The investigation concluded this mechanism (HYP‑1, confidence 0.86) as the root cause. The early 504 responses on /v1/withdrawals starting at 01:34 UTC remain unexplained.

## Hypotheses

### 1. `certificate_or_credential` on **postgres-payments**, triggered by `chg:2581` (HYP-1)

Confidence 0.86 (high), critic: accept. Vault rotated the PostgreSQL password for payments_app at 02:00:05 UTC (v31→v32). Payments‑service does not automatically reload the secret, so existing pods keep using the old password. New DB connections fail with “FATAL: password authentication failed”, the connection pool drains (in‑use drops from ~5.3 to 2), and request handlers for /v1/checkout and /v1/deposits return 500. Health checks stay green because they do not exercise a DB query.

**Supporting:**
- secret_rotation on postgres-payments at 02:00:05 UTC by vault-rotator: Rotate database password for payments_app (secret: db/postgres-payments/payments_app, version: v31 -> v32) (`chg:2581`)
- Starting at 02:02:05 UTC, payments-service logged 788 “FATAL: password authentication failed for user “payments_app”” errors until 02:34:53 UTC. (`log:07bf0979f12c`)
- payments-service logged 788 “FATAL: password authentication failed for user “payments_app”” errors beginning at 2026-10-13T02:02:05 UTC and continuing until 02:34:53 UTC. (`log:07bf0979f12c`)
- Payments-service DB pool in‑use dropped from 5.28 connections at 01:15 UTC to 2.0 at 02:35 UTC, well below the baseline of 5.75. (`metric:payments-service/db_pool_in_use`)
- Edge‑gateway logged 196 occurrences of pattern “upstream payments-service returned 500 (route /v1/checkout)” with the first occurrence at 2026-10-13T02:03:01.213Z and the last at 2026-10-13T02:34:57.568Z. (`log:ca1979ec42e9`)
- postgres-payments active_connections fell from 18.36 at 01:55 UTC to 5.75 at 02:35 UTC, well below the baseline of 20.95, with the decline starting around the secret rotation time. (`metric:postgres-payments/active_connections`)
**Contradicting:**
- From 01:34:34 UTC onward, payments-service recorded 169 HTTP 504 responses (e.g., POST /v1/withdrawals 504 88 ms). (`log:9a103e61f521`)
- Bank‑rails client latency (p99) as measured by payments-service increased from a baseline of 412 ms to 489 ms at 02:35 UTC. (`metric:payments-service/bank_rails_latency_p99_ms`)
**Assumptions:**
- ASM-5: payments‑service does not reload the PostgreSQL password automatically on Vault rotation; a pod restart or SIGHUP is required.
- ASM-6: The payments‑service health‑check endpoint does not perform a DB query.
**Objections:**
- [minor] gap_unaddressed: Early 504 responses on /v1/withdrawals starting at 01:34 (OBS-8) are not explained by the secret‑rotation mechanism; they may be unrelated but remain an open gap.

### 2. `dependency_degradation` on **bank-rails**, triggered by `chg:2578` (HYP-2)

Confidence 0.12 (low), critic: reject. At 01:38:20 UTC the bank‑rails client timeout was raised from 4000 ms to 5000 ms. An unrecorded bank‑rails slowdown (e.g., maintenance) began shortly before, causing downstream latency to approach the new timeout. Payments‑service started returning 504s for withdrawals and later 500s at the gateway.

**Supporting:**
- config on payments-service at 01:38:20 UTC by config-bot: Raise bank-rails client timeout (bank_rails.timeout_ms: 4000 -> 5000) (`chg:2578`)
- payments-service configuration changed at 01:38:20 UTC, raising bank_rails.timeout_ms from 4000 to 5000 (chg:2578). (`chg:2578`)
- Bank‑rails client latency (p99) as measured by payments-service increased from a baseline of 412 ms to 489 ms at 02:35 UTC. (`metric:payments-service/bank_rails_latency_p99_ms`)
- From 01:34:34 UTC onward, payments-service recorded 169 HTTP 504 responses (e.g., POST /v1/withdrawals 504 88 ms). (`log:9a103e61f521`)
**Contradicting:**
- From 01:34:34 UTC onward, payments-service recorded 169 HTTP 504 responses (e.g., POST /v1/withdrawals 504 88 ms). (`log:9a103e61f521`)
- Starting at 02:02:05 UTC, payments-service logged 788 “FATAL: password authentication failed for user “payments_app”” errors until 02:34:53 UTC. (`log:07bf0979f12c`)
- Payments-service DB pool in‑use dropped from 5.28 connections at 01:15 UTC to 2.0 at 02:35 UTC, well below the baseline of 5.75. (`metric:payments-service/db_pool_in_use`)
- No gateway‑side timeout, circuit‑breaker, or “upstream timeout” log lines were found in the edge‑gateway between 01:15 UTC and 02:35 UTC. (`log:0d4fbbb98f6d`)
- payments-service has a hard downstream dependency on bank-rails with a configured client timeout of 4000 ms (dep:payments-service->bank-rails). (`dep:payments-service->bank-rails`)
**Assumptions:**
- ASM-7: An unrecorded bank‑rails slowdown or maintenance window began around 01:30 UTC.
- ASM-8: The timeout increase (4000→5000 ms) was a reactive change to the pre‑existing slowdown, not the cause.
**Objections:**
- [blocking] unsupported_claim: Claims an unrecorded bank‑rails slowdown caused timeouts, but no latency or error‑rate metrics for bank‑rails show a spike near the 5 s timeout (OBS-5 shows only 489 ms).
- [blocking] ignores_contradiction: Ignores the observed PostgreSQL password‑auth failures (OBS-7, OBS-20) and the corresponding connection‑pool drain (OBS-6, OBS-19) that line up with the secret rotation.

### 3. `unknown` on **payments-service** (HYP-3)

Confidence 0.02 (low), critic: reject. A latent bug in payments‑service (e.g., connection‑pool leak or error‑handling flaw) was triggered by the combination of longer bank‑rails calls and the credential rotation, causing spontaneous 500s without any recorded change.

**Supporting:**
- Edge‑gateway error log pattern “GET /v1/portfolio 500 30ms” appears 22 times, first at 2026-10-13T01:53:22.545Z, indicating 500 responses were already being proxied before the checkout surge. (`log:b93f3c05e168`)
- No log lines referencing the /v1/deposits route were present in edge‑gateway logs at WARN level or above during the same window. (`log:ca1979ec42e9`)
**Contradicting:**
- secret_rotation on postgres-payments at 02:00:05 UTC by vault-rotator: Rotate database password for payments_app (secret: db/postgres-payments/payments_app, version: v31 -> v32) (`chg:2581`)
- Starting at 02:02:05 UTC, payments-service logged 788 “FATAL: password authentication failed for user “payments_app”” errors until 02:34:53 UTC. (`log:07bf0979f12c`)
- Payments-service DB pool in‑use dropped from 5.28 connections at 01:15 UTC to 2.0 at 02:35 UTC, well below the baseline of 5.75. (`metric:payments-service/db_pool_in_use`)
- postgres-payments active_connections fell from 18.36 at 01:55 UTC to 5.75 at 02:35 UTC, well below the baseline of 20.95, with the decline starting around the secret rotation time. (`metric:postgres-payments/active_connections`)
- config on payments-service at 01:38:20 UTC by config-bot: Raise bank-rails client timeout (bank_rails.timeout_ms: 4000 -> 5000) (`chg:2578`)
- Bank‑rails client latency (p99) as measured by payments-service increased from a baseline of 412 ms to 489 ms at 02:35 UTC. (`metric:payments-service/bank_rails_latency_p99_ms`)
- From 01:34:34 UTC onward, payments-service recorded 169 HTTP 504 responses (e.g., POST /v1/withdrawals 504 88 ms). (`log:9a103e61f521`)
**Assumptions:**
- ASM-9: A hidden code defect in payments‑service could manifest only under the combined stress of higher downstream latency and credential rotation.
**Objections:**
- [blocking] unsupported_claim: Asserts a latent bug triggered by combined factors, yet no heterogeneous error pattern is observed; logs are dominated by DB auth failures.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Restart all payments‑service pods (or send SIGHUP) to force them to read the new database password. | Immediately restores successful DB connections and stops the 500 error surge. (HYP-1) |
| soon | fix | Add automatic secret reloading (e.g., Vault Agent sidecar, filesystem watch, or periodic SIGHUP) so payments‑service picks up rotated credentials without a pod restart. | Eliminates the window where pods run with stale credentials after each rotation. (HYP-1) |
| later | prevent | Extend the payments‑service health check to perform a lightweight DB query, and add an alert on PostgreSQL authentication‑failure counters. | Detects credential‑mismatch failures before they affect customers and makes future rotations visible. (HYP-1) |
| soon | investigate | Determine the cause of the 504 responses on /v1/withdrawals beginning at 01:34 UTC (OBS‑8) which are not explained by the secret rotation. | Closes the remaining evidence gap (GAP‑1, GAP‑6) and rules out any concurrent bank‑rails issue. |
| soon | investigate | Collect missing bank‑rails latency/error metrics and postgres‑payments authentication‑failure metrics for the 01:00‑02:35 UTC window. | Fills evidence gaps GAP‑1, GAP‑2, GAP‑8 and confirms no hidden downstream degradation. |

## Evidence gaps

- **query_metrics** (bank-rails latency, error_rate, cpu, connection pool): Metrics for bank-rails were not fetched; needed to confirm whether downstream latency contributed.
- **query_metrics** (postgres-payments connection count, authentication failures, CPU, memory): Metrics for postgres-payments were not fetched; required to verify DB contention and rotation impact.
- **query_logs** (payments-service ERROR logs for POST /v1/checkout and POST /v1/deposits): Only generic error patterns were returned; specific checkout/deposit failure logs are missing.
- **query_logs** (payments-service logs at WARN/ERROR level for 01:15‑02:35 UTC): Not queried in this assignment; needed to confirm origin of 500s and any exception stack traces.
- **query_metrics** (payments-service request latency, error rate, and DB connection pool saturation for 01:15‑02:35 UTC): Metrics not fetched; would help pinpoint whether the service began failing before the gateway observed upstream 500s.
- **get_change_history** (bank-rails service changes (config, feature flags, infra) in the 01:00–02:35 window): Change census only covered the four listed services; bank-rails may have had an unrecorded change (e.g., maintenance window) that could affect latency.
- **get_service_dependencies** (Full downstream graph from payments-service (including kafka, any retry/queue layers)): Only depth‑2 downstream was retrieved; indirect dependencies (e.g., payments-service → kafka → downstream consumer) could surface additional failure paths.
- **query_metrics** (postgres-payments/auth_failure_total): Metric does not exist on postgres-payments; available metrics are active_connections, cpu_util, query_latency_p99_ms, replication_lag_s.
- **query_logs** (payments-service POST /v1/deposits ERROR): No matching ERROR‑level records returned; deposits failures may be logged at a lower level or not at all.
- **query_logs** (postgres-payments authentication failure logs): Postgres logs were not queried; they could contain additional evidence of failed password attempts.

## Open questions

- What caused the 504 responses on /v1/withdrawals starting at 01:34 UTC (OBS‑8) if not the secret rotation?
- Did bank‑rails experience any unrecorded change or maintenance that could have contributed to early latency?
- Are deposit failures logged at a level lower than ERROR, and why were no ERROR‑level logs found for POST /v1/deposits (OBS‑22)?
- Will the added DB‑query health check reliably surface credential mismatches for future rotations?

## How the investigation ran

Stopped because the critic accepted HYP-1, after 2 round(s): 27 model calls, 13 tool calls, 120,350 tokens, 1019 s.
