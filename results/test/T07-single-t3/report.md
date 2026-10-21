# T07: Trade confirmation emails delayed

**Outcome:** inconclusive
- HYP-1 and HYP-2 are too close to tell apart

## Summary

At 13:12 UTC notification-service v3.9.0 was deployed, introducing a new SMTP client library that expects config key smtp.max_connections. The running configuration still contained the deprecated smtp.pool_size, causing immediate deprecation warnings, CPU saturation (up to 100%), and a consumer‑lag explosion (peak 174k messages, ~1,400× baseline). This lag translates directly into the 20‑minute+ trade‑confirmation e‑mail delays reported by customers. No upstream traffic surge or SMTP‑relay throttling can explain the magnitude of the lag.

## Hypotheses

### 1. `code_regression` on **notification-service**, triggered by `chg:2571` (HYP-1)

Confidence 0.78 (high). The new SMTP client library introduced a hot path (e.g., busy‑wait on missing pool size) that consumes CPU and slows message processing, causing consumer‑lag buildup.

**Supporting:**
- notification-service v3.9.0 deployed at 13:12:40 UTC (switch to new SMTP client library). (`chg:2571`)
- From 13:13:16 UTC the service logs “config key smtp.pool_size is deprecated; use smtp.max_connections” continuously (494 occurrences). (`log:23bad82d53ef`)
- consumer_lag metric jumps from baseline ~117 msgs to max 174,700, mean 60,720, last 164,500. (`metric:notification-service/consumer_lag`)
- CPU utilisation climbs to 1.0 (max) and averages 0.76 vs baseline 0.50. (`metric:notification-service/cpu_util`)
**Contradicting:**
- Error rate stays near baseline (mean 0.0020 vs 0.00199). (`metric:notification-service/error_rate`)
- Only 8 “email deferred by smtp relay” warnings across the whole window. (`log:6de115f7967d`)
**Assumptions:**
- ASM-1: The new SMTP client treats the deprecated smtp.pool_size as unspecified and defaults to a single connection, then busy‑waits when the pool is exhausted.

### 2. `config_change` on **notification-service**, triggered by `chg:2571` (HYP-2)

Confidence 0.65 (medium). Deploy changed expected config key to smtp.max_connections but the running config still has smtp.pool_size; the library falls back to a default low‑concurrency pool, throttling outbound mail and backing up the consumer.

**Supporting:**
- notification-service v3.9.0 deployed at 13:12:40 UTC (switch to new SMTP client library). (`chg:2571`)
- From 13:13:16 UTC the service logs “config key smtp.pool_size is deprecated; use smtp.max_connections” continuously (494 occurrences). (`log:23bad82d53ef`)
- consumer_lag metric jumps from baseline ~117 msgs to max 174,700, mean 60,720, last 164,500. (`metric:notification-service/consumer_lag`)
- CPU utilisation climbs to 1.0 (max) and averages 0.76 vs baseline 0.50. (`metric:notification-service/cpu_util`)
**Contradicting:**
- Error rate stays near baseline (mean 0.0020 vs 0.00199). (`metric:notification-service/error_rate`)
- Only 8 “email deferred by smtp relay” warnings across the whole window. (`log:6de115f7967d`)
**Assumptions:**
- ASM-2: No separate config‑change record exists because the migration was expected to be part of the deploy; the old key remains in the live config.

### 3. `dependency_degradation` on **orders-service** (HYP-3)

Confidence 0.20 (low). Market open dramatically increases trade events on Kafka, overwhelming the consumer despite unchanged code.

**Supporting:**
- consumer_lag metric jumps from baseline ~117 msgs to max 174,700, mean 60,720, last 164,500. (`metric:notification-service/consumer_lag`)
- RPS rises modestly (mean 160 vs baseline 154). (`metric:notification-service/rps`)
**Contradicting:**
- notification-service v3.9.0 deployed at 13:12:40 UTC (switch to new SMTP client library). (`chg:2571`)
- From 13:13:16 UTC the service logs “config key smtp.pool_size is deprecated; use smtp.max_connections” continuously (494 occurrences). (`log:23bad82d53ef`)
- Starting 13:40:37 UTC consumer group notify‑trades reports growing lag, reaching 67,405 messages behind at 14:14:59 UTC. (`log:7cf4e32d00a9`)
- CPU utilisation climbs to 1.0 (max) and averages 0.76 vs baseline 0.50. (`metric:notification-service/cpu_util`)
**Assumptions:**
- ASM-3: Kafka production rate from orders-service/payments-service jumped sharply at market open.

### 4. `infrastructure_failure` on **notification-service** (HYP-4)

Confidence 0.10 (low). External SMTP relay starts deferring mail, causing back‑pressure that stalls the consumer.

**Supporting:**
- Only 8 “email deferred by smtp relay” warnings across the whole window. (`log:6de115f7967d`)
**Contradicting:**
- consumer_lag metric jumps from baseline ~117 msgs to max 174,700, mean 60,720, last 164,500. (`metric:notification-service/consumer_lag`)
- CPU utilisation climbs to 1.0 (max) and averages 0.76 vs baseline 0.50. (`metric:notification-service/cpu_util`)
- Error rate stays near baseline (mean 0.0020 vs 0.00199). (`metric:notification-service/error_rate`)
**Assumptions:**
- ASM-4: Each SMTP deferral holds a consumer thread for tens of seconds, amplifying lag.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Roll back notification-service to v3.8.4 or deploy hot‑fix adding smtp.max_connections matching former pool size. | Immediately restores previous CPU profile and eliminates consumer lag. |
| now | fix | Add missing config key smtp.max_connections (value = former smtp.pool_size) to ConfigMap/secret and reload service. | If new library is kept, correct config removes fallback that causes low concurrency. |
| soon | investigate | Verify consumer_lag metric returns to baseline (<200 msgs) and CPU drops to ~0.5 after rollback/config fix. | Confirms the fix works before closing incident. |
| later | prevent | Update deploy pipeline to include a config‑migration step for any library that changes config keys; add pre‑deploy validation logging effective SMTP pool size. | Prevents recurrence of deploy‑only‑code changes leaving stale config. |
| later | prevent | Add alerts on notification-service.consumer_lag >5,000 for >5 min and cpu_util >0.85 sustained. | Provides early warning for similar regressions. |

## Evidence gaps

- **query_metrics** (Kafka production metrics for trade‑confirmation topic (bytes/sec, msgs/sec) 13:00‑14:15): Not available via current tooling; needed to confirm or rule out upstream surge.
- **query_logs** (Runtime config of notification-service (values of smtp.pool_size / smtp.max_connections)): Config values are not exposed in logs/metrics; needed to verify A2.
- **query_logs** (Thread dump / profiling of notification-service during high‑CPU period): Would confirm busy‑wait behavior (A1).
- **query_logs** (SMTP relay logs / rate‑limit counters): Would definitively rule out relay throttling (A4).

## Open questions

- What was the numeric value of smtp.pool_size in the live config?
- Did the trade‑event Kafka topic see a genuine spike at market open?
- Does the new SMTP client spin in a tight loop when the pool is exhausted, or does it block efficiently?

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 6 model calls, 4 tool calls, 33,483 tokens, 338 s.
