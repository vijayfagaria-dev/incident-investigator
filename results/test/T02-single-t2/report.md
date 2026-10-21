# T02: Portfolio pages slow and failing

**Outcome:** conclusive. Root cause: `dependency_degradation` on **quotes-vendor**

## Summary

Starting ~14:41 UTC the external quotes‑vendor began responding slower than the 800 ms hard timeout configured in market‑data‑service. This caused market‑data‑service to time‑out and return errors to portfolio‑service, which then hit its 500 ms gRPC deadline and surfaced DEADLINE_EXCEEDED errors. Edge‑gateway subsequently timed out on its 3 s upstream call to portfolio‑service, producing the observed 5xx responses and high p99 latency on /v1/portfolio. A deploy of portfolio‑service v5.4.0 at 14:48 UTC added a sector‑breakdown feature that increased call volume to market‑data‑service and generated “sector mapping missing” warnings, worsening the symptom after onset but not causing it.

## Hypotheses

### 1. `dependency_degradation` on **quotes-vendor** (HYP-1)

Confidence 0.88 (high). Vendor latency exceeds the 800 ms hard timeout, causing market‑data‑service to return errors, which cascade to portfolio‑service (500 ms gRPC deadline) and finally to edge‑gateway (3 s upstream timeout).

**Supporting:**
- Portfolio‑service starts returning gRPC DEADLINE_EXCEEDED to market‑data‑service at 14:42 UTC (679 occurrences). (`log:3096c4afe74b`)
- Market‑data‑service logs show quotes‑vendor request time‑outs (800 ms) from 14:41 UTC (1 072 occurrences) and circuit‑breaker half‑open from 14:47 UTC. (`log:785c94c54006`, `log:a9fa5c6b6926`)
- Edge‑gateway reports upstream portfolio‑service time‑outs (3 s) from 14:43 UTC (300 occurrences). (`log:5eba6c3c8e7a`)
- Portfolio‑service error‑rate jumps from ~0.2 % baseline to >5 % and p99 latency rises from ~415 ms to >3 s during the same window. (`metric:portfolio-service/error_rate`, `metric:portfolio-service/latency_p99_ms`)
- Dependency time‑outs: market‑data‑service→quotes‑vendor 800 ms (hard), portfolio‑service→market‑data‑service 500 ms (hard), edge‑gateway→portfolio‑service 3 s (hard). (`dep:market-data-service->quotes-vendor`, `dep:portfolio-service->market-data-service`, `dep:edge-gateway->portfolio-service`)
**Assumptions:**
- ASM-1: Market‑data‑service enforces the 800 ms hard timeout to quotes‑vendor as defined in the dependency graph.
- ASM-2: Change‑history capture is complete for the window (no hidden config/feature‑flag changes).

### 2. `code_regression` on **portfolio-service**, triggered by `chg:2512` (HYP-2)

Confidence 0.22 (low). New sector‑breakdown feature increases outbound gRPC calls to market‑data‑service, amplifying load and causing time‑outs.

**Supporting:**
- Only production change in the window is a deploy of portfolio‑service v5.4.0 at 14:48:30 UTC (after the first errors). (`chg:2512`)
- “Sector mapping missing” warnings appear in portfolio‑service from 14:49 UTC (after the deploy). (`log:e481388daa5a`)
**Contradicting:**
- Portfolio‑service starts returning gRPC DEADLINE_EXCEEDED to market‑data‑service at 14:42 UTC (679 occurrences). (`log:3096c4afe74b`)
- Market‑data‑service logs show quotes‑vendor request time‑outs (800 ms) from 14:41 UTC (1 072 occurrences) and circuit‑breaker half‑open from 14:47 UTC. (`log:785c94c54006`, `log:a9fa5c6b6926`)
- Edge‑gateway reports upstream portfolio‑service time‑outs (3 s) from 14:43 UTC (300 occurrences). (`log:5eba6c3c8e7a`)
- Portfolio‑service error‑rate jumps from ~0.2 % baseline to >5 % and p99 latency rises from ~415 ms to >3 s during the same window. (`metric:portfolio-service/error_rate`, `metric:portfolio-service/latency_p99_ms`)
**Assumptions:**
- ASM-3: The v5.4.0 deploy adds a code path that calls market‑data‑service more often (sector breakdown).
- ASM-4: Deploy effects are immediate; no rolling‑restart delay.

