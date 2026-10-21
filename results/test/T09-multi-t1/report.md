# T09: Notification pods restarting

**Outcome:** conclusive. Root cause: `code_regression` on **notification-service**, triggered by `chg:2591`

## Summary

The notification‑service began OOM‑killing at ~07:50 UTC after the v3.9.2 deploy (chg:2591) introduced an unbounded per‑locale template cache. Memory utilization rose linearly from ~55 % to the 1 GiB limit over ~38 minutes, GC‑overhead warnings appeared at 07:35, and consumer lag grew as pods recycled. The critic accepted HYP‑1 (code regression) with 86 % confidence, making this the conclusive cause. Remaining unknowns are the exact cache allocation paths, whether a feature‑flag could disable the cache, and the absence of producer‑side Kafka metrics.

## Hypotheses

### 1. `code_regression` on **notification-service**, triggered by `chg:2591` (HYP-1)

Confidence 0.86 (high), critic: accept. The v3.9.2 deploy added a per‑locale template cache with no size bound or eviction. Each distinct locale encountered creates a retained template object, causing a steady heap increase, GC‑overhead warnings, and eventual OOMKills once the 1 GiB limit is reached. Restarts reset the cache, so consumer lag grows while pods recycle.

**Supporting:**
- deploy on notification-service at 07:12:30 UTC by ci/deploy-bot: notification-service v3.9.2: cache rendered templates per recipient locale (version: 3.9.2, previous_version: 3.9.1, commit: 0f6c3a8, diff: +88 / -21) (`chg:2591`)
- GC overhead high warnings appear on notification-service starting at 07:35:06 UTC (153 occurrences through 08:19). (`log:f681f54530df`)
- notification-service pods are OOMKilled (memory limit 1 GiB) beginning at 07:52:13 UTC, with 20 total OOM events through 08:19. (`log:c39fab989944`)
- mem_util rises from 0.5405 at 07:05 to 0.9592 at 07:50 and exceeds 0.97 by 07:53, reaching the 1.0 limit (baseline ≈ 0.55). (`metric:notification-service/mem_util`)
- consumer_lag grows from ~103 messages at 07:05 to 53 110 messages at 08:20 (baseline ≈ 126). (`metric:notification-service/consumer_lag`)
- Only change on the four target services in the 06:30‑08:20 UTC window is the notification-service deploy v3.9.2 at 07:12:30 UTC (chg:2591). (`chg:2591`)
- First OOMKill of notification-service pods observed at ~07:50 UTC, roughly 38 minutes after the notification-service deploy. (`chg:2591`)
- mem_util at 07:10 UTC was 0.5477 (≈55% of the 1 GiB limit). (`metric:notification-service/mem_util`)
- mem_util at 07:12 UTC (deploy minute) was 0.5551, a +0.0074 step increase over the previous point. (`metric:notification-service/mem_util`)
- From 07:14 UTC onward mem_util increased monotonically every 2 minutes, reaching 0.9621 at 07:50 UTC. (`metric:notification-service/mem_util`)
- mem_util first exceeded the practical OOM threshold of 0.97 at 07:52 UTC (0.9686) and remained near 0.96–0.97 through 07:54 UTC. (`metric:notification-service/mem_util`)
- Baseline mean mem_util is 0.549; the observed mean over 07:10‑07:55 UTC is 0.760, a 38% relative increase. (`metric:notification-service/mem_util`)
- The memory growth starts immediately after the v3.9.2 deploy at 07:12:30 UTC and continues linearly for ~38 minutes until the first OOMKill observed at ~07:50 UTC. (`metric:notification-service/mem_util`, `chg:2591`)
**Contradicting:**
- rps increases modestly from 101.7 req/s at 07:05 to 118.5 req/s at 08:20 (baseline ≈ 103). (`metric:notification-service/rps`)
- orders-service request rate averaged 111.5 req/s (baseline 100.6 req/s) with a peak of 128.1 req/s during the window. (`metric:orders-service/rps`)
- payments-service request rate averaged 110.7 req/s (baseline 101.6 req/s) with a peak of 126.3 req/s. (`metric:payments-service/rps`)
**Assumptions:**
- ASM-6: The new per‑locale template cache introduced in v3.9.2 has no size bound or eviction policy.
- ASM-7: Each distinct locale touched creates a retained template object, so cache size grows roughly linearly with distinct locales seen.
- ASM-8: The 1 GiB container memory limit was unchanged by the deploy.

