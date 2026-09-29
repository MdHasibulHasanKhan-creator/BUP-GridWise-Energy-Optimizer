import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import time
import json
import statistics
from fastapi.testclient import TestClient
from app.main import app
from app.models.request import ScenarioRequest
from app.optimizer.solver import EnergyOptimizer
from app.guardrails.validator import DirectiveGuardrail

client = TestClient(app)


def run_benchmark():
    print("=" * 65)
    print("  GRIDWISE OPTIMIZER BENCHMARK & PERFORMANCE PROFILE")
    print("=" * 65)

    data = json.load(open("docs/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json", encoding="utf-8"))
    cases = data["cases"]
    n_runs = 50

    solver_latencies = []
    e2e_latencies = []
    failures = 0

    # 1. Measure Core Linear Programming Solver Speed (HiGHS)
    for case in cases:
        req = ScenarioRequest(**case["input"])
        exp = case["expected_output"]
        directives = DirectiveGuardrail.validate_and_guardrail_interpretations(
            num_notes=len(req.operator_notes),
            raw_interpretations=exp["directive_interpretation"],
            battery_capacity_kwh=req.battery.capacity_kwh,
        )

        for _ in range(n_runs):
            t0 = time.perf_counter()
            plan = EnergyOptimizer.solve(req, directives)
            t1 = time.perf_counter()
            solver_latencies.append((t1 - t0) * 1000.0)

    # 2. Measure End-to-End API Pipeline Latency
    for case in cases:
        req_dict = case["input"]
        for _ in range(n_runs):
            t0 = time.perf_counter()
            resp = client.post("/optimize-energy", json=req_dict)
            t1 = time.perf_counter()
            if resp.status_code != 200:
                failures += 1
            e2e_latencies.append((t1 - t0) * 1000.0)

    solver_p50 = statistics.median(solver_latencies)
    solver_p95 = statistics.quantiles(solver_latencies, n=20)[18] if len(solver_latencies) >= 20 else max(solver_latencies)
    solver_max = max(solver_latencies)
    solver_min = min(solver_latencies)

    e2e_p50 = statistics.median(e2e_latencies)
    e2e_p95 = statistics.quantiles(e2e_latencies, n=20)[18] if len(e2e_latencies) >= 20 else max(e2e_latencies)
    e2e_max = max(e2e_latencies)
    e2e_min = min(e2e_latencies)

    print(f"Total Scenarios Tested: {len(cases)} cases x {n_runs} runs = {len(cases) * n_runs} runs per benchmark")
    print(f"Failures / Infeasibilities: {failures}")
    print("-" * 65)
    print("Linear Programming Solver (SciPy HiGHS) Latency:")
    print(f"  Min: {solver_min:.3f} ms | Median (p50): {solver_p50:.3f} ms | p95: {solver_p95:.3f} ms | Max: {solver_max:.3f} ms")
    print("-" * 65)
    print("End-to-End API (Request -> Interpretation -> Guardrails -> LP -> Replay -> Response) Latency:")
    print(f"  Min: {e2e_min:.3f} ms | Median (p50): {e2e_p50:.3f} ms | p95: {e2e_p95:.3f} ms | Max: {e2e_max:.3f} ms")
    print("-" * 65)
    print("Official Performance Requirement: p95 <= 5000 ms (5.0s)")
    print(f"Current System p95: {e2e_p95:.3f} ms ({(e2e_p95 / 5000.0) * 100:.2f}% of allowed budget)")
    print("=" * 65)


if __name__ == "__main__":
    run_benchmark()
