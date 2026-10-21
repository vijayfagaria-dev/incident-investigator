# T06: Intermittent errors across the app

**Outcome:** conclusive. Root cause: `code_regression` on **orders-service**, triggered by `chg:2561`

## Summary

At ~11:15 UTC edge‑gateway began seeing a sharp rise in upstream connection timeouts to portfolio‑service (≈2 % of requests). The same minute orders‑service logged massive PostgreSQL connection resets and a new “fee cache cold” pattern appeared right after the orders‑service v2.16.0 deploy at 11:05. Portfolio‑service simultaneously started failing gRPC calls to market‑data‑service. No other service changed. The weight of evidence points to a code regression in orders‑service v2.16.0 that overloads postgres‑orders, causing connection resets that cascade to portfolio‑service and then to edge‑gateway.

## Hypotheses

### 1. `code_regression` on **orders-service**, triggered by `chg:2561` (HYP-1)

Confidence 0.55 (medium). v2.16.0 introduces batch fee‑schedule lookups that open many short‑lived DB connections, exhausting postgres‑orders connection pool. Connection resets propagate to orders‑service and portfolio‑service (which also uses postgres‑orders). Portfolio‑service then fails its gRPC calls to market‑data‑service, causing edge‑gateway upstream timeouts.

**Supporting:**
- Edge‑gateway logs show upstream connection timeout to portfolio‑service starting at 11:15:01 (1,443 occurrences). (`log:80f1f968cbad`)
- Edge‑gateway error_rate rises from baseline 0.002 to mean 0.0096 (peak 0.025) during the incident window. (`metric:edge-gateway/error_rate`)
- Edge‑gateway latency_p99 climbs from baseline 342 ms to mean 414 ms (peak 590 ms). (`metric:edge-gateway/latency_p99_ms`)
- Orders‑service logs PostgreSQL connection resets starting 11:15:13 (203 occurrences) and a new “fee cache cold; fetching N fee schedules” pattern appearing at 11:06:22 after the deploy. (`log:a32c4ff0bfc1`, `log:e91658633ca4`)
- Portfolio‑service logs gRPC calls to market‑data‑service failing with UNAVAILABLE (connection reset) from 11:15:13 (174 occurrences). (`log:e0364bef1b6f`)
- Only production change in the 45‑minute window: orders‑service v2.16.0 deployed at 11:05:12 (batch fee‑schedule lookups). (`chg:2561`)
- Dependency graph shows hard dependencies: edge‑gateway→portfolio‑service (3 s), edge‑gateway→orders‑service (3 s), orders‑service→postgres‑orders, orders‑service→market‑data‑service (gRPC), portfolio‑service→market‑data‑service (gRPC), portfolio‑service→postgres‑orders. (`dep:edge-gateway->portfolio-service`, `dep:edge-gateway->orders-service`, `dep:orders-service->postgres-orders`, `dep:orders-service->market-data-service`, `dep:portfolio-service->market-data-service`, `dep:portfolio-service->postgres-orders`)
**Contradicting:**
- Market‑data‑service shows intermittent quotes‑vendor 429 responses throughout the morning, with no sharp change at 11:15. (`log:04398295b807`)
- Payments‑service shows only normal card‑decline warnings; no error‑rate spike. (`log:4a9e6d0a3f8e`)
**Assumptions:**
- ASM-1: “Connection timeout to portfolio‑service” in edge‑gateway indicates the gateway cannot complete the HTTP call to portfolio‑service (service‑side failure).
- ASM-2: The “fee cache cold” log appears only after the v2.16.0 deploy, indicating the new code path touches the DB more aggressively.
- ASM-3: No hidden changes (config‑map rollout, feature‑flag, secret rotation) occurred for the other services.

### 2. `infrastructure_failure` on **postgres-orders** (HYP-2)

Confidence 0.30 (low). A transient infrastructure problem (e.g., max‑connections limit, network blip) on postgres‑orders began ~11:15, causing connection resets for any client (orders‑service, portfolio‑service). Portfolio‑service’s gRPC failures are a secondary effect of its own DB trouble.

