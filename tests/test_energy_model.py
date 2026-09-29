import json
import pytest
from app.models.request import ScenarioRequest, BatteryInput, HourInput
from app.models.response import HourlyPlanEntry, BatteryAction, DirectiveInterpretation
from app.models.directives import DirectiveType
from app.energy.battery import BatterySimulator, TOLERANCE
from app.energy.simulation import simulate_hourly_energy
from app.energy.replay import replay_and_validate_plan


@pytest.fixture
def sample_battery():
    return BatteryInput(
        capacity_kwh=300.0,
        initial_energy_kwh=120.0,
        minimum_energy_kwh=30.0,
        max_charge_kwh_per_hour=60.0,
        max_discharge_kwh_per_hour=60.0,
    )


@pytest.fixture
def base_24h_request(sample_battery):
    hours = [
        HourInput(
            hour=h,
            demand_kwh=100.0,
            solar_kwh=50.0 if 8 <= h <= 16 else 0.0,
            tariff_bdt_per_kwh=10.0 if 17 <= h <= 21 else 5.0,
        )
        for h in range(24)
    ]
    return ScenarioRequest(
        scenario_id="TEST-SIM-01",
        operator_notes=["Standard operational note."],
        hours=hours,
        battery=sample_battery,
    )


# 1. No battery activity (idle)
def test_battery_idle(sample_battery):
    res = BatterySimulator.step(
        energy_before_kwh=120.0,
        action=BatteryAction.IDLE,
        battery_kwh=0.0,
        battery_params=sample_battery,
    )
    assert res.is_valid is True
    assert res.energy_after_kwh == 120.0
    assert res.battery_kwh == 0.0


# 2. Charging from solar
def test_battery_charge_step(sample_battery):
    res = BatterySimulator.step(
        energy_before_kwh=120.0,
        action=BatteryAction.CHARGE,
        battery_kwh=50.0,
        battery_params=sample_battery,
    )
    assert res.is_valid is True
    assert res.energy_after_kwh == 170.0


# 3. Charging from grid if permitted
def test_battery_charge_from_grid(sample_battery):
    res = BatterySimulator.step(
        energy_before_kwh=120.0,
        action=BatteryAction.CHARGE,
        battery_kwh=60.0,
        battery_params=sample_battery,
        no_charge=False,
    )
    assert res.is_valid is True
    assert res.energy_after_kwh == 180.0


# 4. Battery discharge
def test_battery_discharge_step(sample_battery):
    res = BatterySimulator.step(
        energy_before_kwh=120.0,
        action=BatteryAction.DISCHARGE,
        battery_kwh=40.0,
        battery_params=sample_battery,
    )
    assert res.is_valid is True
    assert res.energy_after_kwh == 80.0


# 5 & 6. Charge & Discharge Efficiency (Official 100% ideal energy conservation equation)
def test_charge_discharge_efficiency_conservation(sample_battery):
    # Charging exactly adds battery_kwh
    res_chg = BatterySimulator.step(100.0, BatteryAction.CHARGE, 45.5, sample_battery)
    assert res_chg.is_valid is True
    assert res_chg.energy_after_kwh == 145.5

    # Discharging exactly subtracts battery_kwh
    res_dis = BatterySimulator.step(145.5, BatteryAction.DISCHARGE, 45.5, sample_battery)
    assert res_dis.is_valid is True
    assert res_dis.energy_after_kwh == 100.0


# 7. Minimum reserve (base and directive)
def test_minimum_reserve_enforcement(sample_battery):
    # Discharging below base min reserve (30 kWh) must fail
    res_fail = BatterySimulator.step(50.0, BatteryAction.DISCHARGE, 30.0, sample_battery)
    assert res_fail.is_valid is False
    assert "below active reserve" in res_fail.violation

    # Discharging below elevated directive reserve (80 kWh) must fail
    res_dir_fail = BatterySimulator.step(100.0, BatteryAction.DISCHARGE, 30.0, sample_battery, active_min_reserve_kwh=80.0)
    assert res_dir_fail.is_valid is False
    assert "below active reserve" in res_dir_fail.violation


# 8. Maximum capacity
def test_maximum_capacity_enforcement(sample_battery):
    # Charging above capacity (300 kWh) must fail
    res_fail = BatterySimulator.step(280.0, BatteryAction.CHARGE, 50.0, sample_battery)
    assert res_fail.is_valid is False
    assert "exceeds capacity" in res_fail.violation


# 9. Maximum charge rate
def test_max_charge_rate_enforcement(sample_battery):
    # Charging above max rate (60 kWh/h) must fail
    res_fail = BatterySimulator.step(100.0, BatteryAction.CHARGE, 65.0, sample_battery)
    assert res_fail.is_valid is False
    assert "exceeds max charge rate" in res_fail.violation


# 10. Maximum discharge rate
def test_max_discharge_rate_enforcement(sample_battery):
    # Discharging above max rate (60 kWh/h) must fail
    res_fail = BatterySimulator.step(200.0, BatteryAction.DISCHARGE, 65.0, sample_battery)
    assert res_fail.is_valid is False
    assert "exceeds max discharge rate" in res_fail.violation


# 11. Insufficient battery energy
def test_insufficient_battery_energy(sample_battery):
    res_fail = BatterySimulator.step(40.0, BatteryAction.DISCHARGE, 50.0, sample_battery)
    assert res_fail.is_valid is False


