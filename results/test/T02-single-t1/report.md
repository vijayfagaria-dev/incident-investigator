# T02: Portfolio pages slow and failing

**Outcome:** conclusive. Root cause: `dependency_degradation` on **market-data-service**, triggered by `metric:market-data-service/vendor_latency_p99_ms`

## Summary

Starting at ~14:42 UTC the external quotes‑vendor began returning high latency (p99 ≈ 3 s) and elevated error rates. market‑data‑service propagated this degradation (p99 ≈ 2.4 s, error‑rate ≈ 4.5 %). portfolio‑service gRPC calls to market‑data‑service (500 ms deadline) began timing out in large numbers (679 DEADLINE_EXCEEDED errors), driving portfolio‑service p99 latency >3 s and 5xx error‑rate ~7 %. The portfolio‑service v5.4.0 deploy at 14:48 UTC arrived after the onset and only added sector‑mapping warnings; it is not the root cause but may have added modest extra load. Edge‑gateway remains healthy.

## Hypotheses

### 1. `dependency_degradation` on **market-data-service**, triggered by `metric:market-data-service/vendor_latency_p99_ms` (HYP-1)

Confidence 0.86 (high). External quotes‑vendor latency/error increase causes market‑data‑service to exceed its 500 ms gRPC deadline, leading to portfolio‑service timeouts and 5xx errors.

**Supporting:**
- First gRPC DEADLINE_EXCEEDED from portfolio‑service to market‑data‑service observed at 14:42:01 UTC; 679 occurrences total. (`log:3096c4afe74b`)
- market‑data‑service p99 latency rose from baseline ~253 ms to 2399 ms and error‑rate from 0.19 % to 4.6 % in the same window. (`metric:market-data-service/latency_p99_ms`, `metric:market-data-service/error_rate`)
- market‑data‑service vendor_error_rate peaked at 11.8 % (baseline 0.1 %) and vendor_latency_p99_ms peaked at 2933 ms (baseline 181 ms). (`metric:market-data-service/vendor_error_rate`, `metric:market-data-service/vendor_latency_p99_ms`)
- edge‑gateway latency (p99 ~350 ms) and error‑rate (~1.5 %) stayed near baseline throughout. (`metric:edge-gateway/latency_p99_ms`, `metric:edge-gateway/error_rate`)
- CPU and memory utilisation for both portfolio‑service and market‑data‑service remain flat (~50 % CPU, ~55 % mem). (`metric:portfolio-service/cpu_util`, `metric:portfolio-service/mem_util`, `metric:market-data-service/cpu_util`, `metric:market-data-service/mem_util`)
**Assumptions:**
- ASM-1: The quotes‑vendor latency/error spike is external and not caused by our services.

### 2. `code_regression` on **portfolio-service**, triggered by `chg:2512` (HYP-2)

Confidence 0.18 (low). v5.4.0 introduces extra/heavier calls to market‑data‑service (sector breakdown), increasing load and causing gRPC deadline exceedances.

**Supporting:**
- portfolio‑service p99 latency rose from a baseline of ~415 ms to a peak of 3513 ms and error‑rate rose from 0.22 % to 7.4 % between 14:42 UTC and 15:05 UTC. (`metric:portfolio-service/latency_p99_ms`, `metric:portfolio-service/error_rate`)
- Only production change in the window: portfolio‑service v5.4.0 deployed at 14:48:30 UTC (adds sector breakdown). (`chg:2512`)
- 'Sector mapping missing' warnings in portfolio‑service start at 14:49 UTC, after the deploy. (`log:e481388daa5a`)
**Contradicting:**
- First gRPC DEADLINE_EXCEEDED from portfolio‑service to market‑data‑service observed at 14:42:01 UTC; 679 occurrences total. (`log:3096c4afe74b`)
- market‑data‑service p99 latency rose from baseline ~253 ms to 2399 ms and error‑rate from 0.19 % to 4.6 % in the same window. (`metric:market-data-service/latency_p99_ms`, `metric:market-data-service/error_rate`)
- market‑data‑service vendor_error_rate peaked at 11.8 % (baseline 0.1 %) and vendor_latency_p99_ms peaked at 2933 ms (baseline 181 ms). (`metric:market-data-service/vendor_error_rate`, `metric:market-data-service/vendor_latency_p99_ms`)
**Assumptions:**
- ASM-2: Portfolio‑service v5.4.0 only adds UI‑side sector breakdown and does not alter the gRPC call path before 14:48 UTC.

