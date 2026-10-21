# T09: Notification pods restarting

**Outcome:** conclusive. Root cause: `code_regression` on **notification-service**, triggered by `chg:2591`

## Summary

Notification‑service pods began OOM‑killing at ~07:50 UTC after the v3.9.2 deploy at 07:12 UTC introduced per‑recipient‑locale template caching. Memory utilization climbed from 0.55 to >0.97, GC overhead hit ~37 % CPU, and consumer lag grew from ~128 to >53 k messages. The critic accepted HYP‑1 (cache‑leak regression, change chg:2591) as the root cause with high confidence (0.85). The investigation is conclusive, but a heap dump or allocation‑rate metric to directly observe the leaking cache map has not yet been captured.

## Hypotheses

### 1. `code_regression` on **notification-service**, triggered by `chg:2591` (HYP-1)

Confidence 0.85 (high), critic: accept. The v3.9.2 deploy added per‑recipient‑locale template caching. The cache retains strong references without eviction, causing a steady heap increase. Rising heap triggers frequent GC (≈37 % CPU), then OOMKills, pod restarts, and growing consumer lag as the consumer repeatedly crashes.

**Supporting:**
- deploy on notification-service at 07:12:30 UTC by ci/deploy-bot: notification-service v3.9.2: cache rendered templates per recipient locale (version: 3.9.2, previous_version: 3.9.1, commit: 0f6c3a8, diff: +88 / -21) (`chg:2591`)
- notification-service was deployed to version 3.9.2 at 07:12:30 UTC (commit 0f6c3a8, diff +88/-21). (`chg:2591`)
- Deploy of notification-service v3.9.2 completed at 07:12:30 UTC. (`chg:2591`)
- Memory utilization rises from baseline 0.55 (07:00) to 0.63 at 07:18, 0.78 at 07:33, 0.91 at 07:45, and exceeds 0.97 by 07:51. (`metric:notification-service/mem_util`)
- GC overhead high warnings (≈37 % time in GC) start at 07:35:06 and continue through 08:19. (`log:f681f54530df`)
- First OOMKill of a notification-service pod recorded at 07:52:13; subsequent kills at 07:55, 07:58, 08:01, … up to 08:19. (`log:c39fab989944`)
- Error rate rises from baseline 0.002 to 0.034 by 08:20; latency p99 modestly increases from 252 ms baseline to 249 ms last (within normal range). (`metric:notification-service/error_rate`, `metric:notification-service/latency_p99_ms`)
**Assumptions:**
- ASM-1: The new per‑locale template cache retains objects indefinitely (no eviction or size bound).
- ASM-2: No other configuration or feature‑flag change touched notification‑service between 07:00‑08:20 UTC.
**Objections:**
- [minor] gap_unaddressed: The cache‑leak mechanism assumes the locale cache holds strong references without eviction; a heap dump or allocation‑rate metric would confirm this, but such data is not currently available.

### 2. `dependency_degradation` on **notification-service** (HYP-2)

Confidence 0.25 (low), critic: reject. An unrecorded upstream change (e.g., a feature flag or marketing campaign) increased the rate or payload size of messages published to the notification Kafka topics. The consumer buffers whole batches in heap, so the sudden surge drives memory pressure, GC overhead, OOMKills, and a massive consumer‑lag backlog.

