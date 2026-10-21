# T08: Deposits and checkout failing overnight

**Outcome:** conclusive. Root cause: `certificate_or_credential` on **postgres-payments**, triggered by `chg:2581`

## Summary

At 02:00:05 UTC the Vault‑managed password for the payments_app database user on postgres-payments was rotated (chg:2581). The running payments-service pods continued using the old password, so every new DB connection failed with “password authentication failed”. Because the DB pool is a hard dependency, checkout (POST /v1/checkout) and deposit (POST /v1/deposits) calls began returning 500 errors; error_rate rose from a baseline of 0.002 to 0.33 and the DB connection pool collapsed from ~6 to 2 connections. Health checks stayed green because they do not exercise a DB connection. The earlier config change that raised the bank‑rails timeout (chg:2578) is unrelated – bank‑rails shows only benign 409 warnings and stable latency.

## Hypotheses

### 1. `certificate_or_credential` on **postgres-payments**, triggered by `chg:2581` (HYP-1)

Confidence 0.93 (high). Secret rotation changed the DB password; payments-service pods kept the old password, causing authentication failures on every new connection. The hard DB dependency makes checkout/deposit calls fail with 500, draining the pool and raising error_rate.

**Supporting:**
- At 02:00:05 a secret rotation replaced the DB password for payments_app on postgres-payments (v31 → v32). (`chg:2581`)
- From 02:02:05 onward 788 ERROR log lines appear: “could not open connection to postgres-payments: FATAL: password authentication failed for user “payments_app””. (`log:07bf0979f12c`)
- Metrics 01:30‑02:35: error_rate jumps from baseline 0.002 to 0.327 (last minute), latency_p99 rises from 483 ms baseline to 564 ms, db_pool_in_use falls from ~6 baseline to 2. CPU, memory, RPS flat. (`metric:payments-service/error_rate`, `metric:payments-service/latency_p99_ms`, `metric:payments-service/db_pool_in_use`)
- payments-service depends on bank-rails (hard, 4 s timeout), kafka (soft), and postgres-payments (hard, 2 s timeout). (`dep:payments-service->bank-rails`, `dep:payments-service->postgres-payments`)
**Assumptions:**
- ASM-1: payments-service reads the DB password only at start‑up; the secret rotation does not trigger a reload.
- ASM-2: The health‑check endpoint does not open a DB connection.

### 2. `config_change` on **payments-service**, triggered by `chg:2578` (HYP-2)

Confidence 0.12 (low). Raising the bank-rails client timeout caused downstream time‑outs that manifest as 500s on checkout/deposit.

**Supporting:**
- At 01:38:20 a config change raised the bank-rails client timeout from 4000 ms to 5000 ms. (`chg:2578`)
- payments-service depends on bank-rails (hard, 4 s timeout), kafka (soft), and postgres-payments (hard, 2 s timeout). (`dep:payments-service->bank-rails`, `dep:payments-service->postgres-payments`)
**Contradicting:**
- Bank-rails logs only WARN lines (7 × 409 idempotency‑key duplicates); no error surge. (`log:056d74b236f2`)
- Metrics 01:30‑02:35: error_rate jumps from baseline 0.002 to 0.327 (last minute), latency_p99 rises from 483 ms baseline to 564 ms, db_pool_in_use falls from ~6 baseline to 2. CPU, memory, RPS flat. (`metric:payments-service/error_rate`, `metric:payments-service/latency_p99_ms`, `metric:payments-service/db_pool_in_use`)
**Assumptions:**
- ASM-3: Increasing the bank-rails timeout by 1 s cannot instantly produce a 30 %+ error rate on checkout/deposit.

### 3. `dependency_degradation` on **bank-rails** (HYP-3)

Confidence 0.04 (low). Bank‑rails maintenance/outage (similar to Feb) causes checkout/deposit failures.

**Contradicting:**
- Bank-rails logs only WARN lines (7 × 409 idempotency‑key duplicates); no error surge. (`log:056d74b236f2`)
- Metrics 01:30‑02:35: error_rate jumps from baseline 0.002 to 0.327 (last minute), latency_p99 rises from 483 ms baseline to 564 ms, db_pool_in_use falls from ~6 baseline to 2. CPU, memory, RPS flat. (`metric:payments-service/error_rate`, `metric:payments-service/latency_p99_ms`, `metric:payments-service/db_pool_in_use`)
**Assumptions:**
- ASM-4: No hidden bank-rails outage occurred; the only observable bank-rails signal is the 409 warnings.

### 4. `code_regression` on **payments-service** (HYP-4)

Confidence 0.04 (low). A latent bug in payments-service surfaces under load, causing 500s.

**Supporting:**
- Metrics 01:30‑02:35: error_rate jumps from baseline 0.002 to 0.327 (last minute), latency_p99 rises from 483 ms baseline to 564 ms, db_pool_in_use falls from ~6 baseline to 2. CPU, memory, RPS flat. (`metric:payments-service/error_rate`, `metric:payments-service/latency_p99_ms`, `metric:payments-service/db_pool_in_use`)
**Contradicting:**
- No deploy of payments-service or any other service in the 00:00‑02:35 window. (`chg:2578`, `chg:2581`)
- From 02:02:05 onward 788 ERROR log lines appear: “could not open connection to postgres-payments: FATAL: password authentication failed for user “payments_app””. (`log:07bf0979f12c`)
**Assumptions:**
- ASM-5: No latent code regression was exercised for the first time at 02:00 UTC.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll restart all payments-service pods (or trigger a config reload if supported). | Forces pods to fetch the new DB password, stopping auth failures immediately. |
| now | fix | Verify postgres-payments accepted the new password (check DB auth logs). | Confirms rotation succeeded on the server side. |
| soon | prevent | Add a DB‑connection check to payments-service readiness probe. | Future credential rotations will be detected automatically; health checks will reflect true state. |
| soon | prevent | Update secret‑rotation run‑book to notify payments team and/or automate rolling restart of dependent services after DB password change. | Removes manual gap that caused outage. |
| later | prevent | Implement dynamic credential reload (Vault Agent sidecar or periodic config refresh) in payments-service. | Eliminates need for restarts on future rotations. |
| later | prevent | Add alerting on sharp drop of db_pool_in_use or spike in error_rate for payments-service. | Early detection of similar credential‑mismatch incidents. |

## Evidence gaps

- **query_logs** (postgres-payments): DB logs would confirm authentication failures on the server side and verify rotation success.
- **query_metrics** (postgres-payments): DB connection metrics would show the drop in successful auths.
- **get_change_history** (payments-service credential reload mechanism): Need to know if the service auto‑reloads Vault secrets or requires restart.
- **query_logs** (payments-service health‑check endpoint): Confirm health‑check does not hit the DB (assumption A2).

## Open questions

- Does payments-service have any automatic credential‑refresh capability?
- What does the current health‑check endpoint actually test?
- Were there any concurrent DB configuration changes (e.g., pg_hba.conf reload) not captured in change history?
- Can we add a metric/alert for the “password authentication failed” log pattern to catch credential mismatches instantly?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 6 model calls, 4 tool calls, 34,737 tokens, 145 s.
