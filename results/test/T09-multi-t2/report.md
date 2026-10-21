# T09: Notification pods restarting

**Outcome:** inconclusive
- HYP-1 has unresolved blocking objections

## Summary

Notification‑service pods began OOM‑killing at 07:52 UTC after a deploy (v3.9.2) that added a per‑recipient‑locale template cache. Memory grew steadily, GC overhead exceeded 30 % from 07:35, and consumer lag spiked after the first restart. The leading hypothesis (HYP‑1) blames an unbounded cache introduced by the change, but the change record does not confirm the lack of eviction/TTL and no heap‑allocation data is available, leaving a blocking objection. A secondary hypothesis (HYP‑3) suggests the 1 GiB limit is simply too low for the new cache footprint, while an upstream traffic increase (HYP‑2) lacks supporting evidence. Because the investigation hit its time budget, the outcome is inconclusive.

## Hypotheses

### 1. `code_regression` on **notification-service**, triggered by `chg:2591` (HYP-1)

Confidence 0.50 (medium), critic: challenge, capped from 0.78: it has unresolved blocking objections. Deploy v3.9.2 added a per‑recipient‑locale template cache with no eviction/TTL. Each distinct locale‑recipient pair creates a retained object, causing steady heap growth. GC overhead exceeds 30 % from 07:35, memory climbs to the 1 GiB limit, pods are OOM‑killed starting 07:52, and consumer lag spikes after the first restart.

**Supporting:**
- deploy on notification-service at 07:12:30 UTC by ci/deploy-bot: notification-service v3.9.2: cache rendered templates per recipient locale (version: 3.9.2, previous_version: 3.9.1, commit: 0f6c3a8, diff: +88 / -21) (`chg:2591`)
- The deploy (chg:2591) adds per‑recipient‑locale template caching (+88/‑21 lines) – a consumer‑side modification that does not change the schema, size, or production rate of messages placed on Kafka. (`chg:2591`)
- GC overhead warnings (>30 % time in GC) appear continuously from 07:35:06 to 08:19:52 (153 occurrences). (`log:f681f54530df`)
- Pods are OOMKilled (memory limit 1 GiB) starting at 07:52:13 and recurring every few minutes until 08:19:40 (20 occurrences). (`log:c39fab989944`)
- Memory utilization rose from 0.55 (baseline 0.55) at 07:05 to 0.97 at 08:20, exceeding the 1 GiB limit and triggering OOM kills. (`metric:notification-service/mem_util`)
- Consumer lag stayed near baseline (≈100 messages) through 07:50, then jumped to 2,981 at 07:53 and climbed to 53,110 by 08:17 (baseline 126 messages). (`metric:notification-service/consumer_lag`)
- Request rate modestly rose from 101 rps at 07:05 to 119 rps at 08:20 (baseline 103 rps), while p99 latency remained roughly flat (≈250 ms). (`metric:notification-service/rps`, `metric:notification-service/latency_p99_ms`)
- Change census for orders‑service, payments‑service, kafka and notification‑service shows a single entry: notification‑service deploy v3.9.2 at 07:12:30 UTC (chg:2591). (`chg:2591`)
- Deploy chg:2591 adds per‑recipient‑locale template caching (+88/‑21 lines) – a consumer‑side change that does not modify message schema, size, or production rate. (`chg:2591`)
- GC overhead warnings (>30 % time in GC) appear continuously from 07:35:06 to 08:19:52. (`log:f681f54530df`)
- First OOM kill of notification‑service pods occurs at 07:52:13, with recurring kills every few minutes until 08:19. (`log:c39fab989944`, `metric:notification-service/mem_util`)
- First GC‑overhead‑high warning (37 % time in GC) logged at 07:35:06 UTC; warnings continue every few seconds across both pods until 08:19:52 UTC (153 total occurrences). (`log:f681f54530df`, `log:a27feba5d8ae`, `log:cc8a2069509d`)
**Assumptions:**
- ASM-1: The per‑recipient‑locale cache introduced in v3.9.2 has no eviction or TTL and therefore accumulates one entry per distinct locale‑recipient pair.
- ASM-2: The 1 GiB memory limit was sufficient for v3.9.1; the extra cache pushes the process over the limit.
**Objections:**
- [minor] gap_unaddressed: No heap histogram or allocation‑site data is available (GAP‑10, GAP‑11). The tools cannot provide source‑level allocation profiles, so the claim that the new TemplateCache class dominates allocations cannot be verified directly.
- [blocking] unsupported_claim: The hypothesis asserts the cache has no eviction/TTL, but the change record (chg:2591) only notes '+88/-21 lines – cache rendered templates per recipient locale' and does not describe eviction policy. This claim rests on assumption ASM‑1/ASM‑2 rather than observed evidence.

