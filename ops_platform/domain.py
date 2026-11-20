"""Benchmark-aware placement of inference replicas on synthetic accelerator fleets."""
import json
from typing import List

from pydantic import Field, model_validator

from .agent_loop import Probe
from .contracts import Count, Identifier, Positive, Record, unique

TITLE = "AI Accelerator Capacity Platform"
BRIEF = "Inspect fleet health, benchmark freshness, and inference demand to propose a capacity allocation."
SOURCES = ["fleet", "benchmarks", "demand"]


class Node(Record):
    id: Identifier
    gpu: Identifier
    slots: Positive = Field(le=128)
    free_slots: Count = Field(le=128)
    memory_gib: Positive
    hourly_cents: Count
    healthy: bool

    @model_validator(mode="after")
    def capacity(self):
        if self.free_slots > self.slots:
            raise ValueError("free slots exceed installed slots")
        return self


class Benchmark(Record):
    gpu: Identifier
    model: Identifier
    tokens_per_second: Positive
    p95_ms: Positive
    measured_at: Count


class Workload(Record):
    id: Identifier
    model: Identifier
    memory_gib: Positive
    required_tokens_per_second: Positive
    max_p95_ms: Positive
    min_replicas: Positive = Field(default=1, le=128)


class Case(Record):
    now: Count
    max_age_seconds: Positive = 3600
    max_hourly_cents: Positive
    nodes: List[Node] = Field(min_length=1, max_length=50)
    benchmarks: List[Benchmark] = Field(min_length=1, max_length=100)
    workloads: List[Workload] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def identities(self):
        unique([n.id for n in self.nodes], "node ids")
        unique([(b.gpu, b.model) for b in self.benchmarks], "benchmark pairs")
        unique([w.id for w in self.workloads], "workload ids")
        if any(b.measured_at > self.now for b in self.benchmarks):
            raise ValueError("benchmark timestamp is in the future")
        return self


def prepare(case):
    snapshot = {"fleet": [n.model_dump() for n in case.nodes],
                "benchmarks": {"samples": [b.model_dump() for b in case.benchmarks],
                               "now": case.now, "max_age_seconds": case.max_age_seconds},
                "demand": {"workloads": [w.model_dump() for w in case.workloads],
                           "max_hourly_cents": case.max_hourly_cents}}
    probes = [Probe(key, "Read " + key + " evidence", lambda key=key: snapshot[key])
              for key in SOURCES]

    def decide(evidence):
        available = {node.id: node.free_slots for node in case.nodes}
        benchmarks = {(b.gpu, b.model): b for b in case.benchmarks}
        allocations, unmet = [], []
        hourly = 0
        for workload in sorted(case.workloads, key=lambda w: (-w.memory_gib, w.id)):
            remaining = workload.required_tokens_per_second
            replicas = 0
            # Each replica reserves one whole accelerator. An 80% throughput cap
            # leaves headroom, while placement remains a transparent greedy plan.
            for node in sorted(case.nodes, key=lambda n: (n.hourly_cents, n.id)):
                bench = benchmarks.get((node.gpu, workload.model))
                if (not node.healthy or not bench or node.memory_gib < workload.memory_gib
                        or bench.p95_ms > workload.max_p95_ms
                        or case.now - bench.measured_at > case.max_age_seconds):
                    continue
                throughput = bench.tokens_per_second * 80 // 100
                if throughput == 0:
                    continue
                while available[node.id] and (remaining > 0 or replicas < workload.min_replicas):
                    if hourly + node.hourly_cents > case.max_hourly_cents:
                        break
                    allocations.append({"workload": workload.id, "node": node.id,
                                        "gpu": node.gpu, "reserved_tps": throughput})
                    available[node.id] -= 1
                    hourly += node.hourly_cents
                    remaining -= throughput
                    replicas += 1
            if remaining > 0 or replicas < workload.min_replicas:
                unmet.append(workload.id)
        return {"decision": "capacity_ready" if not unmet else "capacity_hold",
                "ready": not unmet, "citations": SOURCES, "allocations": allocations,
                "unmet": unmet, "hourly_cents": hourly,
                "reason": "All workloads fit the benchmark, memory, latency and cost policy."
                          if not unmet else "Some workload demand cannot be reserved safely."}

    return probes, decide


def bundle(report):
    return {"capacity-reservation.json": json.dumps(
        {"allocations": report["allocations"], "hourly_cents": report["hourly_cents"]}, indent=2)}
