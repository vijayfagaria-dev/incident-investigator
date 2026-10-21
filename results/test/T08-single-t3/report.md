# T08: Deposits and checkout failing overnight

**Outcome:** conclusive. Root cause: `config_change` on **postgres-payments**, triggered by `chg:2581`

## Summary

At 02:00 UTC the database password for the payments_app user on postgres‑payments was rotated (chg:2581). Within two minutes payments‑service began logging “password authentication failed” errors (log:07bf0979f12c). Because the DB connection is a hard dependency (dep:payments-service->postgres-payments), every checkout/deposit request that needs a DB transaction started failing, producing a flood of 5xx responses from 02:05 UTC onward (log:d4f8251184e5). The service‑level error rate jumped from ~0.2 % to >30 % (metric:payments-service/error_rate) and the DB connection pool collapsed (metric:payments-service/db_pool_in_use). The earlier config change raising the bank‑rails timeout (chg:2578) had no observable impact – bank‑rails latency stayed well under the new 5 s limit (metric:payments-service/bank_rails_latency_p99_ms) and no bank‑rails errors appear in the logs. No code was deployed in the window. The root cause is the secret rotation that left the running payments‑service instances unable to authenticate to PostgreSQL.

## Hypotheses

### 1. `config_change` on **postgres-payments**, triggered by `chg:2581` (HYP-1)

Confidence 0.90 (high). The secret rotation changed the DB password; payments-service continued using the old credential, causing authentication failures on every new DB connection. Because the DB connection is a hard dependency, all checkout/deposit requests that need a transaction fail, producing the observed 5xx surge and the collapse of the connection pool.

**Supporting:**
- Secret rotation chg:2581 at 2026‑10‑13T02:00:05Z rotated the DB password for payments_app on postgres-payments (v31 → v32). (`chg:2581`)
- From 02:02:05 UTC the logs show 788 occurrences of “could not open connection to postgres-payments: FATAL: password authentication failed for user “payments_app”.” (`log:07bf0979f12c`)
- Checkout (POST /v1/checkout) errors (500/502/503/504) start at 02:05:08 UTC and continue across all AZs. (`log:d4f8251184e5`)
- payments-service error_rate jumps from a baseline of 0.002 to 0.327 by the end of the window. (`metric:payments-service/error_rate`)
- db_pool_in_use drops from 6.36 connections at 01:30 to 2.0 at 02:35 (baseline ≈5.94). (`metric:payments-service/db_pool_in_use`)
**Assumptions:**
- ASM-1: payments-service pods pick up the new DB password automatically (e.g., via Vault agent or config reload) without a pod restart.

### 2. `config_change` on **payments-service**, triggered by `chg:2578` (HYP-2)

Confidence 0.10 (low). Increasing the bank‑rails timeout from 4 s to 5 s could cause request queuing if bank‑rails latency were near the old limit, leading to timeouts and 5xx errors.

**Supporting:**
- Config change chg:2578 at 2026‑10‑13T01:38:20Z raised bank_rails.timeout_ms from 4000 to 5000 ms. (`chg:2578`)
- bank_rails_latency_p99 rises modestly from a baseline of 406 ms to 489 ms – still well under the new 5 s timeout. (`metric:payments-service/bank_rails_latency_p99_ms`)
**Contradicting:**
- From 02:02:05 UTC the logs show 788 occurrences of “could not open connection to postgres-payments: FATAL: password authentication failed for user “payments_app”.” (`log:07bf0979f12c`)
- Checkout (POST /v1/checkout) errors (500/502/503/504) start at 02:05:08 UTC and continue across all AZs. (`log:d4f8251184e5`)
- payments-service error_rate jumps from a baseline of 0.002 to 0.327 by the end of the window. (`metric:payments-service/error_rate`)
- db_pool_in_use drops from 6.36 connections at 01:30 to 2.0 at 02:35 (baseline ≈5.94). (`metric:payments-service/db_pool_in_use`)
**Assumptions:**
- ASM-2: Raising the bank‑rails client timeout alone cannot cause a sudden error‑rate spike unless the downstream service is already slower than the old timeout.

