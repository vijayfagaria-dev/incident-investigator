# T09: Notification pods restarting

**Outcome:** conclusive. Root cause: `code_regression` on **notification-service**, triggered by `chg:2591`

## Summary

At 07:12 UTC a deploy of notification-service v3.9.2 added a per‑locale template cache. Within ~20 minutes GC overhead warnings appeared, memory utilisation climbed from 73% to 97% of the 1 GiB limit, and the first OOMKilled occurred at 07:52 UTC. Restarts caused consumer lag to surge to >40k messages and error‑rate to rise. Kafka and upstream services showed no degradation. The sole production change in the window points to a memory leak in the new cache.

## Hypotheses

### 1. `code_regression` on **notification-service**, triggered by `chg:2591` (HYP-1)

Confidence 0.86 (high). The v3.9.2 deploy added a per‑locale template cache without eviction. Each distinct locale creates cached objects that are never released, causing steady heap growth, high GC overhead, eventual OOMKills, pod restarts, and resulting consumer lag and error‑rate spikes.

**Supporting:**
- GC overhead warnings ('GC overhead high: <pct>% of time in garbage collection') start at 07:35:06 UTC and continue through 08:29 UTC (181 occurrences). (`log:f681f54530df`)
- OOMKilled events for notification-service pods begin at 07:52:13 UTC and repeat 27 times until 08:29 UTC. (`log:c39fab989944`)
- Memory utilisation rises from 0.736 at 07:30 UTC to 0.970 at 08:30 UTC (baseline 0.576). (`metric:notification-service/mem_util`)
- Consumer lag jumps from ~69 messages at 07:30 UTC to ~41,370 messages at 08:30 UTC (baseline ~125). (`metric:notification-service/consumer_lag`)
- Error rate increases from 0.002 at 07:30 UTC to 0.032 at 08:30 UTC (baseline 0.002). (`metric:notification-service/error_rate`)
- Deploy of notification-service v3.9.2 at 07:12:30 UTC (commit 0f6c3a8) adding per‑locale template cache (+88/-21 lines). (`chg:2591`)
- Dependency graph: notification-service has a hard dependency on Kafka; no upstream services call notification-service directly. (`dep:notification-service->kafka`)
**Contradicting:**
- Request rate rises modestly from 107 rps to 123 rps (baseline 106 rps). (`metric:notification-service/rps`)
- Kafka metrics show stable CPU, inbound rate only +7% vs baseline, and zero under‑replicated partitions throughout the window. (`metric:kafka/broker_cpu_util`, `metric:kafka/messages_in_per_s`, `metric:kafka/under_replicated_partitions`)
**Assumptions:**
- ASM-1: The new per‑locale template cache introduced in v3.9.2 has no eviction or size bound, causing unbounded object retention.

### 2. `capacity_saturation` on **notification-service** (HYP-2)

Confidence 0.12 (low). An unexpected surge in notification traffic overwhelms the service's memory capacity, leading to GC pressure and OOMKills.

**Supporting:**
- Consumer lag jumps from ~69 messages at 07:30 UTC to ~41,370 messages at 08:30 UTC (baseline ~125). (`metric:notification-service/consumer_lag`)
- Error rate increases from 0.002 at 07:30 UTC to 0.032 at 08:30 UTC (baseline 0.002). (`metric:notification-service/error_rate`)
- Request rate rises modestly from 107 rps to 123 rps (baseline 106 rps). (`metric:notification-service/rps`)
**Contradicting:**
- GC overhead warnings ('GC overhead high: <pct>% of time in garbage collection') start at 07:35:06 UTC and continue through 08:29 UTC (181 occurrences). (`log:f681f54530df`)
- Memory utilisation rises from 0.736 at 07:30 UTC to 0.970 at 08:30 UTC (baseline 0.576). (`metric:notification-service/mem_util`)
- Deploy of notification-service v3.9.2 at 07:12:30 UTC (commit 0f6c3a8) adding per‑locale template cache (+88/-21 lines). (`chg:2591`)
- Kafka metrics show stable CPU, inbound rate only +7% vs baseline, and zero under‑replicated partitions throughout the window. (`metric:kafka/broker_cpu_util`, `metric:kafka/messages_in_per_s`, `metric:kafka/under_replicated_partitions`)
- Dependency graph: notification-service has a hard dependency on Kafka; no upstream services call notification-service directly. (`dep:notification-service->kafka`)
**Assumptions:**
- ASM-2: A hidden burst of notification events not reflected in the rps metric could drive memory growth.