### 2. `dependency_degradation` on **notification-service** (HYP-2)

Confidence 0.22 (low), critic: challenge. An unrecorded change in orders‑service or payments‑service (e.g., larger Kafka record payloads, new fields, increased batch size) caused the consumer to fetch larger batches, buffering more data per poll and exhausting the pod’s heap. No deploy or config change is visible for those producers, but a feature‑flag flip or topic‑config change could have taken effect around 07:00‑07:30.

**Supporting:**
- Kafka broker inbound message rate averaged 76.5 msg/s (baseline 72.5 msg/s) with a maximum of 92.1 msg/s observed in the window. (`metric:kafka/messages_in_per_s`)
- consumer_lag grows from ~103 messages at 07:05 to 53 110 messages at 08:20 (baseline ≈ 126). (`metric:notification-service/consumer_lag`)
- orders-service request rate averaged 111.5 req/s (baseline 100.6 req/s) with a peak of 128.1 req/s during the window. (`metric:orders-service/rps`)
- payments-service request rate averaged 110.7 req/s (baseline 101.6 req/s) with a peak of 126.3 req/s. (`metric:payments-service/rps`)
**Contradicting:**
- mem_util rises from 0.5405 at 07:05 to 0.9592 at 07:50 and exceeds 0.97 by 07:53, reaching the 1.0 limit (baseline ≈ 0.55). (`metric:notification-service/mem_util`)
- Kafka under‑replicated partitions remained at zero throughout the window. (`metric:kafka/under_replicated_partitions`)
- Only change on the four target services in the 06:30‑08:20 UTC window is the notification-service deploy v3.9.2 at 07:12:30 UTC (chg:2591). (`chg:2591`)
- No deploy, config, feature‑flag, secret rotation, or infra change recorded for orders-service, payments-service, or kafka in the same window. (`chg:2591`)
**Assumptions:**
- ASM-3: A producer‑side change (larger payload, new field, batch‑size bump) occurred without a recorded deploy, possibly via a feature flag.
- ASM-4: The notification‑service consumer does not apply back‑pressure and buffers whole fetch responses in heap.
**Objections:**
- [blocking] unsupported_claim: Claims an unrecorded producer change enlarged Kafka payloads, but no deploy, config, flag or infra change is observed for orders‑service or payments‑service (OBS‑15, OBS‑16).
- [blocking] gap_unaddressed: Producer‑side metrics (publish_rate, avg_record_size, batch_size) and Kafka fetch‑latency/network metrics are missing (GAP‑4, GAP‑1, GAP‑10, GAP‑11).
- [blocking] alternative_not_excluded: HYP‑1 (code regression) fully explains the memory growth and OOM pattern and has not been ruled out.

### 3. `dependency_degradation` on **orders-service** (HYP-4)

Confidence 0.13 (low), critic: challenge. An unrecorded change in orders‑service or payments‑service (e.g., larger Kafka record payloads, new fields, increased batch size, or a feature‑flag flip) caused the consumer to fetch larger batches, buffering more data per poll and exhausting the notification‑service pod’s heap. No deploy or config change is visible for those producers, but a hidden change could have taken effect around 07:00‑07:30.

