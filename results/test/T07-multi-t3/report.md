# T07: Trade confirmation emails delayed

**Outcome:** inconclusive
- the leading hypothesis has confidence 0.45, below 0.5
- HYP-1 and HYP-2 are too close to tell apart
- HYP-1 has unresolved blocking objections

## Summary

Trade confirmation emails began arriving 20+ minutes late around market open on 2026‑10‑12. The notification‑service v3.9.0 deploy (chg:2571) introduced a new SMTP client and started logging deprecated‑config warnings, while simultaneously a 2‑4× surge in trade‑fill events hit the system. Both a code regression in the new SMTP library (HYP‑1) and simple capacity saturation of a statically sized consumer pool (HYP‑2) explain the observed consumer‑lag growth and CPU rise, but neither hypothesis reaches the 0.5 confidence threshold and each has blocking objections. The investigation stopped due to time budget, leaving the root cause inconclusive.

## Hypotheses

### 1. `code_regression` on **notification-service**, triggered by `chg:2571` (HYP-1)

Confidence 0.45 (low), critic: challenge. The v3.9.0 deploy (chg:2571) replaced the SMTP client library. The new library emits a deprecated‑config warning for every processed message and appears to use a less efficient code path (e.g., synchronous DNS, no connection pooling). This raises per‑message CPU cost, slows the Kafka consumer loop, and causes consumer lag to grow exponentially while CPU utilisation climbs.

**Supporting:**
- deploy on notification-service at 13:12:40 UTC by ci/deploy-bot: notification-service v3.9.0: switch to new SMTP client library (version: 3.9.0, previous_version: 3.8.4, commit: d1e07b9, diff: +530 / -470) (`chg:2571`)
- notification-service v3.9.0 was deployed at 2026-10-12T13:12:40Z, switching to a new SMTP client library (chg:2571). (`chg:2571`)
- Deprecated SMTP config warning appears continuously from 13:13:16 UTC (413 occurrences). (`log:23bad82d53ef`)
- Consumer‑lag warning for group *notify-trades* first appears at 13:40:37 UTC and last at 14:04:41 UTC, with an example lag of 67 405 messages. (`log:7cf4e32d00a9`)
- Kafka consumer_lag metric (baseline_mean 115 msg) jumps from ~120 msg at 13:27 UTC to 1 873 msg at 13:30 UTC, then grows exponentially to 171 600 msg at 14:03 UTC. (`metric:notification-service/consumer_lag`)
- CPU utilisation rises from baseline_mean 0.50 to 0.93 by the end of the window (last point 0.9342). (`metric:notification-service/cpu_util`)
- Error rate modestly increases: baseline_mean 0.00196 → mean 0.00203, last 0.00266. (`metric:notification-service/error_rate`)
**Contradicting:**
- Request latency (p50, p99) stays within baseline (p50 ≈ 44 ms, p99 ≈ 260 ms). (`metric:notification-service/latency_p50_ms`, `metric:notification-service/latency_p99_ms`)
- SMTP deferral warnings occur throughout the window but are low volume (10 total). (`log:675685fce8c5`)
- Request rate (rps) rose from a baseline mean of 156.7 req/s to a period mean of 330.5 req/s, peaking at 640.7 req/s by 14:05 UTC. (`metric:orders-service/rps`)
- CPU utilization climbed to 100 % (max 1.0) by the end of the window, up from a baseline mean of 0.50. (`metric:orders-service/cpu_util`)
**Assumptions:**
- ASM-6: The new SMTP client library logs a deprecated‑config warning for each message processed.
- ASM-7: The new library’s code path increases per‑message CPU usage compared with the previous library.
**Objections:**
- [minor] unsupported_claim: The claim that the new SMTP library uses a less efficient code path (synchronous DNS, no connection pooling) is an assumption (ASM‑6/7) not backed by any log, metric, or change‑detail evidence.
- [blocking] alternative_not_excluded: HYP‑2 (capacity saturation) also explains the lag and CPU rise and has supporting observations (OBS‑13, 16, 8, 9). It has not been ruled out.
- [minor] gap_unaddressed: Per‑message processing latency or CPU‑per‑message data after the deploy is missing (GAP‑5, GAP‑9, GAP‑10).

### 2. `capacity_saturation` on **notification-service** (HYP-2)

Confidence 0.40 (low), critic: challenge. Market open drives a 2‑4× surge in trade‑fill events (orders‑service RPS up to ~640 req/s). The notification‑service consumer pool is statically sized; it cannot keep up with the increased event rate, so Kafka consumer lag grows exponentially, CPU saturates, and email delivery falls behind.

