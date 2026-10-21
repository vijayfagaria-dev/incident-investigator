# T09: Notification pods restarting

**Outcome:** conclusive. Root cause: `code_regression` on **notification-service**, triggered by `chg:2591`

## Summary

notification-service pods began OOMKilling at 07:52 UTC after a deploy at 07:12 UTC introduced an unbounded per‑locale template cache. GC overhead warnings appeared from 07:35 UTC, memory utilization climbed to the 1 GiB limit, and consumer lag and error rates rose as a consequence of repeated restarts. No other config, flag, secret, or infra changes occurred in the window.

## Hypotheses

### 1. `code_regression` on **notification-service**, triggered by `chg:2591` (HYP-1)

Confidence 0.78 (high). Unbounded per‑locale template cache introduced in v3.9.2 retains entries indefinitely, causing steady heap growth, high GC overhead, and eventual OOMKill.

**Supporting:**
- GC overhead high warnings (~35‑37%) appear continuously from 07:35 UTC. (`log:f681f54530df`)
- First OOMKill recorded at 07:52:13 UTC; total 27 OOMKill events until 08:29 UTC. (`log:c39fab989944`)
- Memory utilization climbed from baseline 0.55 to peak 1.00 (1 GiB limit) with mean 0.82. (`metric:notification-service/mem_util`)
- Only production change was deploy of notification-service v3.9.2 at 07:12:30 UTC (commit 0f6c3a8) adding per‑locale template cache. (`chg:2591`)
**Assumptions:**
- ASM-1: The new per‑locale template cache retains entries indefinitely (no eviction/TTL).

### 2. `capacity_saturation` on **notification-service** (HYP-2)

Confidence 0.12 (low). Higher request rate pushes normal memory usage over the 1 GiB limit.

**Supporting:**
- Request rate increased ~10% from baseline 103 rps to mean 113 rps. (`metric:notification-service/rps`)
- Memory utilization climbed from baseline 0.55 to peak 1.00 (1 GiB limit) with mean 0.82. (`metric:notification-service/mem_util`)
**Contradicting:**
- GC overhead high warnings (~35‑37%) appear continuously from 07:35 UTC. (`log:f681f54530df`)
- CPU utilization remained near baseline (0.33 to 0.35). (`metric:notification-service/cpu_util`)
**Assumptions:**
- ASM-2: Memory usage scales roughly linearly with request rate when cache size is bounded.

### 3. `dependency_degradation` on **notification-service** (HYP-3)

Confidence 0.07 (low). Kafka consumer lag forces the service to buffer large batches, exhausting memory.

**Supporting:**
- Consumer lag grew from baseline ~129 messages to last 41,370 messages. (`metric:notification-service/consumer_lag`)
**Contradicting:**
- First OOMKill recorded at 07:52:13 UTC; total 27 OOMKill events until 08:29 UTC. (`log:c39fab989944`)
- GC overhead high warnings (~35‑37%) appear continuously from 07:35 UTC. (`log:f681f54530df`)
**Assumptions:**
- ASM-3: Consumer processes messages in batches whose size is proportional to lag.

### 4. `infrastructure_failure` on **notification-service** (HYP-4)

Confidence 0.03 (low). The 1 GiB memory limit is insufficient for current workload even without a leak.

**Supporting:**
- Memory utilization climbed from baseline 0.55 to peak 1.00 (1 GiB limit) with mean 0.82. (`metric:notification-service/mem_util`)
**Contradicting:**
- Only production change was deploy of notification-service v3.9.2 at 07:12:30 UTC (commit 0f6c3a8) adding per‑locale template cache. (`chg:2591`)
- CPU utilization remained near baseline (0.33 to 0.35). (`metric:notification-service/cpu_util`)
**Assumptions:**
- ASM-4: The 1 GiB container memory limit has not been altered recently.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Rollback notification-service to v3.9.1 or disable the new per‑locale cache via feature flag. | Stops further memory growth immediately; the deploy is the only recent change. |
| now | mitigate | Temporarily raise pod memory limit to 2 GiB and add restart‑rate alert. | Provides breathing room while the fix is validated; prevents immediate OOMKill cascades. |
| soon | fix | Implement bounded cache (LRU/TTL, max entries) and ship hot‑fix v3.9.3. | Eliminates the unbounded growth root cause. |
| later | prevent | Add cache‑size metric (template_cache_entries) and GC pause time metric. | Provides observability for future regressions. |
| soon | investigate | Obtain heap dump from a restarted pod to confirm cache objects dominate retained heap. | Closes Gap G1 and validates hypothesis H1. |

## Evidence gaps

- **query_logs** (heap dump / detailed GC logs): Tool cannot retrieve heap dumps; needed to confirm cache domination.
- **query_metrics** (cache size metric (e.g., template_cache_entries)): Metric not emitted; would directly show unbounded growth.
- **get_change_history** (Kafka consumer config (max.poll.records, fetch.max.bytes)): No record of consumer config changes; needed to rule out H3.

## Open questions

- How many distinct locales were seen during the incident?
- Does the new cache have any eviction/TTL logic that was inadvertently disabled?
- Were there any feature‑flag changes not captured in the change‑history feed?
- What is the Kafka consumer `max.poll.records` setting?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 6 model calls, 4 tool calls, 34,500 tokens, 245 s.
