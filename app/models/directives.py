from enum import Enum
from typing import List, Optional, Union, Dict, Any
from pydantic import BaseModel, Field, field_validator


class DirectiveType(str, Enum):
    SOLAR_REDUCTION = "solar_reduction"
    MINIMUM_BATTERY_RESERVE = "minimum_battery_reserve"
    NO_CHARGE_WINDOW = "no_charge_window"
    NO_DISCHARGE_WINDOW = "no_discharge_window"
    MAX_GRID_WINDOW = "max_grid_window"
    NO_OP = "no_op"


class SolarReductionAdjustment(BaseModel):
    hours: List[int] = Field(..., description="Unique hours 0-23 in ascending order")
    factor: float = Field(..., ge=0.0, le=1.0, description="Remaining usable solar fraction (0.0 to 1.0)")

    @field_validator("hours")
    @classmethod
    def validate_hours(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("hours array must not be empty")
        for h in v:
            if not isinstance(h, int) or h < 0 or h > 23:
                raise ValueError(f"Hour {h} is outside valid range [0, 23]")
        if len(v) != len(set(v)):
            raise ValueError("hours array must contain unique values")
        if v != sorted(v):
            raise ValueError("hours array must be sorted in ascending order")
        return v


class MinimumBatteryReserveAdjustment(BaseModel):
    hours: List[int] = Field(..., description="Unique hours 0-23 in ascending order")
    minimum_energy_kwh: float = Field(..., ge=0.0, description="Minimum battery energy required in kWh")

    @field_validator("hours")
    @classmethod
    def validate_hours(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("hours array must not be empty")
        for h in v:
            if not isinstance(h, int) or h < 0 or h > 23:
                raise ValueError(f"Hour {h} is outside valid range [0, 23]")
        if len(v) != len(set(v)):
            raise ValueError("hours array must contain unique values")
        if v != sorted(v):
            raise ValueError("hours array must be sorted in ascending order")
        return v


class NoChargeWindowAdjustment(BaseModel):
    hours: List[int] = Field(..., description="Unique hours 0-23 in ascending order")

    @field_validator("hours")
    @classmethod
    def validate_hours(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("hours array must not be empty")
        for h in v:
            if not isinstance(h, int) or h < 0 or h > 23:
                raise ValueError(f"Hour {h} is outside valid range [0, 23]")
        if len(v) != len(set(v)):
            raise ValueError("hours array must contain unique values")
        if v != sorted(v):
            raise ValueError("hours array must be sorted in ascending order")
        return v


class NoDischargeWindowAdjustment(BaseModel):
    hours: List[int] = Field(..., description="Unique hours 0-23 in ascending order")

    @field_validator("hours")
    @classmethod
    def validate_hours(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("hours array must not be empty")
        for h in v:
            if not isinstance(h, int) or h < 0 or h > 23:
                raise ValueError(f"Hour {h} is outside valid range [0, 23]")
        if len(v) != len(set(v)):
            raise ValueError("hours array must contain unique values")
        if v != sorted(v):
            raise ValueError("hours array must be sorted in ascending order")
        return v


class MaxGridWindowAdjustment(BaseModel):
    hours: List[int] = Field(..., description="Unique hours 0-23 in ascending order")
    max_grid_kwh: float = Field(..., ge=0.0, description="Maximum grid import in kWh")

    @field_validator("hours")
    @classmethod
    def validate_hours(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("hours array must not be empty")
        for h in v:
            if not isinstance(h, int) or h < 0 or h > 23:
                raise ValueError(f"Hour {h} is outside valid range [0, 23]")
        if len(v) != len(set(v)):
            raise ValueError("hours array must contain unique values")
        if v != sorted(v):
            raise ValueError("hours array must be sorted in ascending order")
        return v


StructuredAdjustmentType = Union[
    SolarReductionAdjustment,
    MinimumBatteryReserveAdjustment,
    NoChargeWindowAdjustment,
    NoDischargeWindowAdjustment,
    MaxGridWindowAdjustment,
    None,
]