**Supporting:**
- Kafka broker inbound message rate averaged 76.5 msg/s (baseline 72.5 msg/s) with a maximum of 92.1 msg/s observed in the window. (`metric:kafka/messages_in_per_s`)
- consumer_lag grows from ~103 messages at 07:05 to 53 110 messages at 08:20 (baseline ≈ 126). (`metric:notification-service/consumer_lag`)
- orders-service request rate averaged 111.5 req/s (baseline 100.6 req/s) with a peak of 128.1 req/s during the window. (`metric:orders-service/rps`)
- payments-service request rate averaged 110.7 req/s (baseline 101.6 req/s) with a peak of 126.3 req/s. (`metric:payments-service/rps`)
- Dependency graph: notification-service → kafka (hard consumer), orders-service → kafka (soft producer), payments-service → kafka (soft producer). (`dep:notification-service->kafka`, `dep:orders-service->kafka`, `dep:payments-service->kafka`)
**Contradicting:**
- mem_util rises from 0.5405 at 07:05 to 0.9592 at 07:50 and exceeds 0.97 by 07:53, reaching the 1.0 limit (baseline ≈ 0.55). (`metric:notification-service/mem_util`)
- Kafka under‑replicated partitions remained at zero throughout the window. (`metric:kafka/under_replicated_partitions`)
- Only change on the four target services in the 06:30‑08:20 UTC window is the notification-service deploy v3.9.2 at 07:12:30 UTC (chg:2591). (`chg:2591`)
- No deploy, config, feature‑flag, secret rotation, or infra change recorded for orders-service, payments-service, or kafka in the same window. (`chg:2591`)
- mem_util at 07:10 UTC was 0.5477 (≈55% of the 1 GiB limit). (`metric:notification-service/mem_util`)
- mem_util at 07:12 UTC (deploy minute) was 0.5551, a +0.0074 step increase over the previous point. (`metric:notification-service/mem_util`)
- From 07:14 UTC onward mem_util increased monotonically every 2 minutes, reaching 0.9621 at 07:50 UTC. (`metric:notification-service/mem_util`)
- mem_util first exceeded the practical OOM threshold of 0.97 at 07:52 UTC (0.9686) and remained near 0.96–0.97 through 07:54 UTC. (`metric:notification-service/mem_util`)
- Baseline mean mem_util is 0.549; the observed mean over 07:10‑07:55 UTC is 0.760, a 38% relative increase. (`metric:notification-service/mem_util`)
- The memory growth starts immediately after the v3.9.2 deploy at 07:12:30 UTC and continues linearly for ~38 minutes until the first OOMKill observed at ~07:50 UTC. (`metric:notification-service/mem_util`, `chg:2591`)
**Assumptions:**
- ASM-9: A hidden change (feature‑flag flip, topic config, schema change) increased per‑message size or batch size around 07:30, causing the consumer to buffer more per poll.
- ASM-10: The extra buffered data from larger Kafka records is the dominant driver of the notification‑service heap growth.
**Objections:**
- [blocking] unsupported_claim: Asserts a hidden orders‑service/payments‑service change without any change‑census evidence (OBS‑15, OBS‑16).
- [blocking] gap_unaddressed: Required producer metrics and Kafka broker fetch metrics are unavailable (GAP‑1, GAP‑10, GAP‑11).
- [blocking] alternative_not_excluded: HYP‑1 remains a better‑supported explanation.

### 4. `capacity_saturation` on **notification-service**, triggered by `chg:2591` (HYP-3)

Confidence 0.07 (low), critic: reject. The new cache introduced by v3.9.2 raises the steady‑state memory footprint above the 1 GiB limit. The pod would OOM shortly after start‑up, but the observed 30‑minute ramp suggests the cache grows to a fixed maximum >1 GiB, causing OOM once that maximum is reached.

**Supporting:**
- notification-service pods are OOMKilled (memory limit 1 GiB) beginning at 07:52:13 UTC, with 20 total OOM events through 08:19. (`log:c39fab989944`)
- mem_util rises from 0.5405 at 07:05 to 0.9592 at 07:50 and exceeds 0.97 by 07:53, reaching the 1.0 limit (baseline ≈ 0.55). (`metric:notification-service/mem_util`)
- Only change on the four target services in the 06:30‑08:20 UTC window is the notification-service deploy v3.9.2 at 07:12:30 UTC (chg:2591). (`chg:2591`)
**Contradicting:**
- GC overhead high warnings appear on notification-service starting at 07:35:06 UTC (153 occurrences through 08:19). (`log:f681f54530df`)
- consumer_lag grows from ~103 messages at 07:05 to 53 110 messages at 08:20 (baseline ≈ 126). (`metric:notification-service/consumer_lag`)
**Assumptions:**
- ASM-5: The cache has a fixed maximum size that exceeds the 1 GiB pod limit, so the pod would OOM only after the cache fills to that maximum.
**Objections:**
- [blocking] ignores_contradiction: Observed gradual memory rise (OBS‑24, OBS‑27) and early GC‑overhead warnings (OBS‑3) contradict the predicted immediate jump to limit.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll back notification-service to v3.9.1 or increase the pod memory limit temporarily while a fix is prepared. | Stops the OOM‑kills and unblocks notification delivery immediately. (HYP-1) |
| soon | fix | Add a size bound and eviction policy (e.g., LRU or TTL) to the per‑locale template cache introduced in v3.9.2. | Eliminates the unbounded heap growth that triggers OOM‑kills. (HYP-1) |
| later | prevent | Introduce a canary/gradual rollout with memory‑usage alerts for future notification-service releases and add a unit‑test that validates cache eviction behavior. | Prevents similar regressions from reaching production. (HYP-1) |
| later | investigate | Obtain a heap dump or detailed GC logs from an OOM‑killed pod to confirm locale‑template objects dominate retained memory. | Closes GAP‑13 and validates the cache‑growth mechanism. (HYP-1) |
| later | investigate | Expose cache‑size/eviction metrics (or add logging) in notification-service to monitor cache growth in real time. | Addresses GAP‑12 and provides early warning for future deployments. (HYP-1) |
| later | investigate | Verify whether any feature‑flag or secret rotation after the deploy could enable/disable the new cache (GAP‑8). | Ensures no hidden toggle contributed to the behavior. (HYP-1) |
| later | investigate | Add Kafka producer metrics (publish_rate, avg_record_size, batch_size) for orders‑service and payments‑service to close GAP‑4, GAP‑10, GAP‑11. | Completes observability for downstream dependency analysis and rules out future producer‑side regressions. |

