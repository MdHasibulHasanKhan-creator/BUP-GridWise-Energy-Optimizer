from typing import List, Set, Dict, Any, Optional
from dataclasses import dataclass
from app.models.directives import DirectiveType
from app.models.request import ScenarioRequest, HourInput, BatteryInput
from app.models.response import DirectiveInterpretation
from app.energy.balance import (
    compute_effective_solar,
    compute_active_battery_reserves,
    compute_forbidden_windows,
    compute_grid_caps,
)


@dataclass(frozen=True)
class ScenarioConstraints:
    """
    Deterministic mathematical constraints compiled from validated directives.
    Used by the optimizer to enforce physical and operational bounds.
    """
    effective_solar_kwh: List[float]
    active_battery_reserves_kwh: List[float]
    forbidden_charge_hours: Set[int]
    forbidden_discharge_hours: Set[int]
    max_grid_kwh_per_hour: List[float]


def compile_scenario_constraints(
    request: ScenarioRequest,
    directives: List[DirectiveInterpretation],
) -> ScenarioConstraints:
    """
    Deterministically transforms a list of validated directives into concrete
    numerical constraint structures for the 24-hour horizon.
    """
    effective_solar = compute_effective_solar(request.hours, directives)
    active_reserves = compute_active_battery_reserves(request.battery, directives)
    no_charge_hours, no_discharge_hours = compute_forbidden_windows(directives)
    grid_caps = compute_grid_caps(directives)

    return ScenarioConstraints(
        effective_solar_kwh=effective_solar,
        active_battery_reserves_kwh=active_reserves,
        forbidden_charge_hours=no_charge_hours,
        forbidden_discharge_hours=no_discharge_hours,
        max_grid_kwh_per_hour=grid_caps,
    )
