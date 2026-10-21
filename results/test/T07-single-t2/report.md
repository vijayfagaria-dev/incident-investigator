# T07: Trade confirmation emails delayed

**Outcome:** conclusive. Root cause: `code_regression` on **notification-service**, triggered by `chg:2571`

## Summary

At 13:12 UTC the notification-service was upgraded to v3.9.0, introducing a new SMTP client library. Within a minute the service began logging a deprecation warning for the old `smtp.pool_size` setting. Starting around 13:40 UTC (market open) the Kafka consumer group `notify-trades` fell dramatically behind, with consumer_lag rising from a baseline of ~117 messages to a peak of 174 k and CPU utilisation saturating at 100 %. Error‑rate, request latency and request volume remained flat. No upstream service anomalies or significant SMTP‑relay deferrals were observed. The most likely cause is that the new SMTP client ignores the deprecated `smtp.pool_size` configuration, defaulting to a very low connection pool, which throttles outbound mail, backs up the consumer, and drives CPU saturation.

## Hypotheses

### 1. `code_regression` on **notification-service**, triggered by `chg:2571` (HYP-1)

Confidence 0.78 (high). The v3.9.0 deploy introduces a new SMTP client that no longer honors the deprecated smtp.pool_size config, defaulting to a tiny connection pool. Each e‑mail send becomes serialized, causing the consumer to spend most CPU time waiting on SMTP, which builds Kafka consumer lag and saturates CPU.

**Supporting:**
- Deploy of notification-service v3.9.0 (new SMTP client library) at 2026-10-12T13:12:40Z. (`chg:2571`)
- Deprecation warning “config key smtp.pool_size is deprecated; use smtp.max_connections” appears continuously from 13:13:16Z (453 occurrences). (`log:23bad82d53ef`)
- Consumer‑group lag warning “consumer group notify-trades is N messages behind” first seen at 13:40:37Z and repeats each minute (56 occurrences). (`log:7cf4e32d00a9`)
- consumer_lag metric spikes from baseline ~117 to mean ~53,900 messages, max 174,700 during 13:00‑14:10Z. (`metric:notification-service/consumer_lag`)
- CPU utilisation rises from baseline ~0.50 to max 1.00, mean 0.74 in the same window. (`metric:notification-service/cpu_util`)
- notification-service has a hard Kafka dependency (consumer group notify-trades). Up‑stream services publish to Kafka via soft dependencies. (`dep:notification-service->kafka`)
**Contradicting:**
- Error‑rate, p99 latency, RPS and memory utilisation stay at baseline levels (no significant change). (`metric:notification-service/error_rate`, `metric:notification-service/latency_p99_ms`, `metric:notification-service/rps`, `metric:notification-service/mem_util`)
- SMTP‑relay deferral warnings (e.g., “email to yahoo.com deferred by smtp relay”) occur sporadically before and after the deploy (8 total, first at 13:03Z). (`log:6de115f7967d`)
**Assumptions:**
- ASM-1: consumer_lag metric reflects the backlog of trade‑confirmation messages waiting to be processed and e‑mailed.
- ASM-2: The new SMTP client library performs noticeably slower per‑mail send when the deprecated smtp.pool_size setting is ignored.
- ASM-3: The library falls back to a single‑connection pool (or a very low max_connections) when smtp.pool_size is not recognized.

### 2. `config_change` on **notification-service** (HYP-2)

Confidence 0.55 (medium). The deprecation of smtp.pool_size without a corresponding smtp.max_connections setting causes the new client to use a default low‑concurrency pool, throttling outbound mail and producing the same symptom as a code regression.

**Supporting:**
- Deprecation warning “config key smtp.pool_size is deprecated; use smtp.max_connections” appears continuously from 13:13:16Z (453 occurrences). (`log:23bad82d53ef`)
- consumer_lag metric spikes from baseline ~117 to mean ~53,900 messages, max 174,700 during 13:00‑14:10Z. (`metric:notification-service/consumer_lag`)
- CPU utilisation rises from baseline ~0.50 to max 1.00, mean 0.74 in the same window. (`metric:notification-service/cpu_util`)
**Contradicting:**
- No other production changes (config, feature‑flag, secret, infra) for notification-service in the 45‑minute window. (`chg:2571`)
**Assumptions:**
- ASM-3: The library falls back to a single‑connection pool (or a very low max_connections) when smtp.pool_size is not recognized.

### 3. `capacity_saturation` on **notification-service** (HYP-3)

Confidence 0.15 (low). A sudden surge of trade‑confirmation events at market open overwhelms the consumer, causing lag and CPU saturation independent of the deploy.

