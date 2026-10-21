# T07: Trade confirmation emails delayed

**Outcome:** inconclusive
- HYP-1 has unresolved blocking objections

## Summary

Trade confirmation emails began arriving 20+ minutes late shortly after market open. The only change in the window was the deployment of notification‑service v3.9.0 at 13:12 UTC, which introduced a new SMTP client library and began emitting a continuous deprecation warning for `smtp.pool_size`. Consumer lag stayed at baseline until ~13:30 UTC, then exploded to >170k messages while CPU rose to near‑saturation; error rate and request latency remained flat. Three hypotheses were examined (code regression, external relay throttling, CPU‑intensive TLS handshake), but each has blocking objections—critical claims lack supporting metrics or logs, and key evidence (per‑instance SMTP latency, relay‑side metrics, actual pool‑size values, async vs sync send path) is missing. Consequently the investigation was stopped as inconclusive after two rounds.

## Hypotheses

### 1. `code_regression` on **notification-service**, triggered by `chg:2571` (HYP-1)

Confidence 0.50 (medium), critic: challenge, capped from 0.66: it has unresolved blocking objections. The v3.9.0 deploy introduced a new SMTP client library. The deprecated config key `smtp.pool_size` is still read, yielding a too‑small connection pool. Email sends are performed synchronously on the Kafka consumer thread, so each send blocks the consumer, causing consumer lag to explode, CPU to rise, and emails to be delayed.

**Supporting:**
- deploy on notification-service at 13:12:40 UTC by ci/deploy-bot: notification-service v3.9.0: switch to new SMTP client library (version: 3.9.0, previous_version: 3.8.4, commit: d1e07b9, diff: +530 / -470) (`chg:2571`)
- notification-service v3.9.0 was deployed at 13:12:40 UTC (change chg:2571). (`chg:2571`)
- WARN log “config key smtp.pool_size is deprecated; use smtp.max_connections” begins at 13:13:16 UTC and recurs continuously (413 occurrences). (`log:23bad82d53ef`)
- Consumer lag metric stays ~100‑140 messages (baseline ≈ 117) until 13:30, then jumps to 8,230 at 13:32 and grows steadily to 174,500 by 14:02. (`metric:notification-service/consumer_lag`)
- WARN log “consumer group notify-trades is <lag> messages behind” first appears at 13:40:37 UTC reporting 67,405 messages behind and continues through 14:04. (`log:7cf4e32d00a9`)
- CPU utilization rises from a baseline mean of 0.504 to a last value of 0.934 (mean 0.771) over the window. (`metric:notification-service/cpu_util`)
- WARN log “email to <domain> deferred by smtp relay” appears first at 13:18:48 UTC (6 total occurrences). (`log:57f4c2c8de0e`)
- notification‑service v3.9.0 was deployed at 2026‑10‑12T13:12:40Z (change‑census chg:2571). (`chg:2571`)
- WARN log “config key smtp.pool_size is deprecated; use smtp.max_connections” appears 413 times from 13:13:16Z to 14:04:57Z. (`log:23bad82d53ef`)
- WARN log “consumer group notify‑trades is <lag> messages behind” appears 52 times starting 13:40:37Z, with an example lag of 67 405 messages at 14:04:41Z. (`log:7cf4e32d00a9`)
- WARN log “email to <domain> deferred by smtp relay” appears 6 times from 13:18:48Z to 14:04:33Z. (`log:57f4c2c8de0e`)
- Consumer‑lag metric baseline ≈118 messages; it stays ~100‑140 until 13:30Z, then jumps to 8 230 at 13:32Z and climbs monotonically to 174 500 by 14:02Z. (`metric:notification-service/consumer_lag`)
- CPU utilization rises from baseline 0.504 to 0.934 (near saturation) by the end of the window. (`metric:notification-service/cpu_util`)
**Contradicting:**
- Error rate remains at or below baseline (mean 0.00198 vs baseline 0.00205); no error‑rate spike observed. (`metric:notification-service/error_rate`)
- Request latency (p50 ~44 ms, p99 ~267 ms) stays within baseline ranges throughout. (`metric:notification-service/latency_p50_ms`, `metric:notification-service/latency_p99_ms`)
- Error rate remains steady around the baseline 0.002 (min 0.00068, max 0.0035). (`metric:notification-service/error_rate`)
- p50 latency stays at the baseline 44.8 ms; p99 latency rises modestly from baseline 255 ms to an average 267 ms. (`metric:notification-service/latency_p50_ms`, `metric:notification-service/latency_p99_ms`)
- Error rate remains flat around baseline (mean 0.00200 vs baseline 0.00205; min 0.00068, max 0.0035) with no spike at deploy. (`metric:notification-service/error_rate`)
- Request latency stays within baseline: p50 mean 44.9 ms (baseline 44.7 ms); p99 mean 264.6 ms (baseline 256.7 ms). (`metric:notification-service/latency_p50_ms`, `metric:notification-service/latency_p99_ms`)
**Assumptions:**
- ASM-6: The deprecated key `smtp.pool_size` is still consulted by the new client and its value limits the connection pool.
- ASM-7: The client sends mail on the Kafka consumer thread (no async hand‑off).
- ASM-8: No other config change (pool size, max_connections, feature flag) occurred at 13:12.
**Objections:**
- [blocking] unsupported_claim: Claims that email sends are performed synchronously on the Kafka consumer thread and that the deprecated `smtp.pool_size` results in an undersized pool; neither claim is backed by logs, metrics or change history.
- [minor] alternative_not_excluded: HYP-2 (external SMTP relay throttling) offers a plausible competing explanation and has not been ruled out. (not blocking: this review rejected HYP-2 or found it flawed)
- [blocking] gap_unaddressed: Missing per‑instance SMTP send latency / outbound queue metrics and the actual numeric values of `smtp.pool_size` / `smtp.max_connections` at deploy time.

