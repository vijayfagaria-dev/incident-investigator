# T09: Notification pods restarting

**Outcome:** conclusive. Root cause: `code_regression` on **notification-service**, triggered by `chg:2591`

## Summary

Notification-service pods began OOMKilling at 07:52 UTC after a deploy of v3.9.2 at 07:12 UTC that added a per‑locale template cache. GC overhead warnings appeared at 07:35 UTC, memory utilisation rose to the 1 Gi limit, consumer lag and error rates exploded as pods restarted. No other code, config, flag, secret or infra change occurred in the window, and the modest 20 % traffic rise cannot explain the rapid memory exhaustion. The evidence points to a code regression – an unbounded cache introduced by the v3.9.2 change.

## Hypotheses

### 1. `code_regression` on **notification-service**, triggered by `chg:2591` (HYP-1)

Confidence 0.86 (high). The v3.9.2 deploy introduced an unbounded per‑locale template cache. Each new locale creates cached objects that are never evicted, causing heap growth, high GC overhead, and eventual OOMKill. Restarting pods lose consumer offsets, inflating lag and error rates.

**Supporting:**
- GC‑overhead warnings start at 07:35 UTC and continue (181 occurrences). (`log:f681f54530df`)
- First OOMKilled log at 07:52:13 UTC; 27 OOMKills recorded up to 08:29 UTC. (`log:c39fab989944`)
- Memory utilisation rises from baseline 0.55 to 0.97 (mean 0.82), hitting the 1 Gi limit. (`metric:notification-service/mem_util`)
- Error rate climbs from baseline 0.002 to 0.032 (≈16×). (`metric:notification-service/error_rate`)
- Deploy of notification-service v3.9.2 at 07:12:30 UTC (change chg:2591) – “cache rendered templates per recipient locale”, +88/-21 lines. (`chg:2591`)
- No other deploy, config, feature‑flag, secret rotation or infra change for notification-service or kafka in the 06:30‑08:30 UTC window. (`chg:2591`)
- Request rate rises modestly from baseline ~103 req/s to ~123 req/s (≈20 % increase). (`metric:notification-service/rps`)
**Assumptions:**
- ASM-1: The new per‑locale cache retains template objects indefinitely (no eviction/size bound).

### 2. `capacity_saturation` on **notification-service** (HYP-2)

Confidence 0.12 (low). A traffic surge pushes the service beyond its 1 Gi memory limit, causing OOMKills.

**Supporting:**
- Memory utilisation rises from baseline 0.55 to 0.97 (mean 0.82), hitting the 1 Gi limit. (`metric:notification-service/mem_util`)
- Request rate rises modestly from baseline ~103 req/s to ~123 req/s (≈20 % increase). (`metric:notification-service/rps`)
**Contradicting:**
- GC‑overhead warnings start at 07:35 UTC and continue (181 occurrences). (`log:f681f54530df`)
- First OOMKilled log at 07:52:13 UTC; 27 OOMKills recorded up to 08:29 UTC. (`log:c39fab989944`)
- Consumer lag jumps from baseline ~128 messages to ~41 k messages at 08:30 UTC (mean ~12 k during window). (`metric:notification-service/consumer_lag`)
- Error rate climbs from baseline 0.002 to 0.032 (≈16×). (`metric:notification-service/error_rate`)
- Deploy of notification-service v3.9.2 at 07:12:30 UTC (change chg:2591) – “cache rendered templates per recipient locale”, +88/-21 lines. (`chg:2591`)
**Assumptions:**
- ASM-2: Memory limit has not been changed recently; the service was stable at prior load.

### 3. `dependency_degradation` on **kafka** (HYP-3)

Confidence 0.02 (low). Kafka consumer lag builds up, causing the service to buffer large batches in memory until OOM.

**Supporting:**
- Consumer lag jumps from baseline ~128 messages to ~41 k messages at 08:30 UTC (mean ~12 k during window). (`metric:notification-service/consumer_lag`)
**Contradicting:**
- GC‑overhead warnings start at 07:35 UTC and continue (181 occurrences). (`log:f681f54530df`)
- First OOMKilled log at 07:52:13 UTC; 27 OOMKills recorded up to 08:29 UTC. (`log:c39fab989944`)
- Deploy of notification-service v3.9.2 at 07:12:30 UTC (change chg:2591) – “cache rendered templates per recipient locale”, +88/-21 lines. (`chg:2591`)
- Notification-service hard‑depends on kafka (queue); upstream services have only soft kafka dependencies. (`dep:notification-service->kafka`)
**Assumptions:**
- ASM-3: Consumer processes messages in large batches that stay in heap until acknowledged.

### 4. `resource_exhaustion` on **notification-service** (HYP-4)

Confidence 0.01 (low). An unrecorded infrastructure change lowered the pod memory limit, causing immediate OOM.

**Supporting:**
- First OOMKilled log at 07:52:13 UTC; 27 OOMKills recorded up to 08:29 UTC. (`log:c39fab989944`)
**Contradicting:**
- No other deploy, config, feature‑flag, secret rotation or infra change for notification-service or kafka in the 06:30‑08:30 UTC window. (`chg:2591`)
**Assumptions:**
- ASM-4: A silent limit change could have occurred outside the change‑history window.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Rollback notification-service to v3.9.1 or deploy hot‑fix disabling the new locale cache. | Stops the memory leak immediately; the only change correlated with onset. |
| now | mitigate | Temporarily raise pod memory limit to 2 Gi if rollback cannot be applied instantly. | Buys time while fix is prepared; does not solve the leak. |
| soon | investigate | Capture heap dump from a crashing pod (enable -XX:+HeapDumpOnOutOfMemoryError) and analyse cache objects. | Confirms the unbounded cache assumption (A1). |
| soon | fix | Add size‑bounded eviction (e.g., Caffeine maximumSize) to the per‑locale template cache in v3.9.2. | Prevents recurrence of the leak. |
| later | prevent | Add alerts on mem_util > 0.85 and GC overhead > 30 %. | Early detection for future regressions. |
| later | prevent | Create regression test simulating high‑locale‑variety traffic. | Ensures cache behaves correctly under load. |

## Evidence gaps

- **query_logs** (heap dump / detailed GC logs from a crashing pod): Tool only returns aggregated patterns; no raw heap dump available.
- **get_change_history** (full diff of commit 0f6c3a8 (v3.9.2 cache implementation)): Change history provides only summary; source diff not accessible.
- **get_change_history** (historical pod memory‑limit configuration): No infra change recorded; cannot verify limit stability.
- **query_metrics** (per‑pod consumer lag timeline): Metrics aggregated per service; per‑pod granularity missing.
- **query_metrics** (kafka broker lag and fetch latency): Only notification-service metrics were queried; kafka side not observed.

## Open questions

- What is the exact eviction policy (or lack thereof) in the new per‑locale cache?
- Did any feature flag toggle the cache on/off around 07:30 UTC?
- Why did consumer lag only explode after the first OOMKill?
- Is the 1 Gi memory limit appropriate for the service’s steady‑state workload?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 6 model calls, 4 tool calls, 33,415 tokens, 261 s.
