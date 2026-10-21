# T06: Intermittent errors across the app

**Outcome:** inconclusive
- HYP-1 has unresolved blocking objections

## Summary

Intermittent ~2% request failures began around 11:15 UTC after the orders‑service v2.16.0 deploy at 11:05 UTC. The leading hypothesis (HYP‑1) is that the new batched fee‑schedule lookup lengthens a DB transaction enough to hit an idle‑in‑transaction or lock‑wait timeout, causing PostgreSQL to close the connection and surface as “connection reset by peer” errors. However, the investigation stopped after two rounds because HYP‑1 has a blocking objection: no metric shows the transaction duration or connection‑reset counters, and the exact code diff for the deploy is unavailable. Other hypotheses (PostgreSQL hiccup, feature‑flag rollout, pool‑config change) were rejected or remain unruled‑out. The root cause remains inconclusive.

## Hypotheses

### 1. `code_regression` on **orders-service**, triggered by `chg:2561` (HYP-1)

Confidence 0.50 (medium), critic: challenge, capped from 0.78: it has unresolved blocking objections. The v2.16.0 deploy introduced a batched fee‑schedule lookup that runs a larger/longer DB transaction. In a small fraction of calls the transaction exceeds PostgreSQL's idle‑in‑transaction timeout (or hits a lock‑wait timeout), so the server closes the connection → client logs “connection … reset by peer”. Errors bubble up through the hard HTTP edge‑gateway, producing ~2 % 5xx seen by customers.

**Supporting:**
- deploy on orders-service at 11:05:12 UTC by ci/deploy-bot: orders-service v2.16.0: batch fee schedule lookups (version: 2.16.0, previous_version: 2.15.2, commit: 8b20f4e, diff: +142 / -97) (`chg:2561`)
- orders-service v2.16.0 was deployed at 11:05:12 UTC. (`chg:2561`)
- WARN log “fee cache cold; fetching <n> fee schedules” appears 36 times, first at 11:06:22 and last at 11:18:41. (`log:e91658633ca4`)
- WARN log “connection to postgres-orders reset by peer; retrying” appears 203 times, first at 11:15:13 and last at 11:49:45. (`log:a32c4ff0bfc1`)
- Error‑rate metric (baseline 0.001883) rises from 0.0018 at 11:00 to 0.0040 at 11:14, then climbs to a peak of 0.01024 at 11:36, averaging 0.0060 over the window. (`metric:orders-service/error_rate`)
- edge‑gateway calls orders‑service via a hard HTTP dependency (timeout 3 s). (`dep:edge-gateway->orders-service`)
- Symptom pattern (~2 % request failures, retries succeed, minimal latency/error graph movement) matches a transient failure in a single downstream service (orders‑service) affecting only traffic that reaches it. (`chg:2561`, `dep:edge-gateway->orders-service`)
**Contradicting:**
- DB pool in‑use mean 17.2 connections (baseline 16.5), max 20.97; pool size constant at 40. (`metric:orders-service/db_pool_in_use`, `metric:orders-service/db_pool_max_connections`)
- CPU, memory, RPS remain within baseline ranges (CPU mean 0.475 vs 0.452 baseline; mem mean 0.553 vs 0.550; rps mean 149.6 vs 140 baseline). (`metric:orders-service/cpu_util`, `metric:orders-service/mem_util`, `metric:orders-service/rps`)
- payments‑service error_rate baseline_mean 0.002066; observed mean 0.002038, first 0.001741 at 10:30, last 0.001234 at 11:50 – no increase at 11:15. (`metric:payments-service/error_rate`)
- payments‑service latency_p99_ms baseline_mean 468.9 ms; observed mean 465.3 ms, stable across window. bank_rails_latency_p99_ms baseline_mean 417.4 ms; observed mean 424.3 ms, also stable. (`metric:payments-service/latency_p99_ms`, `metric:payments-service/bank_rails_latency_p99_ms`)
- postgres-orders query_latency_p99_ms mean 17.53 ms (baseline 17.7 ms), max 21.11 ms, min 13.34 ms over 11:10‑11:40; no spike at 11:15. (`metric:postgres-orders/query_latency_p99_ms`)
**Assumptions:**
- ASM-7: The batched fee‑schedule lookup lengthens the DB transaction (holds a connection longer).
- ASM-8: PostgreSQL is configured with an idle‑in‑transaction timeout that can be hit by the longer transaction.
**Objections:**
- [blocking] unsupported_claim: The claim that the batched lookup lengthens a DB transaction enough to hit an idle‑in‑transaction or lock‑wait timeout is not backed by any metric (transaction duration, lock wait, or connection‑reset counters).
- [minor] alternative_not_excluded: HYP‑2 (postgres transient hiccup), HYP‑3 (feature‑flag rollout), and HYP‑4 (pool‑config change) have not been ruled out by the current evidence. (not blocking: this review rejected HYP-2 or found it flawed)
- [minor] gap_unaddressed: The exact source diff for commit 8b20f4e (v2.16.0) and Postgres connection‑reset/abort counters are not available via the current toolset, leaving a key mechanistic gap.