### 2. `dependency_degradation` on **notification-service**, triggered by `chg:2571` (HYP-2)

Confidence 0.22 (low), critic: challenge. The new SMTP client library is functionally correct, but the external SMTP relay begins throttling/deferring at 13:18 (first “deferred” warning). Because the client still sends synchronously on the consumer thread, each deferral blocks the thread, causing the lag explosion at ~13:32 and the CPU rise.

**Supporting:**
- WARN log “email to <domain> deferred by smtp relay” appears first at 13:18:48 UTC (6 total occurrences). (`log:57f4c2c8de0e`)
- WARN log “email to <domain> deferred by smtp relay” appears 6 times from 13:18:48Z to 14:04:33Z. (`log:57f4c2c8de0e`)
- Consumer lag metric stays ~100‑140 messages (baseline ≈ 117) until 13:30, then jumps to 8,230 at 13:32 and grows steadily to 174,500 by 14:02. (`metric:notification-service/consumer_lag`)
- Consumer‑lag metric baseline ≈118 messages; it stays ~100‑140 until 13:30Z, then jumps to 8 230 at 13:32Z and climbs monotonically to 174 500 by 14:02Z. (`metric:notification-service/consumer_lag`)
- WARN log “consumer group notify-trades is <lag> messages behind” first appears at 13:40:37 UTC reporting 67,405 messages behind and continues through 14:04. (`log:7cf4e32d00a9`)
- WARN log “consumer group notify‑trades is <lag> messages behind” appears 52 times starting 13:40:37Z, with an example lag of 67 405 messages at 14:04:41Z. (`log:7cf4e32d00a9`)
- CPU utilization rises from a baseline mean of 0.504 to a last value of 0.934 (mean 0.771) over the window. (`metric:notification-service/cpu_util`)
- CPU utilization rises from baseline 0.504 to 0.934 (near saturation) by the end of the window. (`metric:notification-service/cpu_util`)
- CPU utilisation rises from baseline mean 0.504 to a last value of 0.974 (mean over window 0.786), reaching near‑saturation by 14:10 UTC. (`metric:notification-service/cpu_util`)
**Contradicting:**
- deploy on notification-service at 13:12:40 UTC by ci/deploy-bot: notification-service v3.9.0: switch to new SMTP client library (version: 3.9.0, previous_version: 3.8.4, commit: d1e07b9, diff: +530 / -470) (`chg:2571`)
- notification-service v3.9.0 was deployed at 13:12:40 UTC (change chg:2571). (`chg:2571`)
- WARN log “config key smtp.pool_size is deprecated; use smtp.max_connections” begins at 13:13:16 UTC and recurs continuously (413 occurrences). (`log:23bad82d53ef`)
- notification‑service v3.9.0 was deployed at 2026‑10‑12T13:12:40Z (change‑census chg:2571). (`chg:2571`)
- WARN log “config key smtp.pool_size is deprecated; use smtp.max_connections” appears 413 times from 13:13:16Z to 14:04:57Z. (`log:23bad82d53ef`)
- Starting at 13:13:16 UTC the new client emitted the warning “config key smtp.pool_size is deprecated; use smtp.max_connections” continuously (413 occurrences). (`log:23bad82d53ef`)
**Assumptions:**
- ASM-9: The external SMTP relay began rate‑limiting at 13:18 and the deferral codes are the primary cause of the block.
- ASM-10: The client does not retry asynchronously; each deferral blocks the consumer thread.
- ASM-11: No internal config change (pool size) contributed to the slowdown.
**Objections:**
- [blocking] unsupported_claim: Asserts that the external SMTP relay began throttling at 13:18 and that each deferral blocks the consumer thread; relay‑side logs or metrics are not available.
- [minor] alternative_not_excluded: HYP-1 (code regression due to pool‑size misconfiguration) remains a viable cause and has not been excluded. (not blocking: this review rejected HYP-1 or found it flawed)