**Supporting:**
- Consumer lag metric jumps from baseline mean 128 messages to a peak of 53 710 messages; last observed value 53 110 at 08:20. (`metric:notification-service/consumer_lag`)
- Error rate rises from baseline 0.002 to 0.034 by 08:20; latency p99 modestly increases from 252 ms baseline to 249 ms last (within normal range). (`metric:notification-service/error_rate`, `metric:notification-service/latency_p99_ms`)
**Contradicting:**
- No changes were recorded for orders-service, payments-service, or kafka in the 07:00–08:20 UTC window. (`chg:2591`)
- Log pattern searches for “kafka” and “notification” in orders‑service returned zero matches for the 07:00‑08:20 UTC window. (`log:f681f54530df`, `log:c39fab989944`)
- The upstream dependency query for notification-service returned an empty dependency list, indicating no recorded producers in the dependency graph. (`dep:orders-service->kafka`)
- Memory utilization rises from baseline 0.55 (07:00) to 0.63 at 07:18, 0.78 at 07:33, 0.91 at 07:45, and exceeds 0.97 by 07:51. (`metric:notification-service/mem_util`)
- GC overhead high warnings (≈37 % time in GC) start at 07:35:06 and continue through 08:19. (`log:f681f54530df`)
**Assumptions:**
- ASM-3: An unrecorded upstream change (feature flag, campaign, data feed) could have altered message volume or size.
- ASM-4: Notification consumer buffers full batches in heap before processing.
**Objections:**
- [blocking] ignores_contradiction: The hypothesis ignores contradictory observations: no upstream deploy/config changes (OBS‑3), empty upstream dependency list (OBS‑4), no Kafka‑related logs in orders‑service (OBS‑12), and memory growth precedes any plausible traffic surge (OBS‑8, OBS‑7).

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll back notification‑service to v3.9.1 or disable the locale‑cache feature flag to stop OOM kills immediately. | The memory leak is triggered by the new cache; removing the change halts the impact while a permanent fix is built. (HYP-1) |
| soon | fix | Add eviction (e.g., size‑bounded LRU or weak references) to the locale template cache and verify memory stability under load. | Eliminates the unbounded strong‑reference map that causes steady heap growth. (HYP-1) |
| later | prevent | Instrument cache size and GC‑overhead metrics; add alerts for GC > 30 % CPU or memory > 90 % of limit. | Early detection of similar regressions in future releases. (HYP-1) |
| later | investigate | Capture a heap dump from a pod just before OOM to confirm the locale‑cache map dominates the heap. | Directly validates the cache‑leak mechanism assumed in HYP‑1 (addresses GAP‑6). (HYP-1) |
| later | investigate | Query fine‑grained consumer‑lag series (per‑minute) to pinpoint when lag diverged from baseline. | Clarifies the exact relationship between memory growth and lag increase (addresses GAP‑4). |
| later | investigate | Collect Kafka broker WARN/ERROR logs for the 07:00‑08:20 window. | Rules out broker‑side issues contributing to lag (addresses GAP‑5). |
| later | investigate | Obtain orders‑service and payments‑service Kafka producer metrics (msg/sec, payload size) and payments‑service change history. | Completes the evidence gap around possible upstream traffic spikes (addresses GAP‑1, GAP‑7, GAP‑8). |
| later | investigate | Verify and extend the service‑dependency catalog for notification‑service upstream producers. | Ensures future investigations have a complete dependency graph (addresses GAP‑2, GAP‑3). |

## Evidence gaps

- **get_change_history** (payments-service (07:00–08:20 UTC)): No change records returned; possible missing data or no changes recorded.
- **get_service_dependencies** (notification-service upstream dependencies): Returned empty list; may be incomplete catalog or notification-service consumes directly from Kafka without a modeled upstream service.
- **get_service_dependencies** (payments-service downstream dependencies): Not queried; unknown whether payments-service produces to the same Kafka topics consumed by notification-service.
- **query_metrics** (notification-service consumer_lag per‑minute series): Step limit exhausted; need fine‑grained lag timeline to pinpoint when lag diverges from baseline.
- **query_logs** (kafka broker logs at WARN/ERROR): Not queried; could reveal broker‑side issues contributing to consumer lag.
- **query_metrics** (notification-service GC pause duration or heap allocation rate): Metrics not available in current catalog; would clarify GC impact on memory growth.
- **query_metrics** (orders‑service Kafka producer metrics (message rate, payload size)): The service’s exported metric set does not contain producer‑side Kafka metrics.
- **query_metrics** (payments‑service Kafka producer metrics (message rate, payload size)): payments‑service was not queried; its metric catalog is unknown and likely lacks producer metrics.
- **query_logs** (orders‑service logs containing Kafka publish activity): No log lines matching ‘kafka’ or ‘notification’ were found in the specified window.

## Open questions

- Does a heap dump show the locale‑cache map retaining strong references without eviction?
- What are the GC pause durations and heap allocation rates during the incident (metrics not currently available)?
- At what exact minute did consumer lag start to deviate from baseline?
- Are there any unrecorded changes or traffic spikes in payments‑service that could have contributed?
- Is the notification‑service upstream dependency list truly empty, or does it consume directly from Kafka topics not modeled in the catalog?
- Do Kafka broker logs reveal any broker‑side errors or latency spikes during the window?

## How the investigation ran

Stopped because the critic accepted HYP-1, after 1 round(s): 19 model calls, 10 tool calls, 64,212 tokens, 518 s.