### 2. `dependency_degradation` on **postgres-orders** (HYP-2)

Confidence 0.14 (low), critic: reject. A transient network/OS hiccup on the PostgreSQL host (e.g., NIC reset, firewall reload, conntrack overflow) began ~11:15, causing the server to abort existing client sockets. Orders‑service logs the peer‑reset; its error‑rate climbs; edge‑gateway sees the downstream failures via its hard dependency.

**Supporting:**
- WARN log “connection to postgres-orders reset by peer; retrying” appears 203 times, first at 11:15:13 and last at 11:49:45. (`log:a32c4ff0bfc1`)
- Error‑rate metric (baseline 0.001883) rises from 0.0018 at 11:00 to 0.0040 at 11:14, then climbs to a peak of 0.01024 at 11:36, averaging 0.0060 over the window. (`metric:orders-service/error_rate`)
- edge‑gateway error_rate baseline_mean is 0.002036 (≈0.2 %). From 11:15 UTC onward the 3‑minute points rise to 0.018‑0.023 (≈1.8‑2.3 %). (`metric:edge-gateway/error_rate`)
- edge‑gateway calls orders‑service via a hard HTTP dependency (timeout 3 s). (`dep:edge-gateway->orders-service`)
- Symptom pattern (~2 % request failures, retries succeed, minimal latency/error graph movement) matches a transient failure in a single downstream service (orders‑service) affecting only traffic that reaches it. (`chg:2561`, `dep:edge-gateway->orders-service`)
**Contradicting:**
- No config changes, feature‑flag flips, secret rotations, or infra work were recorded for any other listed service or shared infrastructure in the window. (`chg:2561`)
- DB pool in‑use mean 17.2 connections (baseline 16.5), max 20.97; pool size constant at 40. (`metric:orders-service/db_pool_in_use`, `metric:orders-service/db_pool_max_connections`)
- CPU, memory, RPS remain within baseline ranges (CPU mean 0.475 vs 0.452 baseline; mem mean 0.553 vs 0.550; rps mean 149.6 vs 140 baseline). (`metric:orders-service/cpu_util`, `metric:orders-service/mem_util`, `metric:orders-service/rps`)
- payments‑service error_rate baseline_mean 0.002066; observed mean 0.002038, first 0.001741 at 10:30, last 0.001234 at 11:50 – no increase at 11:15. (`metric:payments-service/error_rate`)
- payments‑service latency_p99_ms baseline_mean 468.9 ms; observed mean 465.3 ms, stable across window. bank_rails_latency_p99_ms baseline_mean 417.4 ms; observed mean 424.3 ms, also stable. (`metric:payments-service/latency_p99_ms`, `metric:payments-service/bank_rails_latency_p99_ms`)
- postgres-orders query_latency_p99_ms mean 17.53 ms (baseline 17.7 ms), max 21.11 ms, min 13.34 ms over 11:10‑11:40; no spike at 11:15. (`metric:postgres-orders/query_latency_p99_ms`)
- postgres-orders active_connections mean 87.2 connections (baseline 84.8), range 69.5‑99.9; modest increase but well below pool limits. (`metric:postgres-orders/active_connections`)
- postgres-orders cpu_util mean 0.400 (baseline 0.386), range 0.33‑0.50; slight elevation, not indicative of saturation. (`metric:postgres-orders/cpu_util`)
- postgres-orders replication_lag_s mean 0.372 s (baseline 0.419 s), range 0.123‑0.585 s; replication lag improved relative to baseline. (`metric:postgres-orders/replication_lag_s`)
**Assumptions:**
- ASM-9: A non‑instrumented network event can reset TCP sockets without showing up in PostgreSQL metrics.
- ASM-10: The event is short‑lived, so 1‑minute sampled metrics miss it.
**Objections:**
- [blocking] temporal_violation: Orders‑service error rate rises at 11:14, before the first peer‑reset log at 11:15:13, so the putative Postgres hiccup cannot be the initial cause.
- [blocking] ignores_contradiction: Postgres‑orders metrics (query latency, active connections, CPU, replication lag) show no degradation at 11:15, contradicting a server‑side network/OS hiccup.

