from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from app.models.response import BatteryAction, HourlyPlanEntry, DirectiveInterpretation
from app.models.request import ScenarioRequest
from app.energy.battery import BatterySimulator, BatteryStepResult, TOLERANCE
from app.energy.balance import (
    compute_effective_solar,
    compute_active_battery_reserves,
    compute_forbidden_windows,
    compute_grid_caps,
)


@dataclass(frozen=True)
class SimulationStep:
    hour: int
    demand_kwh: float
    effective_solar_kwh: float
    tariff_bdt_per_kwh: float
    grid_kwh: float
    solar_used_kwh: float
    solar_curtailed_kwh: float
    battery_step: BatteryStepResult
    energy_balance_error: float
    is_valid: bool
    violations: List[str]


@dataclass(frozen=True)
class SimulationResult:
    is_valid: bool
    violations: List[str]
    steps: List[SimulationStep]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    final_battery_energy_kwh: float
    end_of_day_neutrality_delta: float


def simulate_hourly_energy(
    request: ScenarioRequest,
    plan: List[HourlyPlanEntry],
    directives: Optional[List[DirectiveInterpretation]] = None,
) -> SimulationResult:
    """
    Deterministically simulates and verifies an entire 24-hour dispatch schedule.
    Asserts:
      1. Hourly energy balance: Grid + SolarUsed + BatteryDischarge = Demand + BatteryCharge
      2. Solar constraints: 0 <= SolarUsed <= EffectiveSolar
      3. Battery bounds: ActiveMinReserve <= E_after <= Capacity
      4. Rate limits: Charge <= MaxCharge, Discharge <= MaxDischarge
      5. Window constraints: no_charge, no_discharge, max_grid
      6. Terminal neutrality: E_23 == E_initial
    """
    if directives is None:
        directives = []

    effective_solar = compute_effective_solar(request.hours, directives)
    active_reserves = compute_active_battery_reserves(request.battery, directives)
    no_charge_hours, no_discharge_hours = compute_forbidden_windows(directives)
    grid_caps = compute_grid_caps(directives)

    battery_params = request.battery
    current_energy = battery_params.initial_energy_kwh

    steps: List[SimulationStep] = []
    global_violations: List[str] = []

    total_grid = 0.0
    total_cost = 0.0
    peak_grid = 0.0

    if len(plan) != 24:
        global_violations.append(f"Expected exactly 24 plan hours, got {len(plan)}")
        return SimulationResult(
            is_valid=False,
            violations=global_violations,
            steps=[],
            total_grid_kwh=0.0,
            total_cost_bdt=0.0,
            peak_grid_kwh=0.0,
            final_battery_energy_kwh=current_energy,
            end_of_day_neutrality_delta=0.0,
        )

    for h, entry in enumerate(plan):
        hour_in = request.hours[h]
        eff_solar = effective_solar[h]
        min_res = active_reserves[h]
        max_grid = grid_caps[h]
        no_c = h in no_charge_hours
        no_d = h in no_discharge_hours

        step_violations: List[str] = []

        # 1. Simulate battery step
        b_res = BatterySimulator.step(
            energy_before_kwh=current_energy,
            action=entry.battery_action,
            battery_kwh=entry.battery_kwh,
            battery_params=battery_params,
            active_min_reserve_kwh=min_res,
            no_charge=no_c,
            no_discharge=no_d,
        )

        if not b_res.is_valid:
            step_violations.append(f"Hour {h} Battery: {b_res.violation}")

        # 2. Check reported battery energy consistency
        if abs(entry.battery_energy_after_kwh - b_res.energy_after_kwh) > TOLERANCE:
            step_violations.append(
                f"Hour {h}: Reported battery_energy_after_kwh ({entry.battery_energy_after_kwh}) "
                f"does not match simulated energy ({b_res.energy_after_kwh})"
            )

        # 3. Solar verification
        if entry.solar_used_kwh < -TOLERANCE:
            step_violations.append(f"Hour {h}: Negative solar used ({entry.solar_used_kwh})")
        if entry.solar_used_kwh > eff_solar + TOLERANCE:
            step_violations.append(
                f"Hour {h}: Solar used ({entry.solar_used_kwh:.4f}) exceeds effective solar ({eff_solar:.4f})"
            )
        curtailed_solar = max(0.0, eff_solar - entry.solar_used_kwh)

        # 4. Grid import verification
        if entry.grid_kwh < -TOLERANCE:
            step_violations.append(f"Hour {h}: Negative grid import ({entry.grid_kwh})")
        if entry.grid_kwh > max_grid + TOLERANCE:
            step_violations.append(
                f"Hour {h}: Grid import ({entry.grid_kwh:.4f}) exceeds max grid cap ({max_grid:.4f})"
            )

        # 5. Energy Balance Equation: Grid + SolarUsed + Discharge = Demand + Charge
        charge_kwh = entry.battery_kwh if entry.battery_action == BatteryAction.CHARGE else 0.0
        discharge_kwh = entry.battery_kwh if entry.battery_action == BatteryAction.DISCHARGE else 0.0

        gen_side = entry.grid_kwh + entry.solar_used_kwh + discharge_kwh
        load_side = hour_in.demand_kwh + charge_kwh
        balance_err = abs(gen_side - load_side)

        if balance_err > TOLERANCE:
            step_violations.append(
                f"Hour {h}: Energy balance error {balance_err:.4f} kWh (Supply={gen_side:.4f}, Demand={load_side:.4f})"
            )

        total_grid += entry.grid_kwh
        total_cost += entry.grid_kwh * hour_in.tariff_bdt_per_kwh
        if entry.grid_kwh > peak_grid:
            peak_grid = entry.grid_kwh

        steps.append(
            SimulationStep(
                hour=h,
                demand_kwh=hour_in.demand_kwh,
                effective_solar_kwh=eff_solar,
                tariff_bdt_per_kwh=hour_in.tariff_bdt_per_kwh,
                grid_kwh=entry.grid_kwh,
                solar_used_kwh=entry.solar_used_kwh,
                solar_curtailed_kwh=round(curtailed_solar, 6),
                battery_step=b_res,
                energy_balance_error=round(balance_err, 6),
                is_valid=len(step_violations) == 0,
                violations=step_violations,
            )
        )

        global_violations.extend(step_violations)
        current_energy = b_res.energy_after_kwh

    # 6. End-of-day battery neutrality
    neutrality_delta = abs(current_energy - battery_params.initial_energy_kwh)
    if neutrality_delta > TOLERANCE:
        global_violations.append(
            f"End-of-day neutrality violation: final energy {current_energy:.4f} kWh != "
            f"initial energy {battery_params.initial_energy_kwh:.4f} kWh (delta={neutrality_delta:.4f} kWh)"
        )

    return SimulationResult(
        is_valid=len(global_violations) == 0,
        violations=global_violations,
        steps=steps,
        total_grid_kwh=round(total_grid, 2),
        total_cost_bdt=round(total_cost, 2),
        peak_grid_kwh=round(peak_grid, 2),
        final_battery_energy_kwh=round(current_energy, 4),
        end_of_day_neutrality_delta=round(neutrality_delta, 6),
    )
