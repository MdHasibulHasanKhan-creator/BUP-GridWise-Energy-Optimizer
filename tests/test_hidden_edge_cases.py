import pytest
from app.models.request import ScenarioRequest, HourInput, BatteryInput
from app.models.response import HourlyPlanEntry, BatteryAction, DirectiveInterpretation
from app.models.directives import DirectiveType
from app.optimizer.solver import EnergyOptimizer, InfeasibleScheduleError
from app.energy.simulation import simulate_hourly_energy
from app.energy.battery import TOLERANCE


@pytest.fixture
def standard_battery():
    return BatteryInput(
        capacity_kwh=400.0,
        initial_energy_kwh=150.0,
        minimum_energy_kwh=50.0,
        max_charge_kwh_per_hour=80.0,
        max_discharge_kwh_per_hour=80.0,
    )


def make_request(
    battery: BatteryInput,
    demand_vals: list,
    solar_vals: list,
    tariff_vals: list,
    scenario_id: str = "EDGE-01",
) -> ScenarioRequest:
    hours = [
        HourInput(
            hour=h,
            demand_kwh=demand_vals[h],
            solar_kwh=solar_vals[h],
            tariff_bdt_per_kwh=tariff_vals[h],
        )
        for h in range(24)
    ]
    return ScenarioRequest(
        scenario_id=scenario_id,
        operator_notes=["Edge case scenario testing."],
        hours=hours,
        battery=battery,
    )


# 1. No-op only scenario
def test_edge_noop_only(standard_battery):
    req = make_request(
        battery=standard_battery,
        demand_vals=[100.0] * 24,
        solar_vals=[0.0] * 8 + [60.0] * 8 + [0.0] * 8,
        tariff_vals=[5.0] * 16 + [15.0] * 8,
    )
    directives = [DirectiveInterpretation(note_index=0, applies=False, directive_type=DirectiveType.NO_OP, structured_adjustment=None, explanation="noop")]
    plan = EnergyOptimizer.solve(req, directives)
    sim = simulate_hourly_energy(req, plan, directives)
    assert sim.is_valid is True
    assert sim.end_of_day_neutrality_delta <= TOLERANCE


# 2. Boundary hours: hour 0 single-hour window
def test_edge_boundary_hour_0(standard_battery):
    req = make_request(
        battery=standard_battery,
        demand_vals=[100.0] * 24,
        solar_vals=[0.0] * 24,
        tariff_vals=[10.0] * 24,
    )
    directives = [DirectiveInterpretation(note_index=0, applies=True, directive_type=DirectiveType.NO_CHARGE_WINDOW, structured_adjustment={"hours": [0]}, explanation="h0")]
    plan = EnergyOptimizer.solve(req, directives)
    sim = simulate_hourly_energy(req, plan, directives)
    assert sim.is_valid is True
    assert plan[0].battery_action != BatteryAction.CHARGE


# 3. Boundary hours: hour 23 single-hour window
def test_edge_boundary_hour_23(standard_battery):
    req = make_request(
        battery=standard_battery,
        demand_vals=[100.0] * 24,
        solar_vals=[0.0] * 24,
        tariff_vals=[10.0] * 24,
    )
    directives = [DirectiveInterpretation(note_index=0, applies=True, directive_type=DirectiveType.NO_DISCHARGE_WINDOW, structured_adjustment={"hours": [23]}, explanation="h23")]
    plan = EnergyOptimizer.solve(req, directives)
    sim = simulate_hourly_energy(req, plan, directives)
    assert sim.is_valid is True
    assert plan[23].battery_action != BatteryAction.DISCHARGE


# 4. Full-day 24-hour window for no_charge
def test_edge_full_day_no_charge(standard_battery):
    req = make_request(
        battery=standard_battery,
        demand_vals=[80.0] * 24,
        solar_vals=[0.0] * 24,
        tariff_vals=[8.0] * 24,
    )
    directives = [DirectiveInterpretation(note_index=0, applies=True, directive_type=DirectiveType.NO_CHARGE_WINDOW, structured_adjustment={"hours": list(range(24))}, explanation="full")]
    plan = EnergyOptimizer.solve(req, directives)
    sim = simulate_hourly_energy(req, plan, directives)
    assert sim.is_valid is True
    # If charging is blocked all 24h and neutrality requires E_23 == E_init, battery cannot discharge either!
    for entry in plan:
        assert entry.battery_action == BatteryAction.IDLE


# 5. Full-day 24-hour window for solar reduction with factor 0.0 (100% solar cut)
def test_edge_full_day_zero_solar_factor(standard_battery):
    req = make_request(
        battery=standard_battery,
        demand_vals=[100.0] * 24,
        solar_vals=[50.0] * 24,
        tariff_vals=[6.0] * 24,
    )
    directives = [DirectiveInterpretation(note_index=0, applies=True, directive_type=DirectiveType.SOLAR_REDUCTION, structured_adjustment={"hours": list(range(24)), "factor": 0.0}, explanation="blackout")]
    plan = EnergyOptimizer.solve(req, directives)
    sim = simulate_hourly_energy(req, plan, directives)
    assert sim.is_valid is True
    for entry in plan:
        assert entry.solar_used_kwh == 0.0