## Evidence gaps

- **query_metrics** (kafka fetch-rate, broker CPU, network, consumer‑lag (broker side)): No Kafka metrics were queried; cannot confirm correlation with notification-service memory growth.
- **query_logs** (kafka broker logs at WARN/ERROR level 07:05‑08:20): Kafka logs not examined; possible broker anomalies are unknown.
- **query_metrics** (kafka/messages_in_per_s time‑series points): Only summary statistics were returned; minute‑level points are needed to pinpoint when the inbound message rate spiked relative to the notification‑service OOMKills.
- **query_metrics** (orders-service and payments-service Kafka producer metrics (publish_rate, record_size, batch_size)): These metrics are not exposed in the current metric catalog, so we cannot attribute the aggregate Kafka increase to a specific service.
- **query_logs** (WARN+ log patterns for orders-service and payments-service (07:05‑08:20)): Log queries were not executed; errors or back‑pressure warnings from producers could explain a sudden publish surge.
- **get_change_history** (Kafka cluster configuration (topic partitions, quotas, retention)): Change census only covered the four named services; cluster‑level config changes are not captured.
- **get_change_history** (Infrastructure events (node‑pool scaling, node restarts, CNI changes)): No infra‑change source was queried; such events could affect pod memory limits or OOM‑killer behavior.
- **get_change_history** (Feature‑flag or secret‑rotation state for notification-service after deploy): Census shows the deploy but not any subsequent flag flip that could enable/disable the new cache.
- **get_change_history** (Detailed code diff of notification-service v3.9.2 (exact cache allocation paths)): Only line‑count diff (+88/‑21) is recorded; the exact allocation logic is needed to assess memory impact.
- **query_metrics** (orders-service publish_rate, avg_record_size, batch_size): Metric names not present in orders-service metric catalog; query returned invalid_query error.
- **query_metrics** (payments-service publish_rate, avg_record_size, batch_size): Metric names not present in payments-service metric catalog; query returned invalid_query error.
- **query_metrics** (Per‑minute mem_util for notification-service 07:10‑07:55 UTC): API limited to 30 points, returned 2‑minute steps instead of 1‑minute resolution.
- **query_metrics** (Heap dump or detailed GC logs for notification-service pods): Not exposed via current metrics/log endpoints; cannot confirm cache objects dominate retained heap.

## Open questions

- Exact allocation logic and retention semantics of the per‑locale template cache (GAP‑9).
- Whether a feature‑flag could disable the cache after deploy (GAP‑8).
- Heap dump / GC log confirmation that locale‑template objects dominate retained heap (GAP‑13).
- Producer‑side Kafka metrics for orders‑service and payments‑service (GAP‑4, GAP‑10, GAP‑11).
- Minute‑resolution memory utilization for notification‑service during the ramp (GAP‑12).

## How the investigation ran

Stopped because the critic accepted HYP-1, after 2 round(s): 30 model calls, 13 tool calls, 137,175 tokens, 746 s.
