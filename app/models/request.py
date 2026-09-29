from typing import List
from pydantic import BaseModel, Field, field_validator, model_validator


class HourInput(BaseModel):
    hour: int = Field(..., ge=0, le=23, description="Hour of day (0-23)")
    demand_kwh: float = Field(..., ge=0.0, description="Campus demand in kWh")
    solar_kwh: float = Field(..., ge=0.0, description="Base solar generation available in kWh")
    tariff_bdt_per_kwh: float = Field(..., ge=0.0, description="Grid tariff in BDT/kWh")


class BatteryInput(BaseModel):
    capacity_kwh: float = Field(..., gt=0.0, description="Total battery capacity in kWh")
    initial_energy_kwh: float = Field(..., ge=0.0, description="Initial energy at start of hour 0 in kWh")
    minimum_energy_kwh: float = Field(..., ge=0.0, description="Base minimum reserve in kWh")
    max_charge_kwh_per_hour: float = Field(..., ge=0.0, description="Max charge rate in kWh/hour")
    max_discharge_kwh_per_hour: float = Field(..., ge=0.0, description="Max discharge rate in kWh/hour")

    @model_validator(mode="after")
    def validate_battery_bounds(self) -> "BatteryInput":
        if self.initial_energy_kwh > self.capacity_kwh:
            raise ValueError(f"initial_energy_kwh ({self.initial_energy_kwh}) cannot exceed capacity_kwh ({self.capacity_kwh})")
        if self.minimum_energy_kwh > self.capacity_kwh:
            raise ValueError(f"minimum_energy_kwh ({self.minimum_energy_kwh}) cannot exceed capacity_kwh ({self.capacity_kwh})")
        if self.initial_energy_kwh < self.minimum_energy_kwh:
            raise ValueError(f"initial_energy_kwh ({self.initial_energy_kwh}) cannot be below minimum_energy_kwh ({self.minimum_energy_kwh})")
        return self


class ScenarioRequest(BaseModel):
    scenario_id: str = Field(..., min_length=1, description="Unique scenario identifier")
    operator_notes: List[str] = Field(..., min_length=1, max_length=3, description="1 to 3 operator notes")
    hours: List[HourInput] = Field(..., min_length=24, max_length=24, description="Exactly 24 hourly records")
    battery: BatteryInput = Field(..., description="Battery parameters")

    @field_validator("operator_notes")
    @classmethod
    def validate_notes(cls, v: List[str]) -> List[str]:
        if not (1 <= len(v) <= 3):
            raise ValueError("operator_notes must contain between 1 and 3 items")
        for idx, note in enumerate(v):
            if not isinstance(note, str) or not note.strip():
                raise ValueError(f"operator_note at index {idx} must be a non-empty string")
        return v

    @field_validator("hours")
    @classmethod
    def validate_hours_sequence(cls, v: List[HourInput]) -> List[HourInput]:
        if len(v) != 24:
            raise ValueError("hours array must contain exactly 24 elements")
        seen_hours = set()
        for idx, item in enumerate(v):
            if item.hour != idx:
                raise ValueError(f"hours array element at index {idx} must have hour={idx}, got {item.hour}")
            seen_hours.add(item.hour)
        if len(seen_hours) != 24:
            raise ValueError("hours array must contain unique hours 0 through 23")
        return v