### 2. `dependency_degradation` on **notification-service** (HYP-2)

Confidence 0.32 (low), critic: reject. An unrecorded config/feature‑flag change in orders‑service or payments‑service increased the average Kafka message size or batch size around 07:45‑07:50. Larger payloads per poll raise per‑message processing memory, triggering GC pressure and OOM kills; the lag jump at 07:53 is a direct result of slower consumption.

**Supporting:**
- notification-service has a hard Kafka consumer dependency (dep:notification-service->kafka). (`dep:notification-service->kafka`)
- orders-service and payments-service each have a soft Kafka producer dependency (dep:orders-service->kafka, dep:payments-service->kafka). (`dep:orders-service->kafka`, `dep:payments-service->kafka`)
- Consumer lag stayed near baseline (≈100 messages) through 07:50, then jumped to 2,981 at 07:53 and climbed to 53,110 by 08:17 (baseline 126 messages). (`metric:notification-service/consumer_lag`)
- Request rate modestly rose from 101 rps at 07:05 to 119 rps at 08:20 (baseline 103 rps), while p99 latency remained roughly flat (≈250 ms). (`metric:notification-service/rps`, `metric:notification-service/latency_p99_ms`)
- Consumer lag remained at baseline (~100 msg) until ~07:50, then jumped to ~3 k at 07:53 and climbed to >53 k by 08:17. (`metric:notification-service/consumer_lag`)
**Contradicting:**
- The deploy (chg:2591) adds per‑recipient‑locale template caching (+88/‑21 lines) – a consumer‑side modification that does not change the schema, size, or production rate of messages placed on Kafka. (`chg:2591`)
- Because no upstream service (orders-service, payments-service, kafka) recorded any change in the window, there is no documented change that could have increased the volume or size of messages flowing into Kafka and thus into notification-service. (`chg:2591`)
- Change census for orders‑service, payments‑service, kafka and notification‑service shows a single entry: notification‑service deploy v3.9.2 at 07:12:30 UTC (chg:2591). (`chg:2591`)
- Deploy chg:2591 adds per‑recipient‑locale template caching (+88/‑21 lines) – a consumer‑side change that does not modify message schema, size, or production rate. (`chg:2591`)
**Assumptions:**
- ASM-3: A silent config or feature‑flag change on orders‑service or payments‑service increased average payload size or batch size around 07:45‑07:50.
- ASM-4: Notification‑service’s Kafka consumer does not enforce a per‑poll memory bound, so larger messages directly increase heap pressure.

### 3. `capacity_saturation` on **notification-service**, triggered by `chg:2591` (HYP-3)

Confidence 0.15 (low), critic: challenge. The new caching feature is correctly bounded, but the 1 GiB memory limit is insufficient for the additional cache footprint under normal traffic. Memory utilization rises to ~0.97 GiB and crosses the limit, causing OOM kills; GC overhead is a symptom of the near‑limit heap.