### 3. `feature_flag` on **orders-service**, triggered by `chg:2561` (HYP-3)

Confidence 0.06 (low), critic: challenge. The deploy toggles a feature flag that enables the new batched fee‑schedule path for only a slice of traffic (~2 %). Those requests hit a bug (e.g., missing retry on cache‑miss) → “fee cache cold” logs and intermittent failures; retries succeed because the flag is evaluated per‑request.

**Supporting:**
- WARN log “fee cache cold; fetching <n> fee schedules” appears 36 times, first at 11:06:22 and last at 11:18:41. (`log:e91658633ca4`)
- Error‑rate metric (baseline 0.001883) rises from 0.0018 at 11:00 to 0.0040 at 11:14, then climbs to a peak of 0.01024 at 11:36, averaging 0.0060 over the window. (`metric:orders-service/error_rate`)
- Symptom pattern (~2 % request failures, retries succeed, minimal latency/error graph movement) matches a transient failure in a single downstream service (orders‑service) affecting only traffic that reaches it. (`chg:2561`, `dep:edge-gateway->orders-service`)
**Contradicting:**
- No config changes, feature‑flag flips, secret rotations, or infra work were recorded for any other listed service or shared infrastructure in the window. (`chg:2561`)
- WARN log “connection to postgres-orders reset by peer; retrying” appears 203 times, first at 11:15:13 and last at 11:49:45. (`log:a32c4ff0bfc1`)
- DB pool in‑use mean 17.2 connections (baseline 16.5), max 20.97; pool size constant at 40. (`metric:orders-service/db_pool_in_use`, `metric:orders-service/db_pool_max_connections`)
- CPU, memory, RPS remain within baseline ranges (CPU mean 0.475 vs 0.452 baseline; mem mean 0.553 vs 0.550; rps mean 149.6 vs 140 baseline). (`metric:orders-service/cpu_util`, `metric:orders-service/mem_util`, `metric:orders-service/rps`)
**Assumptions:**
- ASM-11: A feature flag was flipped silently during the deploy.
- ASM-12: The flagged path is exercised by ~2 % of requests.
**Objections:**
- [blocking] unsupported_claim: No feature‑flag change is recorded in the change history for the deploy window; the hypothesis assumes a flag flip that is not observed.
- [minor] alternative_not_excluded: HYP‑1 (code regression) also explains the “fee cache cold” logs and error pattern and has not been excluded. (not blocking: this review rejected HYP-1 or found it flawed)
- [minor] gap_unaddressed: A feature‑flag audit for orders‑service around 11:05 is not obtainable from the available change‑history endpoint.

