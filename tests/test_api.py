import json
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.directives import DirectiveType
from app.guardrails.validator import DirectiveGuardrail

client = TestClient(app)

SAMPLE_PAYLOAD = {
    "scenario_id": "TEST-01",
    "operator_notes": [
        "Facilities will wash the rooftop solar panels from noon until 2 PM. During cleaning, usable solar should be treated as roughly 25% of the forecast.",
        "The sports office moved next month's registration deadline."
    ],
    "hours": [
        {"hour": 0, "demand_kwh": 90, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
        {"hour": 1, "demand_kwh": 85, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
        {"hour": 2, "demand_kwh": 80, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
        {"hour": 3, "demand_kwh": 80, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
        {"hour": 4, "demand_kwh": 85, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
        {"hour": 5, "demand_kwh": 95, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
        {"hour": 6, "demand_kwh": 110, "solar_kwh": 5, "tariff_bdt_per_kwh": 8},
        {"hour": 7, "demand_kwh": 130, "solar_kwh": 20, "tariff_bdt_per_kwh": 10},
        {"hour": 8, "demand_kwh": 150, "solar_kwh": 50, "tariff_bdt_per_kwh": 12},
        {"hour": 9, "demand_kwh": 165, "solar_kwh": 90, "tariff_bdt_per_kwh": 14},
        {"hour": 10, "demand_kwh": 175, "solar_kwh": 130, "tariff_bdt_per_kwh": 16},
        {"hour": 11, "demand_kwh": 180, "solar_kwh": 160, "tariff_bdt_per_kwh": 16},
        {"hour": 12, "demand_kwh": 185, "solar_kwh": 180, "tariff_bdt_per_kwh": 15},
        {"hour": 13, "demand_kwh": 180, "solar_kwh": 170, "tariff_bdt_per_kwh": 14},
        {"hour": 14, "demand_kwh": 175, "solar_kwh": 140, "tariff_bdt_per_kwh": 14},
        {"hour": 15, "demand_kwh": 160, "solar_kwh": 100, "tariff_bdt_per_kwh": 15},
        {"hour": 16, "demand_kwh": 150, "solar_kwh": 60, "tariff_bdt_per_kwh": 17},
        {"hour": 17, "demand_kwh": 155, "solar_kwh": 25, "tariff_bdt_per_kwh": 19},
        {"hour": 18, "demand_kwh": 170, "solar_kwh": 5, "tariff_bdt_per_kwh": 20},
        {"hour": 19, "demand_kwh": 180, "solar_kwh": 0, "tariff_bdt_per_kwh": 20},
        {"hour": 20, "demand_kwh": 175, "solar_kwh": 0, "tariff_bdt_per_kwh": 18},
        {"hour": 21, "demand_kwh": 160, "solar_kwh": 0, "tariff_bdt_per_kwh": 14},
        {"hour": 22, "demand_kwh": 130, "solar_kwh": 0, "tariff_bdt_per_kwh": 10},
        {"hour": 23, "demand_kwh": 105, "solar_kwh": 0, "tariff_bdt_per_kwh": 7}
    ],
    "battery": {
        "capacity_kwh": 300,
        "initial_energy_kwh": 120,
        "minimum_energy_kwh": 30,
        "max_charge_kwh_per_hour": 60,
        "max_discharge_kwh_per_hour": 60
    }
}


def test_health_endpoint():
    """Verify GET /health returns 200 and status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_optimize_energy_valid():
    """Verify POST /optimize-energy returns 200 and valid schema."""
    response = client.post("/optimize-energy", json=SAMPLE_PAYLOAD)
    assert response.status_code == 200
    data = response.json()
    assert data["scenario_id"] == "TEST-01"
    assert len(data["directive_interpretation"]) == 2
    assert len(data["hourly_plan"]) == 24
    assert data["total_grid_kwh"] > 0
    assert data["total_cost_bdt"] > 0
    assert data["peak_grid_kwh"] > 0
    assert isinstance(data["plan_summary"], str)


def test_optimize_energy_malformed_json():
    """Verify malformed payload returns HTTP 400."""
    response = client.post(
        "/optimize-energy",
        content="not a json string",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400


def test_optimize_energy_missing_scenario_id():
    """Verify missing required field returns HTTP 400."""
    bad_payload = dict(SAMPLE_PAYLOAD)
    del bad_payload["scenario_id"]
    response = client.post("/optimize-energy", json=bad_payload)
    assert response.status_code == 400


def test_optimize_energy_invalid_hours_length():
    """Verify hours array not equal to 24 returns HTTP 400."""
    bad_payload = dict(SAMPLE_PAYLOAD)
    bad_payload["hours"] = SAMPLE_PAYLOAD["hours"][:23]  # only 23 hours
    response = client.post("/optimize-energy", json=bad_payload)
    assert response.status_code == 400


def test_optimize_energy_invalid_battery_bounds():
    """Verify initial energy > capacity returns HTTP 400."""
    bad_payload = dict(SAMPLE_PAYLOAD)
    bad_payload["battery"] = {
        "capacity_kwh": 100,
        "initial_energy_kwh": 150,  # exceeds capacity
        "minimum_energy_kwh": 20,
        "max_charge_kwh_per_hour": 50,
        "max_discharge_kwh_per_hour": 50
    }
    response = client.post("/optimize-energy", json=bad_payload)
    assert response.status_code == 400


def test_guardrails_hours_sanitization():
    """Verify guardrail sorts and deduplicates hours."""
    assert DirectiveGuardrail.sanitize_hours([14, 12, 13, 12]) == [12, 13, 14]
    assert DirectiveGuardrail.sanitize_hours([-1, 0, 23, 24, "invalid"]) == [0, 23]


def test_guardrails_no_op_enforcement():
    """Verify guardrail forces applies=false and adjustment=null for no_op."""
    res = DirectiveGuardrail.sanitize_directive(
        note_index=0,
        raw_directive={"directive_type": "no_op", "structured_adjustment": {"dummy": 123}},
    )
    assert res.applies is False
    assert res.directive_type == DirectiveType.NO_OP
    assert res.structured_adjustment is None
