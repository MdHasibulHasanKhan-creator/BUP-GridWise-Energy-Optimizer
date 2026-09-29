from typing import List, Tuple, Dict, Any
from app.models.response import HourlyPlanEntry, BatteryAction, DirectiveInterpretation
from app.models.request import ScenarioRequest
from app.energy.balance import (
    compute_effective_solar,
    compute_active_battery_reserves,
    compute_forbidden_windows,
    compute_grid_caps,
)


def replay_and_validate_plan(
    plan: List[HourlyPlanEntry],
    request: ScenarioRequest,
    directives: List[DirectiveInterpretation],
) -> Tuple[bool, List[str], Dict[str, float]]:
    """
    Replays the 24-hour schedule against all GridWise constraints and directives.
    Returns: (is_valid, list_of_violations, computed_totals)
    """
    violations = []
    effective_solar = compute_effective_solar(request.hours, directives)
    active_reserves = compute_active_battery_reserves(request.battery, directives)
    no_charge_hours, no_discharge_hours = compute_forbidden_windows(directives)
    grid_caps = compute_grid_caps(directives)

    battery = request.battery
    current_energy = battery.initial_energy_kwh

    total_grid = 0.0
    total_cost = 0.0
    peak_grid = 0.0

    if len(plan) != 24:
        violations.append(f"Plan must contain exactly 24 entries, found {len(plan)}")
        return False, violations, {"total_grid_kwh": 0.0, "total_cost_bdt": 0.0, "peak_grid_kwh": 0.0}

    for h, entry in enumerate(plan):
        hour_data = request.hours[h]
        eff_solar = effective_solar[h]
        min_reserve = active_reserves[h]
        max_grid = grid_caps[h]

        g = entry.grid_kwh
        s = entry.solar_used_kwh
        action = entry.battery_action
        b_kwh = entry.battery_kwh
        e_after = entry.battery_energy_after_kwh

        total_grid += g
        total_cost += g * hour_data.tariff_bdt_per_kwh
        if g > peak_grid:
            peak_grid = g

        # 1. Solar usage bounds
        if s < -0.01:
            violations.append(f"Hour {h}: Negative solar used {s:.4f}")
        if s > eff_solar + 0.01:
            violations.append(f"Hour {h}: Solar used ({s:.4f}) exceeds effective solar ({eff_solar:.4f})")

        # 2. Grid limits & non-negative
        if g < -0.01:
            violations.append(f"Hour {h}: Negative grid import {g:.4f}")
        if g > max_grid + 0.01:
            violations.append(f"Hour {h}: Grid import ({g:.4f}) exceeds max_grid_window limit ({max_grid:.4f})")

        # 3. Battery Action & Rates
        c_kwh = 0.0
        d_kwh = 0.0
        if action == BatteryAction.CHARGE:
            c_kwh = b_kwh
            if h in no_charge_hours and c_kwh > 0.01:
                violations.append(f"Hour {h}: Charging not allowed during no_charge_window")
            if c_kwh > battery.max_charge_kwh_per_hour + 0.01:
                violations.append(f"Hour {h}: Charge rate ({c_kwh:.4f}) exceeds max_charge ({battery.max_charge_kwh_per_hour})")
        elif action == BatteryAction.DISCHARGE:
            d_kwh = b_kwh
            if h in no_discharge_hours and d_kwh > 0.01:
                violations.append(f"Hour {h}: Discharging not allowed during no_discharge_window")
            if d_kwh > battery.max_discharge_kwh_per_hour + 0.01:
                violations.append(f"Hour {h}: Discharge rate ({d_kwh:.4f}) exceeds max_discharge ({battery.max_discharge_kwh_per_hour})")
        elif action == BatteryAction.IDLE:
            if b_kwh > 0.01:
                violations.append(f"Hour {h}: Idle action must have battery_kwh=0, got {b_kwh:.4f}")

        # 4. State transition
        expected_e_after = current_energy + c_kwh - d_kwh
        if abs(e_after - expected_e_after) > 0.01:
            violations.append(f"Hour {h}: Battery transition mismatch: reported {e_after:.4f} vs expected {expected_e_after:.4f}")

        # 5. Battery capacity & active reserve bounds
        if e_after < min_reserve - 0.01:
            violations.append(f"Hour {h}: Battery energy ({e_after:.4f}) below active reserve ({min_reserve:.4f})")
        if e_after > battery.capacity_kwh + 0.01:
            violations.append(f"Hour {h}: Battery energy ({e_after:.4f}) exceeds capacity ({battery.capacity_kwh:.4f})")

        # 6. Hourly Energy Balance: Grid + Solar + Discharge = Demand + Charge
        generation_side = g + s + d_kwh
        demand_side = hour_data.demand_kwh + c_kwh
        if abs(generation_side - demand_side) > 0.01:
            violations.append(f"Hour {h}: Energy balance violation: generation ({generation_side:.4f}) != load ({demand_side:.4f})")

        current_energy = e_after

    # 7. End-of-day battery neutrality
    if abs(current_energy - battery.initial_energy_kwh) > 0.01:
        violations.append(f"End-of-day neutrality violation: final energy {current_energy:.4f} != initial energy {battery.initial_energy_kwh:.4f}")

    is_valid = len(violations) == 0
    metrics = {
        "total_grid_kwh": round(total_grid, 2),
        "total_cost_bdt": round(total_cost, 2),
        "peak_grid_kwh": round(peak_grid, 2),
    }

    return is_valid, violations, metrics
