import json
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_e2e_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_e2e_all_10_public_sample_cases():
    data = json.load(open("docs/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json", encoding="utf-8"))
    for case in data["cases"]:
        cid = case["id"]
        req_body = case["input"]
        exp_out = case["expected_output"]

        resp = client.post("/optimize-energy", json=req_body)
        assert resp.status_code == 200, f"Case {cid} returned {resp.status_code}: {resp.text}"
        res_data = resp.json()

        # Check top-level contract fields
        assert res_data["scenario_id"] == req_body["scenario_id"]
        assert len(res_data["directive_interpretation"]) == len(req_body["operator_notes"])
        assert len(res_data["hourly_plan"]) == 24
        assert isinstance(res_data["plan_summary"], str)

        # Check directive interpretations
        for ext_d, exp_d in zip(res_data["directive_interpretation"], exp_out["directive_interpretation"]):
            assert ext_d["note_index"] == exp_d["note_index"]
            assert ext_d["applies"] == exp_d["applies"]
            assert ext_d["directive_type"] == exp_d["directive_type"]
            if exp_d["structured_adjustment"]:
                assert ext_d["structured_adjustment"]["hours"] == exp_d["structured_adjustment"]["hours"]
            else:
                assert ext_d["structured_adjustment"] is None

        # Check optimality against reference cost within 0.01 tolerance
        cost_diff = abs(res_data["total_cost_bdt"] - exp_out["total_cost_bdt"])
        assert cost_diff <= 0.01, f"{cid} Cost mismatch: Got {res_data['total_cost_bdt']}, Expected {exp_out['total_cost_bdt']}"

        grid_diff = abs(res_data["total_grid_kwh"] - exp_out["total_grid_kwh"])
        assert grid_diff <= 0.01, f"{cid} Grid mismatch: Got {res_data['total_grid_kwh']}, Expected {exp_out['total_grid_kwh']}"


def test_e2e_infeasible_request_returns_422():
    # Construct an infeasible scenario
    infeasible_payload = {
        "scenario_id": "INFEASIBLE-01",
        "operator_notes": ["Grid intake capped at 0 kWh."],
        "hours": [{"hour": h, "demand_kwh": 500, "solar_kwh": 0, "tariff_bdt_per_kwh": 10} for h in range(24)],
        "battery": {
            "capacity_kwh": 50,
            "initial_energy_kwh": 10,
            "minimum_energy_kwh": 10,
            "max_charge_kwh_per_hour": 10,
            "max_discharge_kwh_per_hour": 10
        }
    }
    resp = client.post("/optimize-energy", json=infeasible_payload)
    assert resp.status_code == 422
    assert "Infeasible" in resp.json()["detail"]
