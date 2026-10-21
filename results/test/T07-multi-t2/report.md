# T07: Trade confirmation emails delayed

**Outcome:** inconclusive
- HYP-1 has unresolved blocking objections

## Summary

Trade confirmation emails began arriving 20+ minutes late around market open (≈13:30 UTC). A deploy of notification‑service v3.9.0 at 13:12 UTC introduced a new SMTP client and a deprecated config warning, and consumer lag and CPU rose sharply after the traffic surge. Two leading hypotheses remain viable: a code regression in the new SMTP library (HYP‑1) and simple capacity saturation of the fixed‑parallelism consumer (HYP‑2). Because per‑message SMTP latency, consumer fetch‑rate, and upstream trade‑event production metrics are missing, neither hypothesis can be confirmed, so the investigation is inconclusive.

## Hypotheses

### 1. `code_regression` on **notification-service**, triggered by `chg:2571` (HYP-1)

Confidence 0.50 (medium), critic: challenge, capped from 0.62: it has unresolved blocking objections. The v3.9.0 deploy replaces the SMTP client library. The new library adds per‑message CPU and latency overhead (more TLS work, stricter validation, synchronous retries). At the low pre‑open load the consumer keeps up, but when the trade‑event rate jumps ~4× at 13:30 UTC the consumer cannot drain the Kafka queue fast enough; consumer‑lag grows exponentially and CPU climbs to ~1.0.

**Supporting:**
- deploy on notification-service at 13:12:40 UTC by ci/deploy-bot: notification-service v3.9.0: switch to new SMTP client library (version: 3.9.0, previous_version: 3.8.4, commit: d1e07b9, diff: +530 / -470) (`chg:2571`)
- Starting at 13:13:16 UTC the notification-service logged the deprecation warning “config key smtp.pool_size is deprecated; use smtp.max_connections” continuously (413 occurrences). (`log:23bad82d53ef`)
- Consumer‑lag metric (baseline ≈ 117 messages) stayed around 100‑200 until 13:30 UTC, then rose to 1 873 at 13:30, 14 580 at 13:33, and reached 171 600 by 14:03 UTC. (`metric:notification-service/consumer_lag`)
- CPU utilisation climbed from a baseline mean of 0.50 to a period mean of 0.72, peaking near 1.0 after 13:30 UTC. (`metric:notification-service/cpu_util`)
- notification-service was deployed to v3.9.0 at 2026-10-12T13:12:40Z, replacing the SMTP client library (chg:2571). (`chg:2571`)
- Deploy of notification‑service v3.9.0 occurred at 13:12:40 UTC (chg:2571). (`chg:2571`)
- Consumer lag baseline ≈117 msg; stayed ~100‑200 until 13:30 UTC, then jumped to 1 873 at 13:30, 14 580 at 13:33, reaching 171 600 by 14:03 UTC. (`metric:notification-service/consumer_lag`)
- CPU utilisation rose from baseline mean 0.505 to window mean 0.725, peaking near 1.0 after 13:30 UTC. (`metric:notification-service/cpu_util`)
- Deprecation warning “config key smtp.pool_size is deprecated; use smtp.max_connections” logged continuously from 13:13:16 UTC (413 occurrences). (`log:23bad82d53ef`)
**Contradicting:**
- Error‑rate (baseline ≈ 0.002) and latency‑p99 (baseline ≈ 260 ms) remained essentially unchanged throughout the window. (`metric:notification-service/error_rate`, `metric:notification-service/latency_p99_ms`)
- Latency‑p50 remained flat: window mean 45.0 ms vs baseline 44.4 ms; min 37.8 ms, max 52.2 ms. (`metric:notification-service/latency_p50_ms`)
- Latency‑p99 remained flat: window mean 263 ms vs baseline 260 ms; min 202 ms, max 315 ms. (`metric:notification-service/latency_p99_ms`)
- Error rate unchanged: window mean 0.00201 vs baseline 0.00199. (`metric:notification-service/error_rate`)
**Assumptions:**
- ASM-6: The new SMTP client library adds measurable per‑message processing time (CPU + wall‑clock) compared with the old library.
- ASM-7: The added per‑message cost is small enough to be invisible at the pre‑open load (~110 msg/s) but becomes decisive at ~460 msg/s.
- ASM-8: No other code change in v3.9.0 touches the consumer loop.
**Objections:**
- [minor] gap_unaddressed: Per‑message SMTP send / message‑handle latency metric is not exposed (GAP‑4, GAP‑10); without it the claim of added CPU/latency overhead cannot be verified.
- [blocking] alternative_not_excluded: Capacity‑saturation hypothesis (HYP-2) explains the same lag and CPU pattern and has not been ruled out.