**Supporting:**
- Request rate (rps) rose from a baseline mean of 156.7 req/s to a period mean of 330.5 req/s, peaking at 640.7 req/s by 14:05 UTC. (`metric:orders-service/rps`)
- p50 latency stayed near baseline (observed mean 45.9 ms vs baseline 44.8 ms) and p99 latency was unchanged (observed mean 262 ms vs baseline 262 ms). (`metric:orders-service/latency_p50_ms`, `metric:orders-service/latency_p99_ms`)
- Error rate remained flat (observed mean 0.0020 vs baseline 0.0022). (`metric:orders-service/error_rate`)
- CPU utilization climbed to 100 % (max 1.0) by the end of the window, up from a baseline mean of 0.50. (`metric:orders-service/cpu_util`)
- Kafka consumer_lag metric (baseline_mean 115 msg) jumps from ~120 msg at 13:27 UTC to 1 873 msg at 13:30 UTC, then grows exponentially to 171 600 msg at 14:03 UTC. (`metric:notification-service/consumer_lag`)
- CPU utilisation rises from baseline_mean 0.50 to 0.93 by the end of the window (last point 0.9342). (`metric:notification-service/cpu_util`)
- Error rate modestly increases: baseline_mean 0.00196 → mean 0.00203, last 0.00266. (`metric:notification-service/error_rate`)
**Contradicting:**
- deploy on notification-service at 13:12:40 UTC by ci/deploy-bot: notification-service v3.9.0: switch to new SMTP client library (version: 3.9.0, previous_version: 3.8.4, commit: d1e07b9, diff: +530 / -470) (`chg:2571`)
- notification-service v3.9.0 was deployed at 2026-10-12T13:12:40Z, switching to a new SMTP client library (chg:2571). (`chg:2571`)
- Deprecated SMTP config warning appears continuously from 13:13:16 UTC (413 occurrences). (`log:23bad82d53ef`)
**Assumptions:**
- ASM-8: The notification‑service consumer pool size (threads, max.poll.records, replica count) did not change in the v3.9.0 deploy.
- ASM-9: Consumer lag is evenly distributed across partitions of the trade‑fill topic.
**Objections:**
- [blocking] alternative_not_excluded: HYP‑1 (code regression) remains plausible because the deploy and deprecated‑config warnings start before the lag surge. It has not been excluded.
- [minor] gap_unaddressed: Notification‑service consumer pool size / thread‑pool configuration and per‑partition lag uniformity are unknown (GAP‑4, GAP‑11).

### 3. `infrastructure_failure` on **notification-service** (HYP-3)

Confidence 0.04 (low), critic: reject. A Kafka broker issue or partition‑level hotspot appeared after the deploy, causing the notify‑trades consumer group to lag on specific partitions while overall traffic is normal.