### 3. `dependency_degradation` on **kafka** (HYP-3)

Confidence 0.01 (low). Kafka broker degradation causes back‑pressure, making the consumer lag grow and the service retain more messages in memory.

**Supporting:**
- Consumer lag jumps from ~69 messages at 07:30 UTC to ~41,370 messages at 08:30 UTC (baseline ~125). (`metric:notification-service/consumer_lag`)
**Contradicting:**
- Kafka metrics show stable CPU, inbound rate only +7% vs baseline, and zero under‑replicated partitions throughout the window. (`metric:kafka/broker_cpu_util`, `metric:kafka/messages_in_per_s`, `metric:kafka/under_replicated_partitions`)
- Dependency graph: notification-service has a hard dependency on Kafka; no upstream services call notification-service directly. (`dep:notification-service->kafka`)
**Assumptions:**
- ASM-3: Kafka may have an undetected broker‑side issue not captured by exported metrics.

### 4. `config_change` on **notification-service** (HYP-4)

Confidence 0.01 (low). A runtime configuration or feature‑flag change increased cache size or disabled eviction, causing memory leak.

**Contradicting:**
- Deploy of notification-service v3.9.2 at 07:12:30 UTC (commit 0f6c3a8) adding per‑locale template cache (+88/-21 lines). (`chg:2591`)
**Assumptions:**
- ASM-4: An undocumented runtime config or feature‑flag change affecting cache behaviour occurred around 07:30 UTC.

## Recommended actions

| Urgency | Kind | Action | Why |
|---|---|---|---|
| now | mitigate | Rollback notification-service to v3.9.1 (or disable the new cache via feature flag). | Immediately stops the memory leak introduced by the v3.9.2 deploy (H1). |
| now | mitigate | Temporarily raise pod memory limit to 1.5 GiB and enable HPA to drain consumer lag. | Provides headroom while rollback proceeds and prevents further OOMKills. |
| soon | investigate | Capture a heap dump from a pod before OOM (e.g., -XX:+HeapDumpOnOutOfMemoryError) and analyse retained objects. | Confirms the cache leak and identifies exact object types (addresses Gap G1). |
| soon | fix | Add eviction policy / size bound (LRU, TTL) to the per‑locale template cache and deploy patched version after review. | Eliminates the unbounded growth root cause (H1). |
| later | prevent | Add metric for cache entry count per pod and alert when it exceeds a threshold. | Early detection of similar regressions (addresses Gap G4). |
| later | prevent | Document the incident, add canary deploy with memory‑growth alert, and update release checklist to require cache‑size limits. | Process improvement to avoid repeat of code‑regression memory leaks. |

## Evidence gaps

- **query_logs** (heap dump / detailed GC logs from a crashing notification-service pod): Toolset does not provide heap dumps; needed to confirm leaking object types.
- **query_logs** (source code or diff details of the cache implementation): Diff summary only shows line counts; cannot verify eviction policy.
- **query_metrics** (per‑pod memory utilisation time series): Only aggregate metric available; cannot tell if leak is isolated to subset of pods.
- **get_change_history** (feature‑flag or config change audit around 07:30 UTC): Change history shows no such changes, but tool may not capture all flag systems.

## Open questions

- What exact objects are retained in the locale cache? (requires heap dump).
- Was the cache intended to be bounded? (code review / design doc).
- Did any feature‑flag toggle the cache on/off around 07:30 UTC? (audit logs).

## How the investigation ran

Stopped because the agent finished its investigation, after 1 round(s): 8 model calls, 6 tool calls, 44,945 tokens, 389 s.