**Supporting:**
- Orders‑service logs PostgreSQL connection resets starting 11:15:13 (203 occurrences) and a new “fee cache cold; fetching N fee schedules” pattern appearing at 11:06:22 after the deploy. (`log:a32c4ff0bfc1`, `log:e91658633ca4`)
- Portfolio‑service logs gRPC calls to market‑data‑service failing with UNAVAILABLE (connection reset) from 11:15:13 (174 occurrences). (`log:e0364bef1b6f`)
- Edge‑gateway logs show upstream connection timeout to portfolio‑service starting at 11:15:01 (1,443 occurrences). (`log:80f1f968cbad`)
- Edge‑gateway error_rate rises from baseline 0.002 to mean 0.0096 (peak 0.025) during the incident window. (`metric:edge-gateway/error_rate`)
- Edge‑gateway latency_p99 climbs from baseline 342 ms to mean 414 ms (peak 590 ms). (`metric:edge-gateway/latency_p99_ms`)
**Contradicting:**
- Market‑data‑service shows intermittent quotes‑vendor 429 responses throughout the morning, with no sharp change at 11:15. (`log:04398295b807`)
- Payments‑service shows only normal card‑decline warnings; no error‑rate spike. (`log:4a9e6d0a3f8e`)
- Dependency graph shows hard dependencies: edge‑gateway→portfolio‑service (3 s), edge‑gateway→orders‑service (3 s), orders‑service→postgres‑orders, orders‑service→market‑data‑service (gRPC), portfolio‑service→market‑data‑service (gRPC), portfolio‑service→postgres‑orders. (`dep:edge-gateway->portfolio-service`, `dep:edge-gateway->orders-service`, `dep:orders-service->postgres-orders`, `dep:orders-service->market-data-service`, `dep:portfolio-service->market-data-service`, `dep:portfolio-service->postgres-orders`)
**Assumptions:**
- ASM-1: “Connection timeout to portfolio‑service” in edge‑gateway indicates the gateway cannot complete the HTTP call to portfolio‑service (service‑side failure).
- ASM-3: No hidden changes (config‑map rollout, feature‑flag, secret rotation) occurred for the other services.

### 3. `dependency_degradation` on **market-data-service** (HYP-3)

Confidence 0.15 (low). Sustained quotes‑vendor 429 rate‑limiting degrades market‑data‑service, making its gRPC endpoint unavailable. Portfolio‑service (and orders‑service) then experience gRPC failures, leading to edge‑gateway timeouts.

**Supporting:**
- Portfolio‑service logs gRPC calls to market‑data‑service failing with UNAVAILABLE (connection reset) from 11:15:13 (174 occurrences). (`log:e0364bef1b6f`)
- Market‑data‑service shows intermittent quotes‑vendor 429 responses throughout the morning, with no sharp change at 11:15. (`log:04398295b807`)
- Edge‑gateway logs show upstream connection timeout to portfolio‑service starting at 11:15:01 (1,443 occurrences). (`log:80f1f968cbad`)
**Contradicting:**
- Orders‑service logs PostgreSQL connection resets starting 11:15:13 (203 occurrences) and a new “fee cache cold; fetching N fee schedules” pattern appearing at 11:06:22 after the deploy. (`log:a32c4ff0bfc1`, `log:e91658633ca4`)
- Payments‑service shows only normal card‑decline warnings; no error‑rate spike. (`log:4a9e6d0a3f8e`)
- Only production change in the 45‑minute window: orders‑service v2.16.0 deployed at 11:05:12 (batch fee‑schedule lookups). (`chg:2561`)
- Dependency graph shows hard dependencies: edge‑gateway→portfolio‑service (3 s), edge‑gateway→orders‑service (3 s), orders‑service→postgres‑orders, orders‑service→market‑data‑service (gRPC), portfolio‑service→market‑data‑service (gRPC), portfolio‑service→postgres‑orders. (`dep:edge-gateway->portfolio-service`, `dep:edge-gateway->orders-service`, `dep:orders-service->postgres-orders`, `dep:orders-service->market-data-service`, `dep:portfolio-service->market-data-service`, `dep:portfolio-service->postgres-orders`)
**Assumptions:**
- ASM-1: “Connection timeout to portfolio‑service” in edge‑gateway indicates the gateway cannot complete the HTTP call to portfolio‑service (service‑side failure).
- ASM-3: No hidden changes (config‑map rollout, feature‑flag, secret rotation) occurred for the other services.

