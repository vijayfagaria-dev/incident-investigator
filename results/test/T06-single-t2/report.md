# T06: Intermittent errors across the app

**Outcome:** conclusive. Root cause: `dependency_degradation` on **portfolio-service**

## Summary

Starting at ~11:15 UTC the edge‑gateway error rate jumped from ~0.2 % to ~2 % and its p99 latency rose sharply. Gateway logs show thousands of “connection timeout to portfolio‑service” errors. Portfolio‑service logs show a matching burst of gRPC “UNAVAILABLE (connection reset)” failures when calling market‑data‑service, yet market‑data‑service’s own error rate and latency stay at baseline. The only code change in the window is the orders‑service v2.16.0 deploy at 11:05, which correlates with a modest rise in orders‑service error rate but does not explain the gateway timeouts to portfolio‑service. The evidence points to a degradation in the portfolio‑service → market‑data‑service path (likely a transient network or downstream issue) that stalls portfolio‑service, causing gateway timeouts and the observed 2 % error spike.

## Hypotheses

### 1. `dependency_degradation` on **portfolio-service** (HYP-1)

Confidence 0.55 (medium). Portfolio‑service gRPC calls to market‑data‑service start failing (connection resets). Portfolio‑service blocks or retries, exceeding the gateway's 3 s timeout, so edge‑gateway returns 502/timeout errors. The gateway error spike is a symptom of the downstream stall.

**Supporting:**
- edge‑gateway logs show 619 “upstream connect error … connection timeout to portfolio‑service” errors starting 11:15:01 UTC (`log:80f1f968cbad`)
- portfolio‑service logs show 78 “gRPC call to market‑data‑service failed: UNAVAILABLE (connection reset)” warnings starting 11:15:13 UTC (`log:e0364bef1b6f`)
**Contradicting:**
- market‑data‑service error_rate stays at baseline (~0.0019) throughout the window (`metric:market-data-service/error_rate`)
- portfolio‑service latency_p99 shows no sustained increase (remains ~400‑500 ms) (`metric:portfolio-service/latency_p99_ms`)
**Assumptions:**
- ASM-1: Gateway timeouts to portfolio‑service indicate portfolio‑service is not responding within the 3 s gateway timeout
- ASM-2: Portfolio‑service stalls because its gRPC calls to market‑data‑service are failing (connection reset)

### 2. `code_regression` on **orders-service**, triggered by `chg:2561` (HYP-2)

Confidence 0.35 (low). The v2.16.0 deploy introduced a bug that raises orders‑service error rate; edge‑gateway also calls orders‑service (hard dependency, 3 s timeout) so some gateway errors could stem from orders‑service latency/errors.

**Supporting:**
- orders‑service error_rate baseline ≈0.0018, rises to 0.006‑0.009 from 11:15 UTC (`metric:orders-service/error_rate`)
- Only change in the 45‑minute window is orders‑service deploy v2.16.0 at 11:05:12 UTC (chg:2561) (`chg:2561`)
**Contradicting:**
- edge‑gateway logs show 619 “upstream connect error … connection timeout to portfolio‑service” errors starting 11:15:01 UTC (`log:80f1f968cbad`)
- edge‑gateway latency_p99 rises from ~342 ms baseline to 500‑590 ms starting at 11:15 UTC (`metric:edge-gateway/latency_p99_ms`)
**Assumptions:**
- ASM-3: Orders‑service v2.16.0 introduced a regression that raises its own error rate

### 3. `infrastructure_failure` on **network** (HYP-3)

Confidence 0.30 (low). A brief network disruption (e.g., packet loss or routing flap) affects the specific VPC links between gateway↔portfolio‑service and portfolio‑service↔market‑data‑service, causing connection resets and timeouts while other paths stay healthy.

**Supporting:**
- edge‑gateway logs show 619 “upstream connect error … connection timeout to portfolio‑service” errors starting 11:15:01 UTC (`log:80f1f968cbad`)
- portfolio‑service logs show 78 “gRPC call to market‑data‑service failed: UNAVAILABLE (connection reset)” warnings starting 11:15:13 UTC (`log:e0364bef1b6f`)
**Contradicting:**
- market‑data‑service error_rate stays at baseline (~0.0019) throughout the window (`metric:market-data-service/error_rate`)
- portfolio‑service error_rate remains at baseline (~0.002) throughout the window (`metric:portfolio-service/error_rate`)
- payments‑service error_rate stays at baseline (~0.002) throughout the window (`metric:payments-service/error_rate`)
**Assumptions:**
- ASM-4: A transient network issue could selectively affect the portfolio‑service ↔ market‑data‑service and gateway ↔ portfolio‑service paths

### 4. `unknown` on **unknown** (HYP-4)

Confidence 0.10 (low). The observed pattern could be a client‑side or reporting artifact; insufficient data to pinpoint a single internal cause.

**Contradicting:**
- edge‑gateway error_rate baseline ≈0.002, spikes to 0.018‑0.023 beginning at 11:15 UTC (`metric:edge-gateway/error_rate`)
- edge‑gateway logs show 619 “upstream connect error … connection timeout to portfolio‑service” errors starting 11:15:01 UTC (`log:80f1f968cbad`)
- portfolio‑service logs show 78 “gRPC call to market‑data‑service failed: UNAVAILABLE (connection reset)” warnings starting 11:15:13 UTC (`log:e0364bef1b6f`)

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Raise edge‑gateway timeout for portfolio‑service (e.g., from 3 s to 5 s) and enable a circuit‑breaker fallback to serve stale portfolio data. | Immediately reduces 502 responses while root cause is investigated (addresses symptom F7). |
| soon | investigate | Enable distributed tracing for the gateway → portfolio‑service → market‑data‑service path and capture gRPC status codes. | Will confirm whether portfolio‑service stalls on market‑data‑service calls (supports H1). |
| soon | investigate | Review network flow logs / VPC metrics for the ENIs used by portfolio‑service and gateway during 11:15‑11:30. | Tests the infrastructure‑failure hypothesis (H3). |
| later | fix | If tracing shows market‑data‑service gRPC resets, work with market‑data team to harden the gRPC server (connection pooling, health checks) and add retry/back‑off in portfolio‑service. | Addresses the dependency degradation root cause (H1). |
| later | prevent | Add canary deployment and automated error‑rate alerts for orders‑service to catch regressions like v2.16.0 earlier. | Mitigates future code‑regression risk (H2). |

## Evidence gaps

- **query_logs** (orders-service, market-data-service (WARN+)): Logs for these services were not retrieved; they could reveal errors or retries that explain the orders‑service error rise or confirm market‑data‑service health.
- **query_metrics** (per‑minute granularity for error_rate and latency on all services): Current step is 3 minutes; finer granularity would pinpoint exact onset minute for each service.
- **query_logs** (network / VPC flow logs or cloud provider network health metrics): No network‑level evidence collected; needed to validate hypothesis H3.
- **search_incident_history** (past incidents involving portfolio‑service ↔ market‑data‑service gRPC failures): Analogous incidents could inform whether this is a known failure mode.

## Open questions

- What exact gRPC error codes does market‑data‑service return during the failure window?
- Do VPC flow logs show packet loss or latency spikes on the specific subnet links at 11:15‑11:30?
- Why does portfolio‑service error_rate stay at baseline while its upstream calls fail?
- Is the orders‑service error increase purely coincidental or does it contribute to any gateway errors not captured in the timeout logs?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 13 model calls, 12 tool calls, 116,103 tokens, 499 s.