### 3. `resource_exhaustion` on **market-data-service** (HYP-3)

Confidence 0.07 (low). Hidden saturation (e.g., gRPC thread pool, DB connection pool) in market‑data‑service causes latency rise despite flat CPU/memory.

**Supporting:**
- market‑data‑service p99 latency rose from baseline ~253 ms to 2399 ms and error‑rate from 0.19 % to 4.6 % in the same window. (`metric:market-data-service/latency_p99_ms`, `metric:market-data-service/error_rate`)
**Contradicting:**
- CPU and memory utilisation for both portfolio‑service and market‑data‑service remain flat (~50 % CPU, ~55 % mem). (`metric:portfolio-service/cpu_util`, `metric:portfolio-service/mem_util`, `metric:market-data-service/cpu_util`, `metric:market-data-service/mem_util`)
**Assumptions:**
- ASM-3: Market‑data‑service has no hidden bottleneck (e.g., connection pool) that would appear without CPU/memory rise.

### 4. `config_change` on **market-data-service** (HYP-4)

Confidence 0.04 (low). An untracked configuration change or feature flag in market‑data‑service altered its vendor‑call behaviour, producing the observed spike.

**Contradicting:**
- No config, feature‑flag, secret‑rotation or infra changes for market‑data‑service, orders‑service, auth‑service, payments‑service or edge‑gateway in the 45‑min window. (`chg:2512`)
**Assumptions:**
- ASM-4: Change‑history tool captures all production changes; none missing for market‑data‑service.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll back portfolio‑service to v5.3.2 (or pause v5.4.0 rollout). | Removes any possible aggravation from the new deploy; low risk and immediate. |
| now | mitigate | Add a circuit‑breaker / increase gRPC timeout (e.g., 1 s) on portfolio‑service → market‑data‑service with cached‑quote fallback. | Prevents cascade while vendor stabilises; directly addresses H1 timeout path. |
| now | investigate | Open a support ticket with the quotes‑vendor and request their status page / incident details for 14:40‑15:05 UTC. | Confirms external vendor degradation (H1) and may provide ETA for resolution. |
| soon | investigate | Pull market‑data‑service ERROR/WARN logs for 14:30‑15:05 UTC to verify server‑side gRPC latency and any pool exhaustion. | Closes gap G1 and discriminates between H1 and H3. |
| later | prevent | Add alerting on market‑data‑service vendor_latency_p99_ms and vendor_error_rate with low thresholds. | Early detection of future vendor issues before they cascade. |
| later | prevent | Review portfolio‑service v5.4.0 code for any new market‑data calls; guard them with the same circuit‑breaker if re‑enabled. | Ensures the sector‑breakdown feature cannot re‑introduce load spikes. |

## Evidence gaps

- **query_logs** (market-data-service ERROR/WARN logs 14:30‑15:05 UTC): Need server‑side gRPC latency and any thread‑pool exhaustion traces to confirm H1/H3.
- **query_metrics** (quotes‑vendor SLA / latency dashboard): Direct vendor evidence of the external spike (H1).
- **query_logs** (portfolio-service request traces (if available)): Determine whether v5.4.0 adds extra market‑data calls after 14:48 (H2).
- **get_change_history** (Infrastructure/network changes affecting market‑data‑service → vendor path): Rule out hidden infra change (H4).

## Open questions

- Did the quotes‑vendor experience a known outage or deployment at ~14:40 UTC?
- Does market‑data‑service have any hidden saturation (connection pool, gRPC thread pool) not visible in CPU/memory metrics?
- Does the new sector‑breakdown feature in v5.4.0 issue additional GetQuotes calls per request?
- Were there any network‑path changes (firewall rule, DNS) that could have increased latency to the vendor?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 8 model calls, 6 tool calls, 53,272 tokens, 230 s.
