import json
from pathlib import Path

import pytest

from ops_platform.service import evaluate

def fixture(name):
    return json.loads((Path("examples") / (name + ".json")).read_text())


def test_whole_device_reservations_and_cost():
    report = evaluate(fixture("ready"))
    assert len(report["allocations"]) == 2
    assert report["hourly_cents"] == 200
    assert sum(row["reserved_tps"] for row in report["allocations"]) == 1600

def test_unhealthy_fleet_holds():
    source = fixture("ready")
    for node in source["nodes"]:
        node["healthy"] = False
    assert evaluate(source)["decision"] == "capacity_hold"

def test_duplicate_node_and_future_benchmark_rejected():
    source = fixture("ready")
    source["nodes"].append(source["nodes"][0])
    with pytest.raises(ValueError):
        evaluate(source)
    source = fixture("ready")
    source["benchmarks"][0]["measured_at"] = source["now"] + 1
    with pytest.raises(ValueError):
        evaluate(source)

def test_minimum_replica_redundancy():
    source = fixture("ready")
    source["workloads"][0]["required_tokens_per_second"] = 1
    assert len(evaluate(source)["allocations"]) == 2