**Supporting:**
- Pods are OOMKilled (memory limit 1 GiB) starting at 07:52:13 and recurring every few minutes until 08:19:40 (20 occurrences). (`log:c39fab989944`)
- Memory utilization rose from 0.55 (baseline 0.55) at 07:05 to 0.97 at 08:20, exceeding the 1 GiB limit and triggering OOM kills. (`metric:notification-service/mem_util`)
**Contradicting:**
- GC overhead warnings (>30 % time in GC) appear continuously from 07:35:06 to 08:19:52 (153 occurrences). (`log:f681f54530df`)
- Consumer lag stayed near baseline (≈100 messages) through 07:50, then jumped to 2,981 at 07:53 and climbed to 53,110 by 08:17 (baseline 126 messages). (`metric:notification-service/consumer_lag`)
**Assumptions:**
- ASM-5: The cache’s maximum entry count is proportional to active locales × recipients and grows with traffic, so even a bounded cache could exceed the 1 GiB limit under normal load.
**Objections:**
- [minor] alternative_not_excluded: HYP‑1 (unbounded cache) explains the same memory‑growth and GC‑overhead pattern and has not been ruled out. Until HYP‑1 is falsified, capacity‑saturation cannot be accepted as the sole cause. (not blocking: this review rejected HYP-1 or found it flawed)

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll back notification‑service to v3.9.1 or temporarily raise the pod memory limit above 1 GiB. | Stops the immediate OOM kills and restores notification delivery while the root cause is verified. (HYP-1) |
| now | mitigate | Increase the notification‑service memory limit to 1.5 GiB as a short‑term safeguard. | If the cache is bounded but the limit is insufficient (HYP‑3), this prevents further OOM kills without code changes. (HYP-3) |
| soon | fix | Add explicit eviction/TTL policy to the per‑locale template cache introduced in chg:2591. | Directly addresses the unbounded‑cache claim in HYP‑1; eliminates steady heap growth if the cache is the culprit. (HYP-1) |
| soon | fix | If the cache is already bounded, adjust the cache size configuration so total heap stays comfortably below the limit. | Resolves the capacity‑saturation scenario of HYP‑3. (HYP-3) |
| later | prevent | Add a heap‑usage alert (e.g., >80 % of limit) and GC‑overhead alert (>20 % time in GC) for notification‑service. | Early detection of memory pressure before OOM kills recur. (HYP-1) |
| later | prevent | Enforce code‑review checklist item: any new in‑process cache must declare eviction/TTL and have a size metric. | Prevents future unbounded‑cache regressions. (HYP-1) |
| soon | investigate | Collect a heap histogram / allocation‑site profile for notification‑service during the 07:35‑08:20 window (GAP‑10). | Confirms whether the TemplateCache class dominates allocations, resolving the blocking objection on HYP‑1. (HYP-1) |
| soon | investigate | Query Kafka producer metrics for orders‑service and payments‑service (byte‑rate, request size) and broker logs for the same window (GAP‑8, GAP‑6). | Rules out an undocumented upstream traffic or message‑size increase (HYP‑2). (HYP-2) |
| later | investigate | Check feature‑flag / secret‑rotation audit logs for notification‑service, orders‑service, payments‑service, and Kafka (GAP‑2). | Ensures no hidden config change altered payload size or consumer behavior. (HYP-2) |
| soon | investigate | Validate whether the cache implementation in chg:2591 includes eviction/TTL by reviewing the source diff and any related config. | Directly addresses the unsupported‑claim objection on HYP‑1 (ASM‑1/ASM‑2). (HYP-1) |

## Evidence gaps

- **get_change_history** (kafka broker configuration, topic partition changes, message.max.bytes adjustments): Change‑census does not capture infra‑level Kafka config changes that could affect inbound message size.
- **get_change_history** (feature‑flag toggles or secret rotations for notification-service, orders-service, payments-service, kafka): Flag flips or secret rotations are not represented as deploys in the census.
- **get_service_dependencies** (dependency graph depth limited to 2 hops): Possible indirect producers (e.g., scheduler or batch jobs) feeding Kafka are not shown.
- **metrics collection (not invoked)** (Kafka producer/consumer rates, message sizes, notification‑service pod memory/GC): No metric snapshots were provided; without them we cannot confirm a traffic surge.
- **query_metrics** (notification-service mem_util per‑minute series): Only summary statistics were returned; step‑size limited to 3 min for consumer_lag and no high‑resolution mem_util series available within step budget.
- **query_logs** (kafka broker logs (WARN/ERROR) for the same window): Assignment limited to notification-service and kafka services, but kafka logs were not queried; they could reveal broker‑side back‑pressure or fetch errors.
- **query_metrics** (kafka consumer‑group metrics (fetch‑rate, records‑consumed‑rate) for the notification-service group): Not fetched; needed to confirm whether processing rate dropped after each OOM restart.
- **get_metric** (Kafka producer metrics for orders‑service and payments‑service topics (rate, bytes, request size)): Needed to definitively rule out a silent upstream traffic increase.
- **get_logs** (Schema registry or topic‑level logs for any undeclared schema/serialization changes on the upstream topics): A schema change without a deploy record could alter payload size.
- **get_profile** (Notification‑service heap histogram / allocation sites during 07:35‑08:20): To confirm whether the per‑locale cache introduced by chg:2591 is the primary memory consumer.
- **query_logs** (notification-service logs 07:00‑08:20 UTC for allocation‑rate or detailed GC output): The log store returned zero matching records for 'allocation' and only generic GC‑overhead warnings; detailed heap/GC allocation logs are not available.

## Open questions

- Does the per‑recipient‑locale template cache have an eviction or TTL policy, or is it truly unbounded?
- What does a heap histogram show – is the TemplateCache class the dominant allocation site during the incident?
- Did any upstream service (orders‑service, payments‑service, or Kafka) experience an undocumented config/feature‑flag change that increased message size or rate around 07:45‑07:50?
- Are there Kafka broker configuration changes (e.g., message.max.bytes) not captured in the change census that could affect inbound payload size?
- Is the 1 GiB memory limit fundamentally insufficient for the new cache footprint under normal traffic, or would a modest limit increase suffice?
- Why are detailed GC allocation logs unavailable for notification‑service, and can logging be improved for future incidents?

## How the investigation ran

Stopped because time budget reached, after 1 round(s): 27 model calls, 14 tool calls, 124,042 tokens, 1141 s.