### 3. `resource_exhaustion` on **notification-service**, triggered by `chg:2571` (HYP-3)

Confidence 0.12 (low), critic: challenge. The new SMTP client library is CPU‑intensive (e.g., performs a full TLS handshake per message), driving CPU to saturation. The consumer thread spends most cycles in the client, so lag grows and mail is delayed.

**Supporting:**
- CPU utilization rises from a baseline mean of 0.504 to a last value of 0.934 (mean 0.771) over the window. (`metric:notification-service/cpu_util`)
- CPU utilization rises from baseline 0.504 to 0.934 (near saturation) by the end of the window. (`metric:notification-service/cpu_util`)
- CPU utilisation rises from baseline mean 0.504 to a last value of 0.974 (mean over window 0.786), reaching near‑saturation by 14:10 UTC. (`metric:notification-service/cpu_util`)
- Consumer lag metric stays ~100‑140 messages (baseline ≈ 117) until 13:30, then jumps to 8,230 at 13:32 and grows steadily to 174,500 by 14:02. (`metric:notification-service/consumer_lag`)
- Consumer‑lag metric baseline ≈118 messages; it stays ~100‑140 until 13:30Z, then jumps to 8 230 at 13:32Z and climbs monotonically to 174 500 by 14:02Z. (`metric:notification-service/consumer_lag`)
- WARN log “consumer group notify-trades is <lag> messages behind” first appears at 13:40:37 UTC reporting 67,405 messages behind and continues through 14:04. (`log:7cf4e32d00a9`)
- WARN log “consumer group notify‑trades is <lag> messages behind” appears 52 times starting 13:40:37Z, with an example lag of 67 405 messages at 14:04:41Z. (`log:7cf4e32d00a9`)
**Contradicting:**
- Error rate remains at or below baseline (mean 0.00198 vs baseline 0.00205); no error‑rate spike observed. (`metric:notification-service/error_rate`)
- Request latency (p50 ~44 ms, p99 ~267 ms) stays within baseline ranges throughout. (`metric:notification-service/latency_p50_ms`, `metric:notification-service/latency_p99_ms`)
- Error rate remains steady around the baseline 0.002 (min 0.00068, max 0.0035). (`metric:notification-service/error_rate`)
- p50 latency stays at the baseline 44.8 ms; p99 latency rises modestly from baseline 255 ms to an average 267 ms. (`metric:notification-service/latency_p50_ms`, `metric:notification-service/latency_p99_ms`)
- Error rate remains flat around baseline (mean 0.00200 vs baseline 0.00205; min 0.00068, max 0.0035) with no spike at deploy. (`metric:notification-service/error_rate`)
- Request latency stays within baseline: p50 mean 44.9 ms (baseline 44.7 ms); p99 mean 264.6 ms (baseline 256.7 ms). (`metric:notification-service/latency_p50_ms`, `metric:notification-service/latency_p99_ms`)
- WARN log “config key smtp.pool_size is deprecated; use smtp.max_connections” begins at 13:13:16 UTC and recurs continuously (413 occurrences). (`log:23bad82d53ef`)
- WARN log “config key smtp.pool_size is deprecated; use smtp.max_connections” appears 413 times from 13:13:16Z to 14:04:57Z. (`log:23bad82d53ef`)
- Starting at 13:13:16 UTC the new client emitted the warning “config key smtp.pool_size is deprecated; use smtp.max_connections” continuously (413 occurrences). (`log:23bad82d53ef`)
**Assumptions:**
- ASM-12: The new library performs a full TLS handshake (or similar expensive work) for every outbound mail.
- ASM-13: No other workload change explains the CPU rise.
**Objections:**
- [blocking] unsupported_claim: Claims the new client performs a full TLS handshake per message, driving CPU to saturation; no GC‑pause, thread‑pool queue or TLS‑latency metrics support this.
- [minor] ignores_contradiction: Error rate and request latency stay at baseline while the hypothesis predicts a systemic slowdown that would likely surface in those metrics.
- [minor] alternative_not_excluded: Both HYP-1 and HYP-2 remain plausible and have not been ruled out. (not blocking: this review rejected HYP-1 or found it flawed)

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll back notification‑service to v3.8.4 (the previous stable version). | All three hypotheses share the deploy as the trigger; a rollback will immediately stop the lag growth and email delay while root cause is pursued. (HYP-1) |
| soon | fix | Replace the deprecated `smtp.pool_size` configuration with the supported `smtp.max_connections` and set an appropriately sized pool. | HYP-1 posits that the deprecated key yields an undersized connection pool, causing synchronous sends to block the Kafka consumer. (HYP-1) |
| soon | fix | Refactor email sending to run asynchronously (e.g., hand off to a worker pool or separate thread) instead of blocking the Kafka consumer thread. | Both HYP-1 and HYP-2 assume synchronous sends on the consumer thread; decoupling removes the direct path from SMTP latency to consumer lag. (HYP-1) |
| later | prevent | Add service‑level metrics for SMTP send latency, outbound queue depth, and thread‑pool/connection‑pool queue length; expose per‑instance breakdowns. | Current metric catalogue lacks these series (GAP‑2, GAP‑5, GAP‑15), preventing verification of a step increase at deploy and future regressions. |
| later | investigate | Obtain external SMTP relay logs and metrics (deferral codes, rate‑limit counters) for the 13:18 UTC window. | HYP-2 claims relay throttling began at 13:18, but relay‑side data is unavailable (GAP‑4, GAP‑7). (HYP-2) |
| later | investigate | Audit the notification‑service ConfigMap/Secret to retrieve the exact numeric values of `smtp.pool_size` and `smtp.max_connections` at deploy time. | HYP-1's core claim about an undersized pool cannot be verified without the actual config values (GAP‑9, GAP‑14). (HYP-1) |
| later | investigate | Profile the new SMTP client library for per‑message CPU cost (e.g., TLS handshake) and capture GC pause / thread‑pool queue metrics. | HYP-3 attributes CPU saturation to a full TLS handshake per email, yet no profiling or GC data exists (GAP‑2, GAP‑17). (HYP-3) |
| later | investigate | Identify any upstream services that call notification‑service directly (internal APIs triggering emails) to rule out hidden traffic spikes. | Dependency graph only shows downstream Kafka consumption; unknown callers could affect load (GAP‑11). |

