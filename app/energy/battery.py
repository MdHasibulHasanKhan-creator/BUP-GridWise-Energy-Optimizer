from typing import Tuple, Optional
from dataclasses import dataclass
from app.models.response import BatteryAction
from app.models.request import BatteryInput

TOLERANCE = 0.01  # Official canonical tolerance: 0.01 kWh / 0.01 BDT


@dataclass(frozen=True)
class BatteryStepResult:
    energy_before_kwh: float
    action: BatteryAction
    battery_kwh: float
    energy_after_kwh: float
    is_valid: bool
    violation: Optional[str] = None


class BatterySimulator:
    """
    Deterministic Battery Energy Storage System (BESS) Simulator.
    Strictly follows Problem Statement Section 09.1-09.3.
    """

    @staticmethod
    def step(
        energy_before_kwh: float,
        action: BatteryAction,
        battery_kwh: float,
        battery_params: BatteryInput,
        active_min_reserve_kwh: Optional[float] = None,
        no_charge: bool = False,
        no_discharge: bool = False,
    ) -> BatteryStepResult:
        """
        Executes a single 1-hour deterministic battery state transition.
        Governing equations:
          - charge:    E_after = E_before + battery_kwh
          - discharge: E_after = E_before - battery_kwh
          - idle:      E_after = E_before (battery_kwh = 0)
        """
        min_reserve = (
            max(battery_params.minimum_energy_kwh, active_min_reserve_kwh)
            if active_min_reserve_kwh is not None
            else battery_params.minimum_energy_kwh
        )

        if battery_kwh < -TOLERANCE:
            return BatteryStepResult(
                energy_before_kwh=energy_before_kwh,
                action=action,
                battery_kwh=battery_kwh,
                energy_after_kwh=energy_before_kwh,
                is_valid=False,
                violation=f"battery_kwh cannot be negative: {battery_kwh}",
            )

        # Normalize very small numerical noise to 0.0
        if abs(battery_kwh) < 1e-5:
            battery_kwh = 0.0

        if action == BatteryAction.IDLE:
            if battery_kwh > TOLERANCE:
                return BatteryStepResult(
                    energy_before_kwh=energy_before_kwh,
                    action=action,
                    battery_kwh=battery_kwh,
                    energy_after_kwh=energy_before_kwh,
                    is_valid=False,
                    violation=f"battery_kwh must be 0 for idle action, got {battery_kwh}",
                )
            return BatteryStepResult(
                energy_before_kwh=energy_before_kwh,
                action=action,
                battery_kwh=0.0,
                energy_after_kwh=energy_before_kwh,
                is_valid=True,
            )

        elif action == BatteryAction.CHARGE:
            if no_charge and battery_kwh > TOLERANCE:
                return BatteryStepResult(
                    energy_before_kwh=energy_before_kwh,
                    action=action,
                    battery_kwh=battery_kwh,
                    energy_after_kwh=energy_before_kwh + battery_kwh,
                    is_valid=False,
                    violation="Charging is prohibited during no_charge_window",
                )

            if battery_kwh > battery_params.max_charge_kwh_per_hour + TOLERANCE:
                return BatteryStepResult(
                    energy_before_kwh=energy_before_kwh,
                    action=action,
                    battery_kwh=battery_kwh,
                    energy_after_kwh=energy_before_kwh + battery_kwh,
                    is_valid=False,
                    violation=f"Charge amount {battery_kwh:.4f} kWh exceeds max charge rate {battery_params.max_charge_kwh_per_hour:.4f} kWh/h",
                )

            energy_after = energy_before_kwh + battery_kwh
            if energy_after > battery_params.capacity_kwh + TOLERANCE:
                return BatteryStepResult(
                    energy_before_kwh=energy_before_kwh,
                    action=action,
                    battery_kwh=battery_kwh,
                    energy_after_kwh=energy_after,
                    is_valid=False,
                    violation=f"Battery energy after charge {energy_after:.4f} kWh exceeds capacity {battery_params.capacity_kwh:.4f} kWh",
                )

            return BatteryStepResult(
                energy_before_kwh=energy_before_kwh,
                action=action,
                battery_kwh=battery_kwh,
                energy_after_kwh=round(energy_after, 6),
                is_valid=True,
            )

        elif action == BatteryAction.DISCHARGE:
            if no_discharge and battery_kwh > TOLERANCE:
                return BatteryStepResult(
                    energy_before_kwh=energy_before_kwh,
                    action=action,
                    battery_kwh=battery_kwh,
                    energy_after_kwh=energy_before_kwh - battery_kwh,
                    is_valid=False,
                    violation="Discharging is prohibited during no_discharge_window",
                )

            if battery_kwh > battery_params.max_discharge_kwh_per_hour + TOLERANCE:
                return BatteryStepResult(
                    energy_before_kwh=energy_before_kwh,
                    action=action,
                    battery_kwh=battery_kwh,
                    energy_after_kwh=energy_before_kwh - battery_kwh,
                    is_valid=False,
                    violation=f"Discharge amount {battery_kwh:.4f} kWh exceeds max discharge rate {battery_params.max_discharge_kwh_per_hour:.4f} kWh/h",
                )

            energy_after = energy_before_kwh - battery_kwh
            if energy_after < min_reserve - TOLERANCE:
                return BatteryStepResult(
                    energy_before_kwh=energy_before_kwh,
                    action=action,
                    battery_kwh=battery_kwh,
                    energy_after_kwh=energy_after,
                    is_valid=False,
                    violation=f"Battery energy after discharge {energy_after:.4f} kWh is below active reserve {min_reserve:.4f} kWh",
                )

            return BatteryStepResult(
                energy_before_kwh=energy_before_kwh,
                action=action,
                battery_kwh=battery_kwh,
                energy_after_kwh=round(energy_after, 6),
                is_valid=True,
            )

        return BatteryStepResult(
            energy_before_kwh=energy_before_kwh,
            action=action,
            battery_kwh=battery_kwh,
            energy_after_kwh=energy_before_kwh,
            is_valid=False,
            violation=f"Unknown battery action: {action}",
        )