### 2. `capacity_saturation` on **notification-service** (HYP-2)

Confidence 0.33 (low), critic: challenge. At market open (~13:30 UTC) orders‑service publishes ~4× more trade events (Kafka ingress rises from ~110 to ~460 msg/s). The notification‑service consumer group (`notify‑trades`) runs with fixed parallelism and cannot sustain the higher inbound rate, so its lag grows and CPU rises as workers stay busy. The v3.9.0 deploy is coincidental.

**Supporting:**
- Message ingress rate rose from ~110 msg/s (baseline) to ~460 msg/s beginning at 13:30 UTC and stayed elevated until 14:05 UTC. (`metric:kafka/messages_in_per_s`)
- Consumer‑lag metric (baseline ≈ 117 messages) stayed around 100‑200 until 13:30 UTC, then rose to 1 873 at 13:30, 14 580 at 13:33, and reached 171 600 by 14:03 UTC. (`metric:notification-service/consumer_lag`)
- CPU utilisation climbed from a baseline mean of 0.50 to a period mean of 0.72, peaking near 1.0 after 13:30 UTC. (`metric:notification-service/cpu_util`)
- orders-service has a downstream dependency on Kafka (dep:orders-service→kafka) with soft criticality. (`dep:orders-service->kafka`)
- Consumer lag baseline ≈117 msg; stayed ~100‑200 until 13:30 UTC, then jumped to 1 873 at 13:30, 14 580 at 13:33, reaching 171 600 by 14:03 UTC. (`metric:notification-service/consumer_lag`)
- CPU utilisation rose from baseline mean 0.505 to window mean 0.725, peaking near 1.0 after 13:30 UTC. (`metric:notification-service/cpu_util`)
**Contradicting:**
- deploy on notification-service at 13:12:40 UTC by ci/deploy-bot: notification-service v3.9.0: switch to new SMTP client library (version: 3.9.0, previous_version: 3.8.4, commit: d1e07b9, diff: +530 / -470) (`chg:2571`)
- Starting at 13:13:16 UTC the notification-service logged the deprecation warning “config key smtp.pool_size is deprecated; use smtp.max_connections” continuously (413 occurrences). (`log:23bad82d53ef`)
- notification-service was deployed to v3.9.0 at 2026-10-12T13:12:40Z, replacing the SMTP client library (chg:2571). (`chg:2571`)
- Deploy of notification‑service v3.9.0 occurred at 13:12:40 UTC (chg:2571). (`chg:2571`)
- Deprecation warning “config key smtp.pool_size is deprecated; use smtp.max_connections” logged continuously from 13:13:16 UTC (413 occurrences). (`log:23bad82d53ef`)
**Assumptions:**
- ASM-9: Orders‑service trade‑event production rate truly steps up at 13:30 (market open) and stays at ~460 msg/s for the window.
- ASM-10: The notification‑service consumer parallelism is static (no autoscaling) and its max sustainable throughput is < 460 msg/s.
- ASM-11: Kafka broker resources are not limiting (CPU normal, no under‑replicated partitions).
**Objections:**
- [blocking] alternative_not_excluded: Code‑regression hypothesis (HYP-1) remains plausible; without per‑message latency or consumer‑fetch metrics we cannot confirm the deploy is innocuous.
- [minor] gap_unaddressed: Orders‑service trade‑event production rate metric not captured (GAP‑5); consumer‑group fetch‑rate/poll‑latency also missing (GAP‑6, GAP‑12).

