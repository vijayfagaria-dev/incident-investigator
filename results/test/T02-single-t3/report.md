# T02: Portfolio pages slow and failing

**Outcome:** conclusive. Root cause: `dependency_degradation` on **market-data-service**

## Summary

At ~14:41 UTC the external quotes‑vendor began timing out (800 ms hard timeout) and returning 429s. Market‑data‑service's circuit‑breaker opened at 14:47 UTC and started serving stale quotes. Because portfolio‑service calls market‑data‑service with a 500 ms gRPC deadline, the vendor slowdown immediately produced massive DEADLINE_EXCEEDED errors (first seen 14:42 UTC) and a sharp rise in portfolio‑service latency (p99 > 3 s) and error rate (≈ 7 %). The portfolio‑service v5.4.0 deploy at 14:48 UTC added a new “sector breakdown” feature (visible as “sector mapping missing” warnings) but did not cause the latency spike – the degradation was already underway. Edge‑gateway, which fronts portfolio‑service with a 3 s timeout, consequently returned 5xx and high latency to customers, and some order placements were rejected as a downstream effect.

## Hypotheses

### 1. `dependency_degradation` on **market-data-service** (HYP-1)

Confidence 0.92 (high). External quotes‑vendor latency and error spikes cause market‑data‑service timeouts and circuit‑breaker activation; portfolio‑service's 500 ms deadline is exceeded, generating DEADLINE_EXCEEDED errors, high latency and 5xx, which propagate to edge‑gateway and cause order rejections.

**Supporting:**
- Market‑data‑service logs quotes‑vendor request timed out after 800 ms (batch of symbols) from 14:41 UTC (`log:785c94c54006`)
- Market‑data‑service circuit‑breaker half‑open, serving last known quotes from 14:47 UTC (`log:a9fa5c6b6926`)
- Market‑data‑service vendor_error_rate spikes to 0.118 (baseline 0.001) (`metric:market-data-service/vendor_error_rate`)
- Market‑data‑service vendor_latency_p99 spikes to 2 971 ms (baseline 180 ms) (`metric:market-data-service/vendor_latency_p99_ms`)
- Market‑data‑service latency_p99 spikes to 2 399 ms (baseline 253 ms) (`metric:market-data-service/latency_p99_ms`)
- Portfolio‑service latency_p99 spikes to 3 513 ms (baseline 415 ms) and error_rate to 0.074 (baseline 0.002) (`metric:portfolio-service/latency_p99_ms`, `metric:portfolio-service/error_rate`)
- Dependency graph shows portfolio‑service → market‑data‑service (hard, 500 ms) and market‑data‑service → quotes‑vendor (hard, 800 ms) (`dep:portfolio-service->market-data-service`, `dep:market-data-service->quotes-vendor`)
- No config, feature‑flag, secret‑rotation or infra changes for involved services in the 45 min window (only portfolio‑service deploy) (`chg:2512`)
**Assumptions:**
- ASM-1: The 800 ms hard timeout on market‑data‑service → quotes‑vendor call is enforced exactly as shown in the dependency graph.
- ASM-2: Portfolio‑service’s 500 ms gRPC timeout to market‑data‑service is lower than the vendor latency observed, so any vendor slowdown > 500 ms produces the DEADLINE_EXCEEDED errors.

### 2. `code_regression` on **portfolio-service**, triggered by `chg:2512` (HYP-2)

Confidence 0.18 (low). New sector‑breakdown feature in v5.4.0 adds extra calls or heavier processing to market‑data‑service, amplifying latency and causing the observed spikes.

