from typing import List, Dict, Any, Optional
import math
from app.models.directives import (
    DirectiveType,
    SolarReductionAdjustment,
    MinimumBatteryReserveAdjustment,
    NoChargeWindowAdjustment,
    NoDischargeWindowAdjustment,
    MaxGridWindowAdjustment,
)
from app.models.response import DirectiveInterpretation


class DirectiveGuardrail:
    """
    Deterministic guardrail to validate, sanitize, and normalize
    raw LLM-extracted directive interpretations before optimization.
    """

    @staticmethod
    def sanitize_hours(raw_hours: Any) -> List[int]:
        """Ensure hours is a unique, ascending list of valid integers 0-23."""
        if not isinstance(raw_hours, list):
            return []
        valid_hours = set()
        for h in raw_hours:
            try:
                val = int(h)
                if 0 <= val <= 23:
                    valid_hours.add(val)
            except (ValueError, TypeError):
                continue
        return sorted(list(valid_hours))

    @classmethod
    def sanitize_directive(
        cls,
        note_index: int,
        raw_directive: Dict[str, Any],
        battery_capacity_kwh: Optional[float] = None,
    ) -> DirectiveInterpretation:
        """
        Sanitize an individual directive dictionary against canonical constraints.
        """
        raw_type = str(raw_directive.get("directive_type", "")).lower().strip()
        explanation = str(raw_directive.get("explanation", "")).strip() or "Standard directive interpretation."

        # Map to valid DirectiveType enum or fallback to no_op
        try:
            directive_type = DirectiveType(raw_type)
        except ValueError:
            directive_type = DirectiveType.NO_OP

        if directive_type == DirectiveType.NO_OP:
            return DirectiveInterpretation(
                note_index=note_index,
                applies=False,
                directive_type=DirectiveType.NO_OP,
                structured_adjustment=None,
                explanation=explanation,
            )

        raw_adj = raw_directive.get("structured_adjustment")
        if not isinstance(raw_adj, dict):
            # If missing adjustment for a non-no_op directive, fallback to no_op
            return DirectiveInterpretation(
                note_index=note_index,
                applies=False,
                directive_type=DirectiveType.NO_OP,
                structured_adjustment=None,
                explanation=f"{explanation} (adjustment data missing; defaulted to no-op)",
            )

        hours = cls.sanitize_hours(raw_adj.get("hours"))
        if not hours:
            return DirectiveInterpretation(
                note_index=note_index,
                applies=False,
                directive_type=DirectiveType.NO_OP,
                structured_adjustment=None,
                explanation=f"{explanation} (invalid hours range; defaulted to no-op)",
            )

        if directive_type == DirectiveType.SOLAR_REDUCTION:
            try:
                factor = float(raw_adj.get("factor", 1.0))
                factor = max(0.0, min(1.0, factor))
            except (ValueError, TypeError):
                factor = 1.0
            adj = SolarReductionAdjustment(hours=hours, factor=factor)
            return DirectiveInterpretation(
                note_index=note_index,
                applies=True,
                directive_type=DirectiveType.SOLAR_REDUCTION,
                structured_adjustment=adj.model_dump(),
                explanation=explanation,
            )

        elif directive_type == DirectiveType.MINIMUM_BATTERY_RESERVE:
            try:
                min_energy = float(raw_adj.get("minimum_energy_kwh", 0.0))
                min_energy = max(0.0, min_energy)
                if battery_capacity_kwh is not None:
                    min_energy = min(min_energy, battery_capacity_kwh)
            except (ValueError, TypeError):
                min_energy = 0.0
            adj = MinimumBatteryReserveAdjustment(hours=hours, minimum_energy_kwh=min_energy)
            return DirectiveInterpretation(
                note_index=note_index,
                applies=True,
                directive_type=DirectiveType.MINIMUM_BATTERY_RESERVE,
                structured_adjustment=adj.model_dump(),
                explanation=explanation,
            )

        elif directive_type == DirectiveType.NO_CHARGE_WINDOW:
            adj = NoChargeWindowAdjustment(hours=hours)
            return DirectiveInterpretation(
                note_index=note_index,
                applies=True,
                directive_type=DirectiveType.NO_CHARGE_WINDOW,
                structured_adjustment=adj.model_dump(),
                explanation=explanation,
            )

        elif directive_type == DirectiveType.NO_DISCHARGE_WINDOW:
            adj = NoDischargeWindowAdjustment(hours=hours)
            return DirectiveInterpretation(
                note_index=note_index,
                applies=True,
                directive_type=DirectiveType.NO_DISCHARGE_WINDOW,
                structured_adjustment=adj.model_dump(),
                explanation=explanation,
            )

        elif directive_type == DirectiveType.MAX_GRID_WINDOW:
            try:
                max_grid = float(raw_adj.get("max_grid_kwh", 0.0))
                max_grid = max(0.0, max_grid)
                if math.isinf(max_grid) or math.isnan(max_grid):
                    max_grid = 0.0
            except (ValueError, TypeError):
                max_grid = 0.0
            adj = MaxGridWindowAdjustment(hours=hours, max_grid_kwh=max_grid)
            return DirectiveInterpretation(
                note_index=note_index,
                applies=True,
                directive_type=DirectiveType.MAX_GRID_WINDOW,
                structured_adjustment=adj.model_dump(),
                explanation=explanation,
            )

        # Fallback
        return DirectiveInterpretation(
            note_index=note_index,
            applies=False,
            directive_type=DirectiveType.NO_OP,
            structured_adjustment=None,
            explanation=explanation,
        )

    @classmethod
    def validate_and_guardrail_interpretations(
        cls,
        num_notes: int,
        raw_interpretations: List[Dict[str, Any]],
        battery_capacity_kwh: Optional[float] = None,
    ) -> List[DirectiveInterpretation]:
        """
        Guarantees exactly one DirectiveInterpretation per note index 0..N-1.
        """
        results = []
        lookup = {}
        for item in raw_interpretations:
            if isinstance(item, dict) and "note_index" in item:
                try:
                    idx = int(item["note_index"])
                    lookup[idx] = item
                except (ValueError, TypeError):
                    pass

        for idx in range(num_notes):
            raw_item = lookup.get(idx)
            if raw_item is not None:
                sanitized = cls.sanitize_directive(idx, raw_item, battery_capacity_kwh)
            else:
                sanitized = DirectiveInterpretation(
                    note_index=idx,
                    applies=False,
                    directive_type=DirectiveType.NO_OP,
                    structured_adjustment=None,
                    explanation="No directive recognized; treated as no-op.",
                )
            results.append(sanitized)

        return results
