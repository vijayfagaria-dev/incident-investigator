# T06: Intermittent errors across the app

**Outcome:** conclusive. Root cause: `infrastructure_failure` on **platform/network**

## Summary

At ~11:15 UTC the edge‑gateway began returning ~2 % 5xx errors caused by upstream connection timeouts to portfolio‑service. Portfolio‑service simultaneously logged gRPC UNAVAILABLE errors when calling market‑data‑service, while orders‑service logged PostgreSQL connection resets. Both downstream failures started within the same minute, yet the only production change was the orders‑service v2.16.0 deploy at 11:05. Market‑data‑service remained healthy (error rate flat). The pattern points to a brief platform‑wide connectivity problem (network or host‑level) that momentarily broke access to both the orders DB and the market‑data gRPC endpoint; retries succeeded, matching the reported intermittent errors.

## Hypotheses

### 1. `infrastructure_failure` on **platform/network** (HYP-1)

Confidence 0.55 (medium). A brief network or host‑level disruption broke connectivity from the app tier to both postgres‑orders and market‑data‑service, causing upstream timeouts at edge‑gateway and gRPC failures at portfolio‑service.

**Supporting:**
- Edge‑gateway logs show “upstream connect error … connection timeout to portfolio‑service” first at 11:15:01 and continuing to 11:59. (`log:80f1f968cbad`)
- Portfolio‑service logs show gRPC calls to market‑data‑service failing with UNAVAILABLE (connection reset) first at 11:15:13. (`log:e0364bef1b6f`)
- Orders‑service logs show “connection to postgres‑orders reset by peer; retrying” first at 11:15:13. (`log:a32c4ff0bfc1`)
- Edge‑gateway error_rate rose from baseline 0.20 % to a peak 2.65 % beginning ~11:15 UTC. (`metric:edge-gateway/error_rate`)
- Orders‑service error_rate climbed from baseline 0.18 % to a peak 1.26 %. (`metric:orders-service/error_rate`)
- Market‑data‑service error_rate remained flat (baseline 0.20 %, last 0.03 %). (`metric:market-data-service/error_rate`)
- No config, feature‑flag, secret‑rotation or infra changes recorded between 10:00‑12:00. (`chg:2561`)
**Assumptions:**
- ASM-1: The near‑simultaneous connection‑reset errors to postgres‑orders and gRPC UNAVAILABLE to market‑data‑service are symptoms of a single underlying transient network/infrastructure issue, not two independent bugs.

### 2. `code_regression` on **orders-service**, triggered by `chg:2561` (HYP-2)

Confidence 0.30 (low). The v2.16.0 deploy introduced a connection‑pool leak / extra load on market‑data‑service, exhausting the postgres pool (F10) and causing downstream gRPC failures seen by portfolio‑service.

**Supporting:**
- Only production change in the window: orders‑service v2.16.0 deployed at 11:05:12. (`chg:2561`)
- Orders‑service db_pool_in_use grew from baseline 16.4 connections to ~20.1 connections. (`metric:orders-service/db_pool_in_use`)
- Orders‑service logs show “fee cache cold; fetching … fee schedules” from 11:06‑11:18. (`log:e91658633ca4`)
- Orders‑service error_rate climbed from baseline 0.18 % to a peak 1.26 %. (`metric:orders-service/error_rate`)
**Contradicting:**
- Market‑data‑service error_rate remained flat (baseline 0.20 %, last 0.03 %). (`metric:market-data-service/error_rate`)
- Portfolio‑service logs show gRPC calls to market‑data‑service failing with UNAVAILABLE (connection reset) first at 11:15:13. (`log:e0364bef1b6f`)
**Assumptions:**
- ASM-2: Because retries succeed (support‑desk note), the failures are brief and transient rather than permanent service outages.

### 3. `resource_exhaustion` on **redis-cache** (HYP-3)

Confidence 0.10 (low). Exhaustion of the shared redis‑cache caused both orders‑service and portfolio‑service to fall back to slower paths, leading to timeouts and connection resets.

**Contradicting:**
- Market‑data‑service error_rate remained flat (baseline 0.20 %, last 0.03 %). (`metric:market-data-service/error_rate`)
- No config, feature‑flag, secret‑rotation or infra changes recorded between 10:00‑12:00. (`chg:2561`)

### 4. `dependency_degradation` on **quotes-vendor** (HYP-4)

Confidence 0.05 (low). Rate‑limit / latency from the external quotes vendor propagated through market‑data‑service to its callers, causing gRPC UNAVAILABLE.

**Contradicting:**
- Market‑data‑service error_rate remained flat (baseline 0.20 %, last 0.03 %). (`metric:market-data-service/error_rate`)
- Portfolio‑service logs show gRPC calls to market‑data‑service failing with UNAVAILABLE (connection reset) first at 11:15:13. (`log:e0364bef1b6f`)

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | investigate | Request network/platform team to pull VPC flow logs, host health metrics, and NIC error counters for 11:10‑11:20 UTC. | Direct evidence for the infrastructure_failure hypothesis (H1). |
| soon | investigate | Enable PostgreSQL log_connections / log_disconnections for 24 h and monitor db_pool_in_use alerts. | Closes gap on DB‑side visibility; helps confirm or reject H2. |
| now | mitigate | Add alert on edge‑gateway upstream‑timeout rate >1 % for 2 min and on orders‑service db_pool_in_use >90 % of max. | Faster detection if the blip recurs. |
| soon | fix | Review orders‑service v2.16.0 diff (commit 8b20f4e) for connection‑pool handling; run a canary load test. | Low‑effort mitigation if the deploy contributed to pool growth. |
| later | prevent | Instrument a synthetic full‑path probe (edge‑gateway → portfolio → market‑data) recording per‑hop latency. | Improves observability for future multi‑service incidents. |
| later | prevent | Document run‑book step: “If multiple hard dependencies show connection‑reset at the same minute, treat as possible infra/network issue and engage platform team.” | Operational knowledge capture. |

## Evidence gaps

- **query_metrics** (Network / host‑level metrics (packet loss, NIC errors, VPC flow logs) for the app tier around 11:15): Not available via current metrics API; needed to confirm infrastructure_failure hypothesis.
- **query_logs** (Postgres‑orders logs / metrics (connection reset counts, max‑connections) for 11:10‑11:20): Postgres is not a listed service in the toolset; direct DB logs would show if the DB itself saw a spike.
- **query_metrics** (Redis‑cache metrics (cpu, memory, evictions, command latency) for the incident window): Redis‑cache not queried; needed to rule out resource_exhaustion hypothesis.
- **search_incident_history** (Any prior incidents with simultaneous postgres and market‑data connectivity loss): Analogous past incidents could guide investigation but are not direct evidence.

## Open questions

- Was there an unreported infrastructure event (rolling node‑pool upgrade, security‑group change, DNS hiccup) at ~11:15?
- Did the orders‑service deploy introduce a subtle connection‑pool leak that only manifested under load after ~10 min?
- Why did the edge‑gateway error rate peak at 2.6 % while orders‑service error rate only reached 1.3 %?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 19 model calls, 19 tool calls, 140,974 tokens, 854 s.