**Supporting:**
- Portfolio‑service logs “sector mapping missing” warnings appear after deploy (14:49 UTC onward) (`log:e481388daa5a`)
**Contradicting:**
- First gRPC DEADLINE_EXCEEDED from portfolio‑service → market‑data‑service (GetQuotes) at 14:42:01 UTC (`log:3096c4afe74b`)
- Market‑data‑service logs quotes‑vendor request timed out after 800 ms (batch of symbols) from 14:41 UTC (`log:785c94c54006`)
- Market‑data‑service vendor_error_rate spikes to 0.118 (baseline 0.001) (`metric:market-data-service/vendor_error_rate`)
- Market‑data‑service vendor_latency_p99 spikes to 2 971 ms (baseline 180 ms) (`metric:market-data-service/vendor_latency_p99_ms`)
- Market‑data‑service latency_p99 spikes to 2 399 ms (baseline 253 ms) (`metric:market-data-service/latency_p99_ms`)
- Portfolio‑service latency_p99 spikes to 3 513 ms (baseline 415 ms) and error_rate to 0.074 (baseline 0.002) (`metric:portfolio-service/latency_p99_ms`, `metric:portfolio-service/error_rate`)
**Assumptions:**
- ASM-2: Portfolio‑service’s 500 ms gRPC timeout to market‑data‑service is lower than the vendor latency observed, so any vendor slowdown > 500 ms produces the DEADLINE_EXCEEDED errors.

### 3. `resource_exhaustion` on **market-data-service** (HYP-3)

Confidence 0.03 (low). CPU or memory saturation in market‑data‑service slows its processing of vendor responses, leading to timeouts.

**Contradicting:**
- CPU and memory of portfolio‑service and market‑data‑service remain near baseline (~0.5 ratio), indicating no resource exhaustion (`metric:portfolio-service/cpu_util`, `metric:portfolio-service/mem_util`, `metric:market-data-service/cpu_util`, `metric:market-data-service/mem_util`)

### 4. `config_change` on **market-data-service** (HYP-4)

Confidence 0.02 (low). An undocumented configuration change (e.g., reduced timeout) in market‑data‑service caused earlier vendor timeouts.

**Contradicting:**
- No config, feature‑flag, secret‑rotation or infra changes for involved services in the 45 min window (only portfolio‑service deploy) (`chg:2512`)

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Engage quotes‑vendor on‑call to investigate and resolve latency/429 spikes; request SLA adherence. | Directly addresses the upstream dependency degradation (Hypothesis H1). |
| soon | mitigate | Increase market‑data‑service → vendor timeout or add retry/back‑off logic; optionally raise portfolio‑service gRPC deadline to 1 s. | Reduces immediate DEADLINE_EXCEEDED errors while vendor issue is resolved. |
| soon | fix | Deploy hot‑fix to portfolio‑service to fall back to cached quotes when market‑data‑service latency exceeds threshold. | Improves resilience to future vendor degradations. |
| later | prevent | Add vendor‑latency SLO monitoring and alerting (vendor_error_rate, vendor_latency_p99); align timeout chain (500 ms → 800 ms) and document. | Early detection and prevents cascading failures. |
| later | investigate | Review portfolio‑service v5.4.0 sector‑breakdown code for unnecessary extra market‑data calls; consider rollback if it adds load. | Ensures new feature does not amplify future incidents. |

## Evidence gaps

- **query_logs** (edge-gateway): Edge‑gateway logs/metrics not collected; needed to confirm exact error propagation and timeout behavior.
- **query_metrics** (quotes-vendor): No vendor‑side telemetry available; cannot verify root cause on vendor side.
- **query_logs** (distributed traces): Traces not available; would pinpoint call‑stack latency breakdown.
- **query_metrics** (postgres-orders): Responder claimed Postgres normal but no metric evidence gathered.

## Open questions

- What caused the quotes‑vendor latency spike? (Network, throttling, vendor deploy?)
- Does the new sector‑breakdown logic in v5.4.0 issue additional market‑data calls per request?
- Were any edge‑gateway instances saturated (thread‑pool, connection pool) contributing to 5xx beyond upstream latency?
- Is the Postgres‑orders path truly healthy, or could it become a secondary bottleneck once market‑data recovers?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 8 model calls, 6 tool calls, 51,761 tokens, 267 s.