# 12. Excess solar curtailment
def test_solar_curtailment_handling(base_24h_request):
    # Plan where available solar is 50, but only 30 is used
    plan = [
        HourlyPlanEntry(
            hour=h,
            grid_kwh=70.0 if 8 <= h <= 16 else 100.0,
            solar_used_kwh=30.0 if 8 <= h <= 16 else 0.0,
            battery_action=BatteryAction.IDLE,
            battery_kwh=0.0,
            battery_energy_after_kwh=120.0,
        )
        for h in range(24)
    ]
    sim = simulate_hourly_energy(base_24h_request, plan)
    assert sim.is_valid is True
    # Verify curtailment is recorded for solar hours
    assert sim.steps[10].solar_curtailed_kwh == 20.0
    assert sim.steps[10].energy_balance_error <= TOLERANCE


# 13. Zero solar
def test_zero_solar_hours(base_24h_request):
    plan = [
        HourlyPlanEntry(
            hour=h,
            grid_kwh=100.0,
            solar_used_kwh=0.0,
            battery_action=BatteryAction.IDLE,
            battery_kwh=0.0,
            battery_energy_after_kwh=120.0,
        )
        for h in range(24)
    ]
    sim = simulate_hourly_energy(base_24h_request, plan)
    assert sim.is_valid is True
    assert sim.steps[0].solar_used_kwh == 0.0


# 14. Zero demand
def test_zero_demand_simulation(sample_battery):
    zero_demand_req = ScenarioRequest(
        scenario_id="ZERO-DEMAND",
        operator_notes=["Zero demand overnight."],
        hours=[HourInput(hour=h, demand_kwh=0.0, solar_kwh=0.0, tariff_bdt_per_kwh=5.0) for h in range(24)],
        battery=sample_battery,
    )
    plan = [
        HourlyPlanEntry(
            hour=h,
            grid_kwh=0.0,
            solar_used_kwh=0.0,
            battery_action=BatteryAction.IDLE,
            battery_kwh=0.0,
            battery_energy_after_kwh=120.0,
        )
        for h in range(24)
    ]
    sim = simulate_hourly_energy(zero_demand_req, plan)
    assert sim.is_valid is True
    assert sim.total_cost_bdt == 0.0


# 15. Consecutive charging and discharging
def test_consecutive_charge_discharge(sample_battery):
    e = 100.0
    # Hour 1: charge 30 -> 130
    s1 = BatterySimulator.step(e, BatteryAction.CHARGE, 30.0, sample_battery)
    assert s1.is_valid and s1.energy_after_kwh == 130.0
    # Hour 2: charge 40 -> 170
    s2 = BatterySimulator.step(s1.energy_after_kwh, BatteryAction.CHARGE, 40.0, sample_battery)
    assert s2.is_valid and s2.energy_after_kwh == 170.0
    # Hour 3: discharge 50 -> 120
    s3 = BatterySimulator.step(s2.energy_after_kwh, BatteryAction.DISCHARGE, 50.0, sample_battery)
    assert s3.is_valid and s3.energy_after_kwh == 120.0


# 16 & 17. 24-hour simulation & final battery condition (neutrality)
def test_24h_simulation_and_neutrality_violation(base_24h_request):
    # Plan where final battery energy is not restored (neutrality violated)
    plan = [
        HourlyPlanEntry(
            hour=h,
            grid_kwh=60.0 if h == 1 else 100.0,
            solar_used_kwh=0.0,
            battery_action=BatteryAction.DISCHARGE if h == 1 else BatteryAction.IDLE,
            battery_kwh=40.0 if h == 1 else 0.0,
            battery_energy_after_kwh=80.0 if h >= 1 else 120.0,
        )
        for h in range(24)
    ]
    sim = simulate_hourly_energy(base_24h_request, plan)
    assert sim.is_valid is False
    assert any("neutrality" in v for v in sim.violations)


# 18. Floating-point tolerance edge cases (within 0.01 tolerance is accepted)
def test_floating_point_tolerance(sample_battery):
    # 0.005 difference from idle
    res_tiny = BatterySimulator.step(120.0, BatteryAction.IDLE, 0.000001, sample_battery)
    assert res_tiny.is_valid is True


# 19. Invalid physically impossible states
def test_impossible_energy_balance_fails(base_24h_request):
    plan = [
        HourlyPlanEntry(
            hour=h,
            grid_kwh=50.0,  # Missing 50 kWh of demand!
            solar_used_kwh=0.0,
            battery_action=BatteryAction.IDLE,
            battery_kwh=0.0,
            battery_energy_after_kwh=120.0,
        )
        for h in range(24)
    ]
    sim = simulate_hourly_energy(base_24h_request, plan)
    assert sim.is_valid is False
    assert any("Energy balance error" in v for v in sim.violations)


# Task 8: Test replay validator against all 10 public reference cases
def test_all_10_public_sample_cases_replay():
    data = json.load(open("docs/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json", encoding="utf-8"))
    for case in data["cases"]:
        cid = case["id"]
        req = ScenarioRequest(**case["input"])
        exp = case["expected_output"]
        plan = [HourlyPlanEntry(**p) for p in exp["hourly_plan"]]
        directives = [DirectiveInterpretation(**d) for d in exp["directive_interpretation"]]

        sim = simulate_hourly_energy(req, plan, directives)
        assert sim.is_valid is True, f"Case {cid} failed replay simulation: {sim.violations}"
        assert abs(sim.total_cost_bdt - exp["total_cost_bdt"]) <= TOLERANCE, f"Cost mismatch on {cid}"
        assert abs(sim.total_grid_kwh - exp["total_grid_kwh"]) <= TOLERANCE, f"Grid kWh mismatch on {cid}"
        assert abs(sim.peak_grid_kwh - exp["peak_grid_kwh"]) <= TOLERANCE, f"Peak grid mismatch on {cid}"