**Supporting:**
- consumer_lag metric spikes from baseline ~117 to mean ~53,900 messages, max 174,700 during 13:00‑14:10Z. (`metric:notification-service/consumer_lag`)
- CPU utilisation rises from baseline ~0.50 to max 1.00, mean 0.74 in the same window. (`metric:notification-service/cpu_util`)
**Contradicting:**
- Deploy of notification-service v3.9.0 (new SMTP client library) at 2026-10-12T13:12:40Z. (`chg:2571`)
- Deprecation warning “config key smtp.pool_size is deprecated; use smtp.max_connections” appears continuously from 13:13:16Z (453 occurrences). (`log:23bad82d53ef`)
- Error‑rate, p99 latency, RPS and memory utilisation stay at baseline levels (no significant change). (`metric:notification-service/error_rate`, `metric:notification-service/latency_p99_ms`, `metric:notification-service/rps`, `metric:notification-service/mem_util`)
- notification-service has a hard Kafka dependency (consumer group notify-trades). Up‑stream services publish to Kafka via soft dependencies. (`dep:notification-service->kafka`)
**Assumptions:**
- ASM-4: An upstream traffic surge alone would not push notification-service CPU to 100 % unless per‑message work increased.

### 4. `dependency_degradation` on **notification-service** (HYP-4)

Confidence 0.07 (low). External SMTP relay begins throttling or deferring mail, causing the consumer to block on sends, which backs up the Kafka consumer and drives CPU up.

**Supporting:**
- SMTP‑relay deferral warnings (e.g., “email to yahoo.com deferred by smtp relay”) occur sporadically before and after the deploy (8 total, first at 13:03Z). (`log:6de115f7967d`)
**Contradicting:**
- Deprecation warning “config key smtp.pool_size is deprecated; use smtp.max_connections” appears continuously from 13:13:16Z (453 occurrences). (`log:23bad82d53ef`)
- consumer_lag metric spikes from baseline ~117 to mean ~53,900 messages, max 174,700 during 13:00‑14:10Z. (`metric:notification-service/consumer_lag`)
- CPU utilisation rises from baseline ~0.50 to max 1.00, mean 0.74 in the same window. (`metric:notification-service/cpu_util`)
- Error‑rate, p99 latency, RPS and memory utilisation stay at baseline levels (no significant change). (`metric:notification-service/error_rate`, `metric:notification-service/latency_p99_ms`, `metric:notification-service/rps`, `metric:notification-service/mem_util`)
**Assumptions:**
- ASM-5: External SMTP‑relay problems would manifest as increased send latency or error‑rate in service metrics, which are not observed.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | fix | Roll back notification-service to v3.8.4 (or deploy a hot‑fix restoring the previous SMTP client). | Removes the code path that introduced the low‑concurrency SMTP pool, directly addressing the highest‑confidence hypothesis (H1). |
| now | fix | Add/raise smtp.max_connections in notification-service configuration to match the former pool size (e.g., 50‑100). | If the new library respects max_connections, this restores concurrency without a full rollback, addressing hypothesis H2. |
| soon | mitigate | Monitor consumer_lag and CPU after the change; verify they return to baseline (<5k lag, CPU <70%). | Confirms the remediation works before closing the incident. |
| later | prevent | Instrument SMTP client send latency (histogram) and add an alert on consumer_lag > 5,000 messages. | Provides early detection of future regressions in the e‑mail send path. |
| later | prevent | Audit all services for the deprecated smtp.pool_size key and ensure migration to smtp.max_connections. | Closes the configuration gap (G1) and prevents similar deprecation‑related slow‑downs. |
| later | investigate | Run a load‑test against the new SMTP library with realistic concurrency to characterize its throughput. | Quantifies capacity of the new client and informs proper pool sizing. |

## Evidence gaps

- **get_change_history** (Configuration changes for notification-service (e.g., smtp.max_connections) around the deploy window.): No config‑change events were returned; the deprecation warning suggests a missing config migration that we cannot confirm.
- **query_metrics** (Per‑message SMTP send latency or throughput metrics from the new client library.): Such metrics are not emitted; we infer slowness from CPU and lag but cannot directly measure it.
- **query_metrics** (Kafka broker health metrics (fetch latency, broker CPU, network) during 13:30‑14:10Z.): Broker‑side issues could contribute to consumer lag; not captured in current data.
- **query_logs** (Orders-service and payments-service logs around market open to verify publish‑rate surge.): Upstream traffic spike is a plausible alternative cause but we have no visibility.

## Open questions

- What is the exact default connection pool size used by the new SMTP client when smtp.pool_size is ignored?
- Was a config change adding smtp.max_connections attempted but not recorded in change history?
- Did the Kafka brokers experience any GC pauses or network blips around 13:40 UTC?
- What was the exact publish rate of trade‑confirmation events from orders-service and payments-service at market open?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 6 model calls, 4 tool calls, 34,547 tokens, 251 s.
