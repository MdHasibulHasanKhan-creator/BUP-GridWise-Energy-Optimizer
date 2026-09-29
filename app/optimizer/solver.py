from typing import List, Tuple, Optional
import numpy as np
from scipy.optimize import linprog
from app.models.request import ScenarioRequest
from app.models.response import HourlyPlanEntry, BatteryAction, DirectiveInterpretation
from app.guardrails.constraints import compile_scenario_constraints, ScenarioConstraints
from app.energy.battery import TOLERANCE


class InfeasibleScheduleError(Exception):
    """Raised when no physically valid schedule can satisfy all hard constraints."""
    pass


class EnergyOptimizer:
    """
    Deterministic 24-hour Linear Programming energy scheduling optimizer using SciPy HiGHS.
    
    Decision Variables per hour h in [0..23] (5 per hour -> 120 total):
      - G_h : Grid electricity purchased in hour h (kWh) [cost = Tariff_h]
      - s_h : Solar energy consumed in hour h (kWh) [cost = -1e-5 to prioritize free solar]
      - C_h : Battery energy charged in hour h (kWh) [cost = +1e-6 to avoid unnecessary cycling]
      - D_h : Battery energy discharged in hour h (kWh) [cost = +1e-6 to avoid unnecessary cycling]
      - E_h : Battery energy state immediately after hour h (kWh) [cost = 0]
    
    Hard Constraints:
      1. Energy Balance (24 equalities): G_h + s_h + D_h - C_h = Demand_h
      2. Battery State Transitions (24 equalities): E_h - E_{h-1} - C_h + D_h = 0 (E_{-1} = InitialEnergy)
      3. End-of-Day Neutrality (1 equality): E_23 = InitialEnergy
      4. Solar Limits: 0 <= s_h <= EffectiveSolar_h
      5. Active Battery Reserve & Capacity: ActiveMinReserve_h <= E_h <= Capacity
      6. Charge Rate Limits: 0 <= C_h <= (0 if h in no_charge else MaxCharge)
      7. Discharge Rate Limits: 0 <= D_h <= (0 if h in no_discharge else MaxDischarge)
      8. Grid Import Caps: 0 <= G_h <= MaxGrid_h
    """

    N_HOURS = 24
    VARS_PER_HOUR = 5

    @classmethod
    def solve(
        cls,
        request: ScenarioRequest,
        directives: List[DirectiveInterpretation],
    ) -> List[HourlyPlanEntry]:
        """
        Solves the cost-optimal 24-hour dispatch schedule.
        Throws InfeasibleScheduleError if the constraints cannot be satisfied.
        """
        constraints: ScenarioConstraints = compile_scenario_constraints(request, directives)
        battery = request.battery
        n_hours = cls.N_HOURS
        n_vars = n_hours * cls.VARS_PER_HOUR

        def idx(h: int, var_type: int) -> int:
            # var_type: 0: G, 1: s, 2: C, 3: D, 4: E
            return h * cls.VARS_PER_HOUR + var_type

        # 1. Objective function vector c
        c = np.zeros(n_vars)
        for h in range(n_hours):
            tariff = float(request.hours[h].tariff_bdt_per_kwh)
            c[idx(h, 0)] = tariff      # minimize total grid electricity cost
            c[idx(h, 1)] = -1e-5       # tie-breaker: consume all free available solar before curtailing
            c[idx(h, 2)] = 1e-6        # tie-breaker: prevent unnecessary battery charge cycling
            c[idx(h, 3)] = 1e-6        # tie-breaker: prevent simultaneous charging and discharging

        # 2. Variable Bounds
        bounds = []
        for h in range(n_hours):
            # G_h : grid import
            g_max = (
                constraints.max_grid_kwh_per_hour[h]
                if constraints.max_grid_kwh_per_hour[h] < float("inf")
                else None
            )
            bounds.append((0.0, g_max))

            # s_h : solar used
            bounds.append((0.0, constraints.effective_solar_kwh[h]))

            # C_h : charge rate
            c_max = (
                0.0
                if h in constraints.forbidden_charge_hours
                else battery.max_charge_kwh_per_hour
            )
            bounds.append((0.0, c_max))

            # D_h : discharge rate
            d_max = (
                0.0
                if h in constraints.forbidden_discharge_hours
                else battery.max_discharge_kwh_per_hour
            )
            bounds.append((0.0, d_max))

            # E_h : battery energy bounds
            min_e = constraints.active_battery_reserves_kwh[h]
            max_e = battery.capacity_kwh
            if min_e > max_e:
                raise InfeasibleScheduleError(
                    f"Infeasible: Active minimum reserve ({min_e} kWh) exceeds capacity ({max_e} kWh) at hour {h}"
                )
            bounds.append((min_e, max_e))

        # 3. Equalities Formulation A_eq @ x == b_eq
        # Total equality rows = 24 (energy balance) + 24 (battery transition) + 1 (neutrality) = 49
        n_eq = n_hours + n_hours + 1
        A_eq = np.zeros((n_eq, n_vars))
        b_eq = np.zeros(n_eq)

        row = 0
        # Energy balance rows: G_h + s_h - C_h + D_h = Demand_h
        for h in range(n_hours):
            A_eq[row, idx(h, 0)] = 1.0  # +G_h
            A_eq[row, idx(h, 1)] = 1.0  # +s_h
            A_eq[row, idx(h, 2)] = -1.0 # -C_h
            A_eq[row, idx(h, 3)] = 1.0  # +D_h
            b_eq[row] = float(request.hours[h].demand_kwh)
            row += 1

        # Battery transition rows: E_h - E_{h-1} - C_h + D_h = 0
        for h in range(n_hours):
            A_eq[row, idx(h, 4)] = 1.0  # +E_h
            A_eq[row, idx(h, 2)] = -1.0 # -C_h
            A_eq[row, idx(h, 3)] = 1.0  # +D_h
            if h == 0:
                b_eq[row] = float(battery.initial_energy_kwh)
            else:
                A_eq[row, idx(h - 1, 4)] = -1.0 # -E_{h-1}
                b_eq[row] = 0.0
            row += 1

        # End-of-Day Neutrality row: E_23 = InitialEnergy
        A_eq[row, idx(23, 4)] = 1.0
        b_eq[row] = float(battery.initial_energy_kwh)
        row += 1

        # 4. Solve Linear Program via HiGHS
        res = linprog(
            c=c,
            A_eq=A_eq,
            b_eq=b_eq,
            bounds=bounds,
            method="highs",
            options={"presolve": True},
        )

        if not res.success:
            raise InfeasibleScheduleError(
                f"Optimization solver failed to find a feasible solution: {res.message} (status {res.status})"
            )

        x = res.x
        plan: List[HourlyPlanEntry] = []

        for h in range(n_hours):
            g = max(0.0, float(x[idx(h, 0)]))
            s = max(0.0, float(x[idx(h, 1)]))
            c_val = max(0.0, float(x[idx(h, 2)]))
            d_val = max(0.0, float(x[idx(h, 3)]))
            e_after = max(0.0, float(x[idx(h, 4)]))

            # Numerical zero clamping
            if g < 1e-5:
                g = 0.0
            if s < 1e-5:
                s = 0.0
            if c_val < 1e-5:
                c_val = 0.0
            if d_val < 1e-5:
                d_val = 0.0

            # Determine mutually exclusive categorical action
            if c_val > 1e-4 and c_val >= d_val:
                action = BatteryAction.CHARGE
                b_kwh = c_val
            elif d_val > 1e-4 and d_val > c_val:
                action = BatteryAction.DISCHARGE
                b_kwh = d_val
            else:
                action = BatteryAction.IDLE
                b_kwh = 0.0

            plan.append(
                HourlyPlanEntry(
                    hour=h,
                    grid_kwh=round(g, 4),
                    solar_used_kwh=round(s, 4),
                    battery_action=action,
                    battery_kwh=round(b_kwh, 4),
                    battery_energy_after_kwh=round(e_after, 4),
                )
            )

        return plan