### 3. `resource_exhaustion` on **market-data-service** (HYP-3)

Confidence 0.10 (low). Internal saturation (thread‑pool, GC) in market‑data‑service leads to slower responses to quotes‑vendor, manifesting as vendor time‑outs.

**Supporting:**
- Market‑data‑service logs show quotes‑vendor request time‑outs (800 ms) from 14:41 UTC (1 072 occurrences) and circuit‑breaker half‑open from 14:47 UTC. (`log:785c94c54006`, `log:a9fa5c6b6926`)
**Contradicting:**
- CPU and memory on portfolio‑service remain flat (~0.51 CPU, 0.55 mem) – no resource saturation. (`metric:portfolio-service/cpu_util`, `metric:portfolio-service/mem_util`)
**Assumptions:**
- ASM-5: If market‑data‑service were resource‑exhausted, its own CPU/memory metrics would show a rise.

### 4. `infrastructure_failure` on **network** (HYP-4)

Confidence 0.08 (low). Network latency or packet loss between market‑data‑service and quotes‑vendor causes the 800 ms timeout.

**Supporting:**
- Market‑data‑service logs show quotes‑vendor request time‑outs (800 ms) from 14:41 UTC (1 072 occurrences) and circuit‑breaker half‑open from 14:47 UTC. (`log:785c94c54006`, `log:a9fa5c6b6926`)
**Assumptions:**
- ASM-6: A network problem would be visible to other services using the same egress path; none reported.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Add a circuit‑breaker / fallback in portfolio‑service for market‑data‑service calls (serve stale cached quotes). | Prevents cascade to edge‑gateway while vendor is slow. |
| now | mitigate | Increase portfolio‑service → market‑data‑service gRPC timeout from 500 ms to ~800 ms and enable retry with back‑off (if idempotent). | Aligns timeout budget with vendor timeout, giving more headroom. |
| soon | investigate | Engage quotes‑vendor with observed timeout pattern (800 ms) and request status / SLA review. | External root cause needs vendor remediation. |
| soon | fix | Roll back portfolio‑service v5.4.0 or disable the new sector‑breakdown feature flag. | Deploy added load after onset; rollback reduces pressure on market‑data‑service. |
| later | prevent | Add synthetic health‑checks that hit the full chain (edge‑gateway → portfolio → market‑data → vendor) and surface per‑hop latency. | Guarantees visibility of future vendor‑side problems. |
| later | prevent | Document the timeout budget (vendor 800 ms → market‑data 500 ms → portfolio 3 s) and enforce a timeout‑budget policy for new features. | Prevents future features from unintentionally tightening the chain. |

## Evidence gaps

- **query_metrics** (quotes-vendor latency and error rate): External vendor not instrumented in our metrics platform
- **query_metrics** (market-data-service CPU, memory, thread‑pool, GC): Not queried; would confirm or rule out resource exhaustion
- **get_change_history** (market-data-service config/feature‑flag changes): Change history may miss non‑deploy changes
- **query_logs** (distributed trace of a portfolio request (edge‑gateway → portfolio → market‑data → vendor)): Tracing infrastructure not available via current tools

## Open questions

- What is the current SLA / typical latency of quotes‑vendor? (Needed to judge whether 800 ms timeout is appropriate.)
- Did market‑data‑service experience any GC pauses or thread‑pool exhaustion during 14:40‑15:05? (Metrics not collected; could rule out H3.)
- Is there a feature‑flag to disable the new sector‑breakdown without a full rollback? (Would allow quick mitigation.)
- Are there other downstream callers of market‑data‑service that showed errors? (Would indicate broader impact of vendor slowdown.)

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 8 model calls, 6 tool calls, 53,566 tokens, 301 s.