**Supporting:**
- Consumer‑lag warning for group *notify-trades* first appears at 13:40:37 UTC and last at 14:04:41 UTC, with an example lag of 67 405 messages. (`log:7cf4e32d00a9`)
- Kafka consumer_lag metric (baseline_mean 115 msg) jumps from ~120 msg at 13:27 UTC to 1 873 msg at 13:30 UTC, then grows exponentially to 171 600 msg at 14:03 UTC. (`metric:notification-service/consumer_lag`)
**Contradicting:**
- No other deploy, config change, feature‑flag toggle, secret rotation, or infra work was recorded for orders-service or Kafka between 12:45 and 14:05 UTC. (`chg:2571`)
**Assumptions:**
- ASM-5: A single Kafka partition became hot after the deploy (e.g., new keying in the SMTP client).
**Objections:**
- [blocking] unsupported_claim: No broker‑side logs, leadership changes, or error metrics are presented; the hypothesis rests solely on the lag symptom.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll back notification-service to v3.8.4 to eliminate the deprecated‑config warnings and test whether per‑message CPU cost drops. | HYP‑1 predicts that reverting removes the inefficient SMTP code path and stabilises lag; a rollback can be done immediately and will also stop the warning spam. (HYP-1) |
| now | mitigate | Increase notification-service consumer replicas or thread‑pool size to absorb the market‑open event surge. | HYP‑2 predicts that adding consumer capacity will immediately reduce Kafka lag if the issue is pure saturation. (HYP-2) |
| soon | investigate | Enable per‑partition consumer‑lag metrics for the notify‑trades group (or query broker‑side lag) to determine whether lag is uniform or partition‑skewed. | Uniform lag supports HYP‑2 (capacity), while a hot partition would support HYP‑3 (infrastructure) or a library‑specific bottleneck. (HYP-2) |
| soon | investigate | Add SMTP send‑latency and outbound‑queue‑depth metrics to notification-service and capture them for the next market open. | HYP‑1 hinges on the new SMTP library being slower; without these metrics we cannot confirm or refute the per‑message cost increase (GAP‑5, GAP‑9, GAP‑10). (HYP-1) |
| soon | investigate | Retrieve the full diff for change chg:2571 (commit d1e07b9) to identify the exact SMTP library version and any configuration changes. | The current diff summary (+530/‑470) does not reveal the library swap; confirming the library change is needed to evaluate ASM‑6/7. (HYP-1) |
| soon | investigate | Document the current notification-service consumer pool size, thread‑pool configuration, and autoscaling rules. | HYP‑2 assumes a static pool; knowing the exact config will let us model whether the observed RPS surge exceeds capacity (GAP‑4, GAP‑11). (HYP-2) |
| later | prevent | Deploy an autoscaler for notification-service that adds consumer instances when consumer_lag exceeds a threshold (mirroring the fix for pir:2025‑046). | Historical incident pir:2025‑046 was resolved by pre‑scaling and autoscaling; this prevents recurrence regardless of the exact cause. (HYP-2) |
| later | fix | If rollback proves effective, refactor the new SMTP client usage to enable connection pooling, asynchronous DNS, and remove the deprecated configuration before re‑deploying v3.9.x. | Addresses the alleged inefficient code path in HYP‑1 and eliminates the warning spam. (HYP-1) |

## Evidence gaps

- **get_change_history** (Kafka configuration, feature flags, secret rotations, infra maintenance): Change census only returned a deploy for notification-service; any Kafka‑side changes in the window are unknown.
- **get_change_history** (notification-service commit diff (d1e07b9)): The diff summary (+530/-470) does not reveal which SMTP library was introduced or what configuration changed.
- **observability (logs/metrics)** (notification-service warning logs mentioned by responder): Responder notes claim continuous warnings since deploy, but log data was not queried.
- **query_metrics** (kafka consumer lag per partition for group notify-trades): Metric not exposed in current metrics catalog; needed to pinpoint whether lag is uniform or partition‑skewed.
- **query_metrics** (SMTP send latency / outbound queue depth): No metric series captured for the new SMTP client; cannot confirm if email dispatch is the bottleneck.
- **query_logs** (Detailed ERROR/EXCEPTION logs from notification-service after 13:12): Log query limited to WARN level; errors that could explain processing slowdown may be at ERROR level and were not retrieved.
- **query_metrics** (trade‑confirmation event publish rate / latency): No such metric appears in the orders‑service metric catalogue returned for the window; cannot verify publishing performance.
- **query_logs** (trade‑confirmation publish log lines): Search for “trade” at INFO+ returned zero matches; publishing may be logged at DEBUG or omitted.
- **query_metrics** (SMTP send latency metric for notification-service (13:00–14:05 UTC)): Metric not present in the service's exported metrics catalogue.
- **query_metrics** (Outbound queue depth metric for notification-service (13:00–14:05 UTC)): Metric not present in the service's exported metrics catalogue.
- **query_metrics** (notification-service consumer_lag per partition): The metrics endpoint only returns a single aggregated consumer_lag series; no per‑partition series are exposed.
- **query_logs** (notification-service WARN logs containing partition‑level consumer‑lag details): Log search for “consumer‑lag” returned zero matches, so no partition‑specific lag warnings are available in the collected logs.

## Open questions

- Does the new SMTP library actually use synchronous DNS or lack connection pooling (ASM‑6/7)?
- Is consumer lag uniform across all partitions of the notify‑trades group, or are specific partitions hot?
- What is the configured consumer replica count and thread‑pool size for notification-service?
- What is the per‑message CPU cost before and after the v3.9.0 deploy when message rate is held constant?
- Did the market‑open trade‑fill rate exceed the maximum processing capacity of the current consumer pool?
- Are there any ERROR‑level logs from notification-service after 13:12 that were not captured (GAP‑6)?

## How the investigation ran

Stopped because time budget reached, after 2 round(s): 29 model calls, 14 tool calls, 122,376 tokens, 1129 s.
