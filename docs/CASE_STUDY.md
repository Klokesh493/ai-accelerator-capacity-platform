# Engineering case study

## Engineering problem

An inference fleet can have free accelerators while still lacking the memory, latency headroom, or budget needed by a workload.

## Design choices

Whole-device allocation makes ownership explicit and avoids assuming that model memory can be safely shared. The allocator sorts workloads by memory and nodes by hourly cost. This is a greedy feasibility planner, so a hold can require an operator to try a different placement rather than prove the fleet has no feasible arrangement.

## Implementation

I built a benchmark-aware allocator that reserves whole GPU slots, checks benchmark freshness and p95 latency, and keeps throughput at 80% of the supplied benchmark. Requests pass through an auditable approval and export workflow.

The API and CLI share ops_platform.service.evaluate. Domain contracts and decisions live in ops_platform/domain.py. SQLite persistence is implemented in ops_platform/storage.py. Prometheus metrics are created per API instance. The deployment directory contains the supplied observability and Kubernetes configuration.

## Technical challenges

A stale benchmark, unhealthy node, latency violation, insufficient memory, or budget cap can leave a workload unmet. Any unmet workload holds the entire export.

Retry handling also matters across all workflows. A duplicate client request reuses its report, while stale approvals fail with HTTP 409. An unavailable model records an incomplete report that cannot be approved. HEC failures leave audit events pending.

## Validation results

5 labeled domain scenarios passed. The actual local Qwen run returned capacity_ready for ready.json and capacity_hold for hold.json. Captured reports include the model name, probe trace, content digests, and cited evidence. API and domain tests cover the decision policy and workflow failure cases. [Validation details](VALIDATION.md)

## Lessons learned

Free GPU count alone is a poor capacity signal. A usable reservation must account for model-specific throughput, memory, latency, redundancy, and budget together.

## Remaining scope

Fleet inventories and L4/A100 benchmark values are synthetic. GPU placement and inference performance were not measured on NVIDIA hardware. Model-agent inference was exercised separately using local Qwen on the development machine.
