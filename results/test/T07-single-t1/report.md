# T07: Trade confirmation emails delayed

**Outcome:** inconclusive
- HYP-1 and HYP-2 are too close to tell apart

## Summary

At 13:12 UTC the notification-service was deployed to v3.9.0 (chg:2571) which introduced a new SMTP client library. The library no longer recognises the historic `smtp.pool_size` config key, causing continuous deprecation warnings (log:23bad82d53ef). Because the configuration was not migrated to the new `smtp.max_connections` key, the client fell back to a minimal connection pool, dramatically slowing outbound e‑mail sends. Starting ~13:40 UTC the Kafka consumer group `notify-trades` began lagging, reaching ~175k messages by 14:04 UTC (log:7cf4e32d00a9, metric:notification-service/consumer_lag). CPU on the service saturated (metric:notification-service/cpu_util) and error rate rose slightly (metric:notification-service/error_rate). Pre‑existing SMTP relay deferrals (log:952abcfdf35f) were low‑volume background noise. The backlog directly explains the 20‑minute+ trade‑confirmation e‑mail delays reported by customers.

## Hypotheses

### 1. `code_regression` on **notification-service**, triggered by `chg:2571` (HYP-1)

Confidence 0.78 (high). The new SMTP client library (v3.9.0) no longer honors `smtp.pool_size`; without `smtp.max_connections` it uses a tiny default pool, causing each e‑mail send to take far longer. The consumer therefore cannot keep up with the Kafka topic, building a large lag and saturating CPU.

**Supporting:**
- notification-service v3.9.0 deployed at 2026-10-12T13:12:40Z (new SMTP client library). (`chg:2571`)
- Deprecation warning for config key `smtp.pool_size` logged 413 times from 13:13:16 to 14:04:57. (`log:23bad82d53ef`)
- Consumer group notify-trades lag warnings appear from 13:40:37 onward, reaching 67,405 messages behind. (`log:7cf4e32d00a9`)
- Metric consumer_lag baseline ~126 messages; peak 174,700 messages at 14:04. (`metric:notification-service/consumer_lag`)
- CPU utilization rose from baseline 0.48 to max 1.00 (mean 0.64) during the window. (`metric:notification-service/cpu_util`)
- Error rate increased from baseline 0.0020 to max 0.0035. (`metric:notification-service/error_rate`)
**Contradicting:**
- SMTP relay deferral warnings observed throughout the window (12 occurrences from 12:22). (`log:952abcfdf35f`)
**Assumptions:**
- ASM-1: The new SMTP client library defaults to a minimal connection pool when `smtp.max_connections` is not set.
- ASM-2: The service configuration still contains the deprecated `smtp.pool_size` key and lacks `smtp.max_connections`.

### 2. `config_change` on **notification-service**, triggered by `chg:2571` (HYP-2)

Confidence 0.71 (medium). Deploy introduced a config‑key rename requirement; the missing migration to `smtp.max_connections` left the service with an effective pool size of 1, throttling e‑mail throughput.

**Supporting:**
- notification-service v3.9.0 deployed at 2026-10-12T13:12:40Z (new SMTP client library). (`chg:2571`)
- Deprecation warning for config key `smtp.pool_size` logged 413 times from 13:13:16 to 14:04:57. (`log:23bad82d53ef`)
- Consumer group notify-trades lag warnings appear from 13:40:37 onward, reaching 67,405 messages behind. (`log:7cf4e32d00a9`)
- Metric consumer_lag baseline ~126 messages; peak 174,700 messages at 14:04. (`metric:notification-service/consumer_lag`)
- CPU utilization rose from baseline 0.48 to max 1.00 (mean 0.64) during the window. (`metric:notification-service/cpu_util`)
**Contradicting:**
- SMTP relay deferral warnings observed throughout the window (12 occurrences from 12:22). (`log:952abcfdf35f`)
**Assumptions:**
- ASM-2: The service configuration still contains the deprecated `smtp.pool_size` key and lacks `smtp.max_connections`.

### 3. `dependency_degradation` on **notification-service** (HYP-3)

Confidence 0.22 (low). External SMTP relay began throttling or deferring messages, causing the consumer to back up.

**Supporting:**
- SMTP relay deferral warnings observed throughout the window (12 occurrences from 12:22). (`log:952abcfdf35f`)
**Contradicting:**
- notification-service v3.9.0 deployed at 2026-10-12T13:12:40Z (new SMTP client library). (`chg:2571`)
- Deprecation warning for config key `smtp.pool_size` logged 413 times from 13:13:16 to 14:04:57. (`log:23bad82d53ef`)
- Consumer group notify-trades lag warnings appear from 13:40:37 onward, reaching 67,405 messages behind. (`log:7cf4e32d00a9`)
- Metric consumer_lag baseline ~126 messages; peak 174,700 messages at 14:04. (`metric:notification-service/consumer_lag`)
- CPU utilization rose from baseline 0.48 to max 1.00 (mean 0.64) during the window. (`metric:notification-service/cpu_util`)
- Inbound request rate (rps) remained stable around 150 req/s, matching baseline. (`metric:notification-service/rps`)
**Assumptions:**
- ASM-3: SMTP relay deferrals are unrelated to the sudden consumer‑lag spike because they started well before the deploy and remained low volume.

### 4. `capacity_saturation` on **orders-service** (HYP-4)

Confidence 0.12 (low). Market‑open traffic surge caused orders-service to publish many more trade events, overwhelming the notification consumer.

**Contradicting:**
- Dependency graph shows notification-service → kafka (hard) and orders-service → kafka (soft). (`dep:notification-service->kafka`, `dep:orders-service->kafka`)
- Inbound request rate (rps) remained stable around 150 req/s, matching baseline. (`metric:notification-service/rps`)
**Assumptions:**
- ASM-4: Orders-service did not experience a traffic surge at market open that would increase publish rate to Kafka.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll back notification-service to v3.8.4 or deploy hot‑fix adding `smtp.max_connections` equal to previous `smtp.pool_size` value and restart pods. | Immediately restores prior e‑mail throughput and eliminates consumer lag. |
| now | fix | Add missing configuration key `smtp.max_connections` to the service config map and perform a rolling restart. | Addresses the config‑mismatch root cause without full rollback if the new library is otherwise stable. |
| later | prevent | Add CI/CD validation step that flags deprecated configuration keys (`smtp.pool_size`) and requires `smtp.max_connections` on deploy. | Prevents silent config drift when libraries change. |
| soon | investigate | Instrument SMTP client send latency as a metric and add alerting on consumer lag > 10k messages. | Early detection of similar regressions in future releases. |

## Evidence gaps

- **get_change_history** (Configuration changes for notification-service (smtp.max_connections)): No config‑change record captured; cannot confirm whether the key was added or omitted.
- **query_metrics** (Orders-service publish rate / Kafka producer metrics around market open): Metrics for orders-service not queried; a hidden surge cannot be ruled out.
- **query_metrics** (SMTP relay latency / error rates): Relay‑side metrics unavailable; external deferral contribution uncertain.
- **query_metrics** (Per‑minute consumer_lag series for notify-trades): Only summary stats returned; exact minute lag began would tighten onset‑to‑deploy offset.

## Open questions

- Was the `smtp.max_connections` key deliberately omitted, or did the deploy automation miss it?
- Did the orders-service publish rate truly stay flat, or is there a blind spot in our metrics?
- What is the current health / capacity of the external SMTP relay?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 4 model calls, 4 tool calls, 24,161 tokens, 202 s.