### 4. `config_change` on **orders-service**, triggered by `chg:2561` (HYP-4)

Confidence 0.02 (low), critic: reject. The new binary ships a different default for the connection‑pool configuration (e.g., shorter maxLifetime or idle_timeout). Connections that survive longer than the new limit are closed by the pool, and the client interprets the closure as “reset by peer”.

**Supporting:**
- WARN log “connection to postgres-orders reset by peer; retrying” appears 203 times, first at 11:15:13 and last at 11:49:45. (`log:a32c4ff0bfc1`)
- Error‑rate metric (baseline 0.001883) rises from 0.0018 at 11:00 to 0.0040 at 11:14, then climbs to a peak of 0.01024 at 11:36, averaging 0.0060 over the window. (`metric:orders-service/error_rate`)
- edge‑gateway calls orders‑service via a hard HTTP dependency (timeout 3 s). (`dep:edge-gateway->orders-service`)
**Contradicting:**
- No config changes, feature‑flag flips, secret rotations, or infra work were recorded for any other listed service or shared infrastructure in the window. (`chg:2561`)
- DB pool in‑use mean 17.2 connections (baseline 16.5), max 20.97; pool size constant at 40. (`metric:orders-service/db_pool_in_use`, `metric:orders-service/db_pool_max_connections`)
**Assumptions:**
- ASM-13: The deploy bundles a library upgrade that changes pool defaults.
**Objections:**
- [blocking] unsupported_claim: The hypothesis posits a pool‑configuration change in v2.16.0, but the change census shows only a code diff; no config change is recorded.
- [blocking] ignores_contradiction: DB pool size and in‑use connections remain constant and well below limits, providing no evidence that a new pool limit is being hit.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll back orders‑service to v2.15.2 to stop the error spike while the root cause is clarified. | The deploy at 11:05 UTC is the only change correlated with the symptom onset; rolling back removes the suspect code path immediately. (HYP-1) |
| now | investigate | Retrieve the full source diff for commit 8b20f4e (orders‑service v2.16.0) to verify whether the batched fee‑schedule lookup introduces a larger/longer DB transaction. | The blocking objection on HYP‑1 cites the missing code diff; the diff is needed to confirm or refute the transaction‑length mechanism. (HYP-1) |
| soon | investigate | Enable and collect PostgreSQL connection‑reset / aborted‑connection counters (e.g., pg_stat_database_conflicts, pg_stat_activity state changes) for the postgres‑orders instance covering 11:10‑11:40 UTC. | HYP‑1 predicts a spike in connection‑reset errors; the current metric catalog lacks these counters (GAP‑9). (HYP-1) |
| soon | investigate | Add DB‑transaction‑level metrics (transaction duration, active transaction count) to orders‑service and PostgreSQL dashboards. | Gap‑11 notes no transaction‑latency metrics exist; they are required to observe whether the new code path lengthens transactions. (HYP-1) |
| soon | investigate | Audit feature‑flag state for orders‑service at the time of the deploy to determine whether a flag enabling the batched lookup was flipped for a subset of traffic. | HYP‑3 assumes a flag flip (~2% traffic) but no flag change is recorded; the audit will confirm or exclude this path. (HYP-3) |
| soon | investigate | Verify whether any connection‑pool configuration (maxLifetime, idleTimeout) changed in v2.16.0 by reviewing the full diff and runtime config. | HYP‑4 posits a pool‑config change, but the change census shows only code changes; confirming the config eliminates this hypothesis. (HYP-4) |
| later | prevent | Implement automated canary analysis with error‑rate and latency guards for all service deployments. | A canary would have detected the ~2% error rise early and prevented a full rollout of a regressing version. |
| later | prevent | Add alerts for PostgreSQL idle‑in‑transaction timeouts, lock‑wait timeouts, and connection‑reset counters. | Direct visibility into the conditions HYP‑1 describes would surface similar issues instantly. (HYP-1) |
| later | fix | If the batched fee‑schedule lookup is confirmed to cause long transactions, refactor it to use smaller batches or asynchronous processing. | Removes the mechanistic cause identified in HYP‑1 and prevents recurrence. (HYP-1) |