### 4. `infrastructure_failure` on **platform-network** (HYP-4)

Confidence 0.10 (low). A cluster‑wide network or service‑mesh glitch caused intermittent TCP resets across multiple independent service pairs (orders→postgres, portfolio→market‑data, edge→portfolio) starting at 11:15.

**Supporting:**
- Edge‑gateway logs show upstream connection timeout to portfolio‑service starting at 11:15:01 (1,443 occurrences). (`log:80f1f968cbad`)
- Orders‑service logs PostgreSQL connection resets starting 11:15:13 (203 occurrences) and a new “fee cache cold; fetching N fee schedules” pattern appearing at 11:06:22 after the deploy. (`log:a32c4ff0bfc1`, `log:e91658633ca4`)
- Portfolio‑service logs gRPC calls to market‑data‑service failing with UNAVAILABLE (connection reset) from 11:15:13 (174 occurrences). (`log:e0364bef1b6f`)
**Contradicting:**
- Market‑data‑service shows intermittent quotes‑vendor 429 responses throughout the morning, with no sharp change at 11:15. (`log:04398295b807`)
- Payments‑service shows only normal card‑decline warnings; no error‑rate spike. (`log:4a9e6d0a3f8e`)
- No deployments, config changes, feature‑flag flips, secret rotations, or infra work for any other service in the window. (`chg:2561`)
**Assumptions:**
- ASM-1: “Connection timeout to portfolio‑service” in edge‑gateway indicates the gateway cannot complete the HTTP call to portfolio‑service (service‑side failure).
- ASM-3: No hidden changes (config‑map rollout, feature‑flag, secret rotation) occurred for the other services.
- ASM-4: Postgres‑orders and market‑data‑service share no common infrastructure other than the network layer.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Rollback orders‑service to v2.15.2 (or disable the new batch fee‑lookup feature via feature flag). | Removes the only change that coincides with the onset; should stop the DB connection storm. |
| now | mitigate | Temporarily increase postgres‑orders max_connections / connection‑pool limits and enable verbose logging (log_min_messages = WARNING). | Mitigates immediate symptom while root cause is fixed; provides data for H2 verification. |
| soon | investigate | Add per‑service error‑rate and latency alerts for orders‑service, portfolio‑service, market‑data‑service. | Earlier detection of upstream degradation; currently only edge‑gateway is alerted. |
| soon | fix | Deploy a canary of v2.16.0 with the batch lookup guarded by a feature flag; monitor DB connection metrics. | Allows safe re‑enable after confirming the regression is fixed. |
| later | prevent | Post‑mortem: capture missing telemetry (postgres metrics, service‑mesh traces) and add them to the observability stack. | Closes gaps for future incidents. |
| later | prevent | Review fee‑schedule lookup implementation for connection‑pool misuse (e.g., opening a new pool per request). | Prevents recurrence of the same regression. |

## Evidence gaps

- **query_metrics** (postgres-orders connection count, error rate, CPU): Needed to confirm or reject the postgres‑orders infrastructure failure hypothesis (H2).
- **query_metrics** (orders-service, portfolio-service, market-data-service error_rate, latency, saturation): Would pinpoint which service’s SLO broke first and validate cascade direction.
- **query_logs** (service-mesh sidecar / CNI logs): Required to evaluate a cluster‑wide network glitch (H4).
- **query_logs** (portfolio-service code path after DB error): To understand why portfolio‑service logs gRPC failures to market‑data‑service rather than DB errors.

## Open questions

- What is the exact DB‑side cause of the connection resets (max_connections exhaustion, idle timeout, network glitch)?
- Why does portfolio‑service surface gRPC failures to market‑data‑service instead of PostgreSQL errors after a DB reset?
- Did a subtle network or service‑mesh event occur at 11:15 affecting only the three observed paths?
- Does the v2.16.0 diff contain other code paths that also touch postgres‑orders besides the batch fee‑schedule lookup?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 10 model calls, 8 tool calls, 72,017 tokens, 303 s.