# 6. Overlapping multi-directives: solar reduction + minimum reserve + grid cap
def test_edge_multi_directive_coexistence(standard_battery):
    req = make_request(
        battery=standard_battery,
        demand_vals=[120.0] * 24,
        solar_vals=[0.0] * 6 + [80.0] * 12 + [0.0] * 6,
        tariff_vals=[5.0] * 16 + [18.0] * 8,
    )
    directives = [
        DirectiveInterpretation(note_index=0, applies=True, directive_type=DirectiveType.SOLAR_REDUCTION, structured_adjustment={"hours": [12, 13, 14], "factor": 0.3}, explanation="solar"),
        DirectiveInterpretation(note_index=1, applies=True, directive_type=DirectiveType.MINIMUM_BATTERY_RESERVE, structured_adjustment={"hours": [18, 19, 20], "minimum_energy_kwh": 100.0}, explanation="reserve"),
        DirectiveInterpretation(note_index=2, applies=True, directive_type=DirectiveType.MAX_GRID_WINDOW, structured_adjustment={"hours": [19, 20, 21], "max_grid_kwh": 160.0}, explanation="grid"),
    ]
    plan = EnergyOptimizer.solve(req, directives)
    sim = simulate_hourly_energy(req, plan, directives)
    assert sim.is_valid is True


# 7. Zero solar all day
def test_edge_zero_solar_all_day(standard_battery):
    req = make_request(
        battery=standard_battery,
        demand_vals=[90.0] * 24,
        solar_vals=[0.0] * 24,
        tariff_vals=[6.0] * 24,
    )
    plan = EnergyOptimizer.solve(req, [])
    sim = simulate_hourly_energy(req, plan, [])
    assert sim.is_valid is True
    assert all(e.solar_used_kwh == 0.0 for e in plan)


# 8. Very high solar (solar >> demand) $\to$ Curtailment and battery charging
def test_edge_very_high_solar_curtailment(standard_battery):
    req = make_request(
        battery=standard_battery,
        demand_vals=[50.0] * 24,
        solar_vals=[300.0] * 24,
        tariff_vals=[10.0] * 24,
    )
    plan = EnergyOptimizer.solve(req, [])
    sim = simulate_hourly_energy(req, plan, [])
    assert sim.is_valid is True
    assert sim.total_cost_bdt == 0.0  # Entire demand covered by solar


# 9. Low and high demand extremes
def test_edge_demand_extremes(standard_battery):
    demand = [10.0] * 12 + [250.0] * 12
    req = make_request(
        battery=standard_battery,
        demand_vals=demand,
        solar_vals=[50.0] * 24,
        tariff_vals=[7.0] * 24,
    )
    plan = EnergyOptimizer.solve(req, [])
    sim = simulate_hourly_energy(req, plan, [])
    assert sim.is_valid is True


# 10. Initial energy at lower bound (E_init == E_min)
def test_edge_initial_energy_at_min():
    bat = BatteryInput(
        capacity_kwh=300.0,
        initial_energy_kwh=50.0,
        minimum_energy_kwh=50.0,
        max_charge_kwh_per_hour=50.0,
        max_discharge_kwh_per_hour=50.0,
    )
    req = make_request(
        battery=bat,
        demand_vals=[100.0] * 24,
        solar_vals=[0.0] * 24,
        tariff_vals=[5.0] * 12 + [15.0] * 12,
    )
    plan = EnergyOptimizer.solve(req, [])
    sim = simulate_hourly_energy(req, plan, [])
    assert sim.is_valid is True
    assert plan[0].battery_action != BatteryAction.DISCHARGE


# 11. Initial energy at capacity (E_init == Capacity)
def test_edge_initial_energy_at_capacity():
    bat = BatteryInput(
        capacity_kwh=300.0,
        initial_energy_kwh=300.0,
        minimum_energy_kwh=50.0,
        max_charge_kwh_per_hour=50.0,
        max_discharge_kwh_per_hour=50.0,
    )
    req = make_request(
        battery=bat,
        demand_vals=[100.0] * 24,
        solar_vals=[0.0] * 24,
        tariff_vals=[15.0] * 12 + [5.0] * 12,
    )
    plan = EnergyOptimizer.solve(req, [])
    sim = simulate_hourly_energy(req, plan, [])
    assert sim.is_valid is True
    assert plan[0].battery_action != BatteryAction.CHARGE


# 12. Infeasible scenario detection: Zero solar, zero grid allowed, zero battery
def test_edge_infeasible_scenario_fails_gracefully():
    bat = BatteryInput(
        capacity_kwh=100.0,
        initial_energy_kwh=10.0,
        minimum_energy_kwh=10.0,
        max_charge_kwh_per_hour=0.0,
        max_discharge_kwh_per_hour=0.0,
    )
    req = make_request(
        battery=bat,
        demand_vals=[200.0] * 24,
        solar_vals=[0.0] * 24,
        tariff_vals=[10.0] * 24,
    )
    # Block grid import to 0 kWh when demand is 200 kWh
    directives = [
        DirectiveInterpretation(note_index=0, applies=True, directive_type=DirectiveType.MAX_GRID_WINDOW, structured_adjustment={"hours": [0], "max_grid_kwh": 0.0}, explanation="block")
    ]
    with pytest.raises(InfeasibleScheduleError):
        EnergyOptimizer.solve(req, directives)


# 13. Exact Determinism test: Repeated solves produce exact same floating point output
def test_edge_exact_determinism(standard_battery):
    req = make_request(
        battery=standard_battery,
        demand_vals=[110.0] * 24,
        solar_vals=[40.0] * 24,
        tariff_vals=[6.0] * 12 + [14.0] * 12,
    )
    plan1 = EnergyOptimizer.solve(req, [])
    plan2 = EnergyOptimizer.solve(req, [])
    for p1, p2 in zip(plan1, plan2):
        assert p1.grid_kwh == p2.grid_kwh
        assert p1.solar_used_kwh == p2.solar_used_kwh
        assert p1.battery_action == p2.battery_action
        assert p1.battery_kwh == p2.battery_kwh
        assert p1.battery_energy_after_kwh == p2.battery_energy_after_kwh