### 3. `dependency_degradation` on **bank-rails** (HYP-3)

Confidence 0.08 (low). An external degradation of bank‑rails (e.g., maintenance) could cause payment failures that look like 5xx from payments-service.

**Contradicting:**
- From 02:02:05 UTC the logs show 788 occurrences of “could not open connection to postgres-payments: FATAL: password authentication failed for user “payments_app”.” (`log:07bf0979f12c`)
- Checkout (POST /v1/checkout) errors (500/502/503/504) start at 02:05:08 UTC and continue across all AZs. (`log:d4f8251184e5`)
- payments-service error_rate jumps from a baseline of 0.002 to 0.327 by the end of the window. (`metric:payments-service/error_rate`)
- db_pool_in_use drops from 6.36 connections at 01:30 to 2.0 at 02:35 (baseline ≈5.94). (`metric:payments-service/db_pool_in_use`)
- bank_rails_latency_p99 rises modestly from a baseline of 406 ms to 489 ms – still well under the new 5 s timeout. (`metric:payments-service/bank_rails_latency_p99_ms`)
**Assumptions:**
- ASM-3: An external bank‑rails degradation would surface as HTTP error codes or timeout logs in payments-service.

### 4. `code_regression` on **payments-service** (HYP-4)

Confidence 0.02 (low). A latent bug in payments-service suddenly manifests, causing checkout/deposit failures without any deploy.

**Contradicting:**
- Secret rotation chg:2581 at 2026‑10‑13T02:00:05Z rotated the DB password for payments_app on postgres-payments (v31 → v32). (`chg:2581`)
- From 02:02:05 UTC the logs show 788 occurrences of “could not open connection to postgres-payments: FATAL: password authentication failed for user “payments_app”.” (`log:07bf0979f12c`)
- Checkout (POST /v1/checkout) errors (500/502/503/504) start at 02:05:08 UTC and continue across all AZs. (`log:d4f8251184e5`)
- payments-service error_rate jumps from a baseline of 0.002 to 0.327 by the end of the window. (`metric:payments-service/error_rate`)
- db_pool_in_use drops from 6.36 connections at 01:30 to 2.0 at 02:35 (baseline ≈5.94). (`metric:payments-service/db_pool_in_use`)
**Assumptions:**
- ASM-4: A code regression would require a deploy or config change to manifest; none occurred in the window.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll back the DB password to the previous version (v31) or update the Vault secret used by payments-service to the new value and trigger a reload. | Restores authentication; the only change aligned with the onset of failures. |
| now | fix | Verify that payments-service pods have re‑loaded the new secret (e.g., restart a pod or send SIGHUP to the Vault agent). | Confirms assumption A1; if pods need a restart, perform a rolling restart. |
| soon | prevent | Add a health‑check that validates DB connectivity (e.g., a lightweight SELECT) so future secret rotations surface as unhealthy pods. | Prevents “green health‑check but broken DB” situations. |
| later | prevent | Automate secret‑rotation verification: after each rotation run a smoke test against the DB from a staging pod before marking the rotation complete. | Guarantees the new credentials work for the service. |
| later | prevent | Document the dependency on automatic secret reload in the payments-service run‑book. | Reduces recurrence risk. |

## Evidence gaps

- **query_logs** (postgres-payments logs 2026‑10‑13T01:45‑02:35): Not available; would confirm password‑auth failure from DB side.
- **query_logs** (bank-rails logs 2026‑10‑13T01:45‑02:35): Not available; would rule out external degradation.
- **query_logs** (payments-service secret‑reload configuration): Not available; needed to verify assumption A1.
- **query_logs** (distributed traces for failing checkout requests): Not available; would pinpoint exact failure point.

## Open questions

- Does payments-service automatically reload Vault‑injected secrets, or does it require a pod restart?
- What do the postgres-payments logs show for the same period?
- Were there any bank-rails side‑effects (e.g., increased error rates) that we cannot see?
- Could a brief network partition between payments-service and postgres-payments have coincided with the rotation, amplifying the impact?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 7 model calls, 5 tool calls, 47,146 tokens, 294 s.
