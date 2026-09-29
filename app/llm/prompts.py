import json
from typing import List, Dict, Any, Optional

SYSTEM_INSTRUCTION = """You are the expert GridWise Energy Optimization Directive Interpreter for BUP Smart Campus.
Your task is to analyze 1 to 3 operator notes and extract structured operational directives for a 24-hour dispatch schedule (hours 0 to 23).

### CANONICAL DIRECTIVE RULES:
1. Only the following 6 directive types are permitted:
   - "solar_reduction": Usable solar output is reduced during specific hours.
     Adjustment: {"hours": [int, ...], "factor": float}
     NOTE: "factor" is the remaining usable fraction (0.0 to 1.0). An "80% reduction" means factor=0.2. "Drop to 25%" means factor=0.25. "Half" means factor=0.5.
   - "minimum_battery_reserve": Battery energy must remain at or above a specified kWh level during specific hours.
     Adjustment: {"hours": [int, ...], "minimum_energy_kwh": float}
     NOTE: If stated as a percentage of capacity (e.g. 50%), multiply by battery capacity_kwh.
   - "no_charge_window": Battery charging is disabled during specific hours.
     Adjustment: {"hours": [int, ...]}
   - "no_discharge_window": Battery discharging is disabled during specific hours.
     Adjustment: {"hours": [int, ...]}
   - "max_grid_window": Grid power import is capped at a maximum kWh during specific hours.
     Adjustment: {"hours": [int, ...], "max_grid_kwh": float}
   - "no_op": The note is an administrative announcement, distractor, or irrelevant to the 24-hour energy schedule.
     Adjustment: null

2. TIME WINDOW RULES:
   - Hours are 0-indexed integers from 0 through 23.
   - Time ranges are start-hour INCLUSIVE and end-hour EXCLUSIVE:
     * "noon until 2 PM" -> [12, 13]
     * "1 PM to 3 PM" (or "13:00 to 15:00") -> [13, 14]
     * "2 AM until 5 AM" -> [2, 3, 4]
     * "6 PM until 9 PM" -> [18, 19, 20]
     * "6 PM until 10 PM" -> [18, 19, 20, 21]
     * "7 PM until 9 PM" -> [19, 20]
     * "7 PM until 10 PM" -> [19, 20, 21]
     * "11 AM until 1 PM" -> [11, 12]
     * "11 AM until 2 PM" -> [11, 12, 13]
     * "5 PM until 7 PM" -> [17, 18]
     * "6 PM until 8 PM" -> [18, 19]
     * "10 AM until noon" -> [10, 11]
     * "2 PM until 4 PM" -> [14, 15]

3. APPLIES & ADJUSTMENT CONVENTION:
   - For "no_op": "applies" must be false, "structured_adjustment" must be null.
   - For any other directive: "applies" must be true, "structured_adjustment" must contain the required fields.

4. OUTPUT FORMAT:
   Return a JSON array containing exactly one entry per operator note in note_index order:
   [
     {
       "note_index": 0,
       "applies": true,
       "directive_type": "solar_reduction",
       "structured_adjustment": {"hours": [12, 13], "factor": 0.25},
       "explanation": "Brief explanation"
     },
     {
       "note_index": 1,
       "applies": false,
       "directive_type": "no_op",
       "structured_adjustment": null,
       "explanation": "Brief explanation"
     }
   ]
"""


def build_interpretation_prompt(
    operator_notes: List[str],
    battery_info: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Constructs the user prompt for operator note interpretation.
    """
    notes_formatted = "\n".join([f"Note {idx}: \"{note}\"" for idx, note in enumerate(operator_notes)])
    battery_ctx = ""
    if battery_info:
        battery_ctx = (
            f"Context: Battery Capacity = {battery_info.get('capacity_kwh')} kWh, "
            f"Base Minimum Reserve = {battery_info.get('minimum_energy_kwh')} kWh.\n"
        )

    prompt = (
        f"{battery_ctx}Please interpret the following {len(operator_notes)} operator note(s) into structured directives:\n\n"
        f"{notes_formatted}\n\n"
        f"Return ONLY the JSON array matching the required specification."
    )
    return prompt