## Evidence gaps

- **query_metrics** (kafka broker metrics (produce rate, consume rate, broker‑reported consumer lag)): Not queried; needed to confirm whether the backlog originates from producer surge or consumer slowdown.
- **query_metrics** (per‑instance notification-service metrics (SMTP send latency, thread‑pool queue length, GC pauses)): Only service‑aggregated metrics were available; instance‑level detail could pinpoint the bottleneck.
- **query_logs** (ERROR‑level logs for notification-service): Only WARN patterns returned; absence of ERROR logs could hide crashes or exceptions.
- **query_logs** (SMTP relay / mail‑gateway logs): External relay deferral warnings seen, but relay‑side logs not accessible via current tooling.
- **query_metrics** (email‑send latency / outbound queue depth): No metric exposing per‑email send time or SMTP queue length is available for notification‑service.
- **query_logs** (INFO‑level successful email‑send records): Only WARN+ patterns were fetched; successful send throughput cannot be compared pre/post deploy.
- **query_metrics** (SMTP relay health (external)): Relay‑side metrics (deferral codes, connection limits) are not collected in our platform.
- **query_logs** (Rollback verification logs): No rollback has been performed yet, so post‑rollback behavior is unknown.
- **get_change_history** (notification‑service configuration (SMTP host, credentials, pool size) and any feature‑flag state for the new SMTP client): Change census only records deploys; config or flag changes are not captured.
- **get_change_history** (Secret rotations for SMTP credentials or Kafka SASL/SSL secrets): Secret rotations are not represented in the change log.
- **get_service_dependencies** (Potential upstream callers of notification‑service (e.g., internal APIs that trigger emails)): Dependency graph only shows downstream deps; upstream services are missing.
- **get_change_history** (Kafka broker health metrics (broker CPU, disk, network) and topic‑level producer/consumer metrics for the window): No infra‑level metrics were queried; broker issues could affect consumer lag.
- **get_change_history** (config, feature_flag, secret_rotation, infra for notification-service 13:00‑13:30 UTC): The change‑history API records only change events, not the actual configuration values or feature‑flag states at a point in time.
- **get_change_history** (ConfigMap/Secret version history for notification-service SMTP settings): No tool in the current toolbox exposes the stored key/value pairs; an audit of the config store is required to retrieve the numeric pool size and max_connections values.
- **query_metrics** (notification-service metrics catalogue (13:10‑14:10 UTC)): Service does not emit smtp_send_latency_ms or any thread‑pool / connection‑pool queue‑length metric, preventing direct verification of a step increase at deploy.
- **query_metrics** (per‑instance breakdown of CPU, lag, latency): Current API returns only service‑wide aggregates; instance‑level outliers cannot be examined.
- **query_logs** (DEBUG‑level SMTP client logs around deploy): Log collection limited to WARN+; detailed send timings are not captured.

## Open questions

- What are the exact runtime values of `smtp.pool_size` / `smtp.max_connections` after the v3.9.0 deploy?
- Does the notification‑service perform email sends synchronously on the Kafka consumer thread, or is there an async hand‑off?
- Did the external SMTP relay actually throttle or defer messages starting at 13:18 UTC, and what were the relay‑side deferral codes?
- How much CPU time does the new SMTP client consume per outbound email (e.g., full TLS handshake vs session reuse)?
- Why do error rate and request latency remain at baseline while consumer lag and CPU explode?
- What is the per‑instance distribution of consumer lag and CPU – is a single instance driving the aggregate?
- Are there any secret rotations or feature‑flag changes for SMTP credentials or the new client that were not captured in the change log?
- What upstream services (if any) invoke notification‑service directly, and could they have contributed to load?

## How the investigation ran

Stopped because reached the limit of 2 rounds, after 2 round(s): 31 model calls, 13 tool calls, 146,995 tokens, 670 s.
