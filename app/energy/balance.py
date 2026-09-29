from typing import List, Dict, Set, Tuple
from app.models.directives import DirectiveType
from app.models.request import HourInput, BatteryInput
from app.models.response import DirectiveInterpretation


def compute_effective_solar(
    hours: List[HourInput],
    directives: List[DirectiveInterpretation],
) -> List[float]:
    """
    Computes effective solar generation for each hour 0-23 by applying all
    active solar_reduction directives.
    """
    effective_solar = [h.solar_kwh for h in hours]

    for d in directives:
        if d.applies and d.directive_type == DirectiveType.SOLAR_REDUCTION and d.structured_adjustment:
            adj_hours = d.structured_adjustment.get("hours", [])
            factor = float(d.structured_adjustment.get("factor", 1.0))
            for h in adj_hours:
                if 0 <= h < 24:
                    effective_solar[h] = effective_solar[h] * factor

    return effective_solar


def compute_active_battery_reserves(
    battery: BatteryInput,
    directives: List[DirectiveInterpretation],
) -> List[float]:
    """
    Computes active minimum battery reserve floor for each hour 0-23.
    min_energy_kwh[h] = max(battery.minimum_energy_kwh, directive_minimum_energy_kwh).
    """
    reserves = [battery.minimum_energy_kwh for _ in range(24)]

    for d in directives:
        if d.applies and d.directive_type == DirectiveType.MINIMUM_BATTERY_RESERVE and d.structured_adjustment:
            adj_hours = d.structured_adjustment.get("hours", [])
            min_energy = float(d.structured_adjustment.get("minimum_energy_kwh", 0.0))
            for h in adj_hours:
                if 0 <= h < 24:
                    reserves[h] = max(reserves[h], min_energy)

    return reserves


def compute_forbidden_windows(
    directives: List[DirectiveInterpretation],
) -> Tuple[Set[int], Set[int]]:
    """
    Returns sets of hours where charging or discharging is disabled: (no_charge_hours, no_discharge_hours).
    """
    no_charge = set()
    no_discharge = set()

    for d in directives:
        if d.applies and d.structured_adjustment:
            adj_hours = d.structured_adjustment.get("hours", [])
            if d.directive_type == DirectiveType.NO_CHARGE_WINDOW:
                for h in adj_hours:
                    if 0 <= h < 24:
                        no_charge.add(h)
            elif d.directive_type == DirectiveType.NO_DISCHARGE_WINDOW:
                for h in adj_hours:
                    if 0 <= h < 24:
                        no_discharge.add(h)

    return no_charge, no_discharge


def compute_grid_caps(
    directives: List[DirectiveInterpretation],
) -> List[float]:
    """
    Computes max grid import cap per hour. Default float('inf').
    """
    caps = [float("inf") for _ in range(24)]

    for d in directives:
        if d.applies and d.directive_type == DirectiveType.MAX_GRID_WINDOW and d.structured_adjustment:
            adj_hours = d.structured_adjustment.get("hours", [])
            max_grid = float(d.structured_adjustment.get("max_grid_kwh", float("inf")))
            for h in adj_hours:
                if 0 <= h < 24:
                    caps[h] = min(caps[h], max_grid)

    return caps
