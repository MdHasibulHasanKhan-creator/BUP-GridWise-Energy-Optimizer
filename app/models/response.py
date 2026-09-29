from enum import Enum
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field, field_validator, model_validator
from app.models.directives import DirectiveType


class BatteryAction(str, Enum):
    CHARGE = "charge"
    DISCHARGE = "discharge"
    IDLE = "idle"


class DirectiveInterpretation(BaseModel):
    note_index: int = Field(..., ge=0, description="Zero-based index corresponding to operator note")
    applies: bool = Field(..., description="True if non-no_op, False if no_op")
    directive_type: DirectiveType = Field(..., description="Recognized directive type")
    structured_adjustment: Optional[Dict[str, Any]] = Field(None, description="Adjustment payload, null for no_op")
    explanation: str = Field(..., min_length=1, description="Brief explanation of the directive")

    @model_validator(mode="after")
    def validate_applies_and_adjustment(self) -> "DirectiveInterpretation":
        if self.directive_type == DirectiveType.NO_OP:
            if self.applies is not False:
                raise ValueError("applies must be false when directive_type is no_op")
            if self.structured_adjustment is not None:
                raise ValueError("structured_adjustment must be null when directive_type is no_op")
        else:
            if self.applies is not True:
                raise ValueError("applies must be true when directive_type is not no_op")
            if self.structured_adjustment is None:
                raise ValueError(f"structured_adjustment cannot be null for {self.directive_type}")
        return self


class HourlyPlanEntry(BaseModel):
    hour: int = Field(..., ge=0, le=23, description="Hour of the day (0-23)")
    grid_kwh: float = Field(..., ge=0.0, description="Non-negative grid energy purchased in kWh")
    solar_used_kwh: float = Field(..., ge=0.0, description="Solar energy consumed in kWh")
    battery_action: BatteryAction = Field(..., description="One of: charge, discharge, idle")
    battery_kwh: float = Field(..., ge=0.0, description="Magnitude of battery energy flow in kWh (0 when idle)")
    battery_energy_after_kwh: float = Field(..., ge=0.0, description="Battery energy state immediately after this hour")

    @model_validator(mode="after")
    def validate_battery_action_consistency(self) -> "HourlyPlanEntry":
        if self.battery_action == BatteryAction.IDLE:
            if abs(self.battery_kwh) > 1e-4:
                raise ValueError(f"battery_kwh must be 0 when battery_action is idle, got {self.battery_kwh}")
        return self


class HealthResponse(BaseModel):
    status: str = Field("ok", description="Readiness status")


class ScenarioResponse(BaseModel):
    scenario_id: str = Field(..., description="Echoed scenario identifier")
    directive_interpretation: List[DirectiveInterpretation] = Field(..., description="Interpreted directives")
    hourly_plan: List[HourlyPlanEntry] = Field(..., min_length=24, max_length=24, description="24-hour plan")
    total_grid_kwh: float = Field(..., ge=0.0, description="Sum of grid energy across 24 hours")
    total_cost_bdt: float = Field(..., ge=0.0, description="Calculated total grid electricity cost in BDT")
    peak_grid_kwh: float = Field(..., ge=0.0, description="Maximum hourly grid import in kWh")
    plan_summary: str = Field(..., min_length=1, description="Human-readable summary of the optimization strategy")

    @field_validator("hourly_plan")
    @classmethod
    def validate_plan_hours(cls, v: List[HourlyPlanEntry]) -> List[HourlyPlanEntry]:
        if len(v) != 24:
            raise ValueError("hourly_plan must contain exactly 24 hours")
        for idx, entry in enumerate(v):
            if entry.hour != idx:
                raise ValueError(f"hourly_plan entry at index {idx} must have hour={idx}, got {entry.hour}")
        return v