### 3. `config_change` on **notification-service**, triggered by `chg:2571` (HYP-3)

Confidence 0.05 (low), critic: reject. The deploy leaves the deprecated `smtp.pool_size` config in place; the new library ignores it and defaults to a very small `smtp.max_connections`. Under low load the pool suffices, but when the message rate spikes the outbound SMTP connection pool saturates, causing retries/back‑pressure that inflates consumer‑lag and CPU.

**Supporting:**
- Starting at 13:13:16 UTC the notification-service logged the deprecation warning “config key smtp.pool_size is deprecated; use smtp.max_connections” continuously (413 occurrences). (`log:23bad82d53ef`)
- Consumer‑lag metric (baseline ≈ 117 messages) stayed around 100‑200 until 13:30 UTC, then rose to 1 873 at 13:30, 14 580 at 13:33, and reached 171 600 by 14:03 UTC. (`metric:notification-service/consumer_lag`)
- CPU utilisation climbed from a baseline mean of 0.50 to a period mean of 0.72, peaking near 1.0 after 13:30 UTC. (`metric:notification-service/cpu_util`)
- Deprecation warning “config key smtp.pool_size is deprecated; use smtp.max_connections” logged continuously from 13:13:16 UTC (413 occurrences). (`log:23bad82d53ef`)
**Contradicting:**
- Error‑rate (baseline ≈ 0.002) and latency‑p99 (baseline ≈ 260 ms) remained essentially unchanged throughout the window. (`metric:notification-service/error_rate`, `metric:notification-service/latency_p99_ms`)
- Latency‑p50 remained flat: window mean 45.0 ms vs baseline 44.4 ms; min 37.8 ms, max 52.2 ms. (`metric:notification-service/latency_p50_ms`)
- Latency‑p99 remained flat: window mean 263 ms vs baseline 260 ms; min 202 ms, max 315 ms. (`metric:notification-service/latency_p99_ms`)
- Error rate unchanged: window mean 0.00201 vs baseline 0.00199. (`metric:notification-service/error_rate`)
- SMTP relay deferral warnings observed at low rate (8 total) across the whole window, first at 13:03:00 UTC. (`log:6de115f7967d`)
**Assumptions:**
- ASM-12: The new library’s default `smtp.max_connections` is dramatically lower than the previous pool size.
- ASM-13: SMTP relay latency is low enough that pool exhaustion would manifest as a sharp increase in send latency, which we do not observe.
**Objections:**
- [blocking] ignores_contradiction: SMTP deferral warnings are low and pre‑date the deploy; error rate and latency metrics show no degradation, contradicting pool‑exhaustion claim.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll back notification‑service to v3.8.4 (or disable the new SMTP client) to stop lag growth immediately. | If the regression in the new SMTP library is the cause (HYP‑1), a rollback will flatten the lag curve even under peak load. (HYP-1) |
| now | mitigate | Add a second consumer instance (or increase the thread pool) for the notify‑trades group. | If capacity saturation is the cause (HYP‑2), extra parallelism will immediately arrest lag growth without a code rollback. (HYP-2) |
| soon | fix | Update the notification‑service configuration to set `smtp.max_connections` to a suitably high value and remove the deprecated `smtp.pool_size`. | Addresses the config‑change hypothesis (HYP‑3) and eliminates a possible SMTP‑pool bottleneck if it contributes. (HYP-3) |
| later | prevent | Instrument notification‑service with per‑message SMTP send latency and message‑handle latency metrics. | Closes GAP‑4 / GAP‑10 so future regressions in the SMTP client can be detected instantly. (HYP-1) |
| later | prevent | Expose Kafka consumer‑group metrics (fetch‑rate, poll‑latency, offset‑lag) for `notify‑trades`. | Closes GAP‑6 / GAP‑12, allowing quick discrimination between consumer‑side and broker‑side bottlenecks. (HYP-2) |
| soon | investigate | Collect orders‑service trade‑event production rate metrics for the 13:00‑14:05 UTC window. | Fills GAP‑5 to verify whether the 4× traffic spike aligns with the lag onset. (HYP-2) |
| soon | investigate | Retrieve notification‑service DEBUG/TRACE logs around message handling for the incident window. | Addresses GAP‑7; fine‑grained logs may reveal retries, throttling, or TLS overhead in the new SMTP client. (HYP-1) |