## Evidence gaps

- **query_metrics** (Kafka consumer lag for orders-service): Metric not exposed / not returned in the metrics summary; needed to assess downstream back‑pressure.
- **query_metrics** (error_rate, latency_p99, rps for orders-service, market-data-service, payments-service, portfolio-service, quotes-vendor, postgres-orders, postgres-payments, bank-rails, redis-cache): Step budget exhausted; need per‑service error/latency series to locate the first hop after edge‑gateway.
- **get_change_history** (orders-service v2.16.0 code diff): The change census only provides a line‑count summary (+142/‑97). The exact code change to “batch fee schedule lookups” is needed to assess race conditions, cache‑miss fallbacks, or DB‑lock contention.
- **get_change_history** (Feature‑flag or config toggles applied during the orders‑service deploy): Flags flipped as part of a deploy are not always emitted as separate change records; a flag could enable the new batch path for only a subset of traffic, matching the 2 % error rate.
- **get_service_dependencies** (Edge‑gateway request routing / fan‑out logic): If a single client request fans out to both orders‑service and portfolio‑service, a failure in orders‑service could be counted as a failure for the portfolio screen, inflating the apparent error surface.
- **get_change_history** (Client‑side error classification (server 5xx vs client timeout/network error)): Responder notes suggest a possible client‑side cause; confirming the error class would focus the investigation on the correct tier.
- **query_metrics** (portfolio-service, quotes-vendor, postgres-orders, postgres-payments, bank-rails, redis-cache, kafka): Step limit reached; unable to fetch error‑rate and latency metrics for the remaining downstream services.
- **query_logs** (portfolio-service, quotes-vendor, postgres-orders, postgres-payments, bank-rails, redis-cache, kafka): Step limit reached; unable to inspect WARN/ERROR log patterns for the remaining downstream services.
- **query_metrics** (postgres-orders connection reset / aborted connection counters): The metric catalog for postgres-orders does not expose connection‑reset or aborted‑connection counters, so the requested REQ‑4 counters cannot be retrieved.
- **get_change_history** (commit 8b20f4e diff): The change‑history endpoint only returns a line‑count summary (+142 / -97) and does not provide the actual source diff needed to verify whether the batched lookup lengthens DB transactions.
- **metrics query (not available)** (orders-service DB transaction latency / active transaction count): No transaction‑level metrics (e.g., db_txn_duration_ms, db_txn_active_count) were supplied, so we cannot directly observe a change in transaction length after the deploy.

## Open questions

- What is the exact code change in commit 8b20f4e (the batched fee‑schedule lookup implementation)?
- Do orders‑service DB transactions after the deploy exceed PostgreSQL's idle‑in‑transaction or lock‑wait timeout thresholds?
- What are the PostgreSQL connection‑reset / aborted‑connection counters during 11:10‑11:40 UTC?
- Was a feature flag toggled as part of the v2.16.0 rollout that enables the new lookup for only a fraction of traffic?
- Did the connection‑pool configuration (maxLifetime, idleTimeout) change in the new binary?
- Are the observed client errors server‑side 5xx or client‑side timeouts/network errors?
- What is the Kafka consumer lag for orders‑service during the incident window (possible back‑pressure)?

## How the investigation ran

Stopped because reached the limit of 2 rounds, after 2 round(s): 34 model calls, 16 tool calls, 169,922 tokens, 882 s.