## Evidence gaps

- **query_metrics** (Kafka broker disk I/O, request latency, and partition leadership metrics): These metrics are not exposed in the current metric catalogue; they are needed to rule out broker‑side I/O or leadership churn.
- **query_metrics** (Consumer‑lag metrics for notification-service (or its consumer group)): Consumer lag is the direct indicator of email‑delivery delay but was not available in the queried metric set.
- **query_logs** (Kafka broker logs at WARN/ERROR for the period 13:00‑14:05): Log query returned zero patterns; broker logs may be routed elsewhere or require a different source.
- **query_metrics** (notification-service per‑message processing latency / SMTP send latency): No metric exposing time spent in the new SMTP client; needed to confirm processing slowdown.
- **query_metrics** (orders-service trade‑event production rate): Production rate not captured in current metric set; cannot verify if upstream traffic surge contributed.
- **query_metrics** (kafka consumer‑group fetch‑rate, poll‑latency, and offset‑lag for notify‑trades): Kafka‑level consumer metrics were not queried; they would clarify whether the broker or consumer is the bottleneck.
- **query_logs** (notification-service DEBUG/TRACE logs around message handling): Only WARN+ logs were retrieved; finer‑grained logs could reveal throttling or retries in the SMTP client.
- **get_service_dependencies** (Kafka downstream dependencies (to confirm notification-service consumes from Kafka)): The dependency call for notification-service returned no upstreams; a separate call for Kafka downstream was not made.
- **get_service_dependencies** (payments-service downstream dependencies (to verify its path to Kafka)): payments-service dependencies were not queried; we only have orders-service graph.
- **query_metrics** (per‑message SMTP send latency / message‑handle latency): No such metric exists in notification‑service metric catalog; only generic request latency (p50/p99) is available.
- **query_metrics** (high‑resolution time‑series points for latency_p50_ms and latency_p99_ms): Summary endpoint returned only aggregated stats; point‑level data needed to pinpoint exact minute‑level changes.
- **query_metrics** (kafka consumer_fetch_rate, consumer_poll_latency, consumer_offset_lag for group notify-trades): Metric names not present in kafka or notification-service metric catalogs (available metrics listed do not include consumer‑group fetch‑rate, poll‑latency, or offset‑lag).
- **query_logs** (notification-service WARN logs containing 'fetch' between 13:00‑14:05 UTC): No matching log patterns returned; fetch‑related warnings are absent.

## Open questions

- What is the per‑message SMTP send / message‑handle latency after the v3.9.0 deploy? (GAP‑4, GAP‑10)
- What is the Kafka consumer‑group fetch‑rate, poll‑latency, and offset‑lag for `notify‑trades`? (GAP‑6, GAP‑12)
- What was the exact orders‑service trade‑event production rate at market open? (GAP‑5)
- Does the deprecated `smtp.pool_size` config affect the new library’s connection pool size? (HYP‑3 config question)
- Are there any broker‑side I/O or leadership changes that could contribute? (GAP‑1, GAP‑3)
- Why were SMTP relay deferral warnings low and pre‑dating the deploy? (OBS‑21, contradicts HYP‑3)

## How the investigation ran

Stopped because time budget reached, after 2 round(s): 31 model calls, 16 tool calls, 122,697 tokens, 946 s.
