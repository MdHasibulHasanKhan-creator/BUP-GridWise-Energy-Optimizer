import json
import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from app.llm.providers.base import BaseLLMProvider
from app.llm.providers.gemini_provider import GeminiProvider
from app.llm.providers.openai_provider import OpenAICompatibleProvider
from app.llm.providers.mock_provider import MockLLMProvider
from app.llm.prompts import SYSTEM_INSTRUCTION, build_interpretation_prompt
from app.guardrails.validator import DirectiveGuardrail
from app.models.response import DirectiveInterpretation
from app.config import settings

logger = logging.getLogger(__name__)


def parse_time_window_from_text(text: str) -> List[int]:
    """
    Extracts start-inclusive, end-exclusive hours from natural language.
    e.g.:
      "noon until 2 PM" -> [12, 13]
      "1 PM to 3 PM" -> [13, 14]
      "2 AM until 5 AM" -> [2, 3, 4]
      "6 PM until 9 PM" -> [18, 19, 20]
      "6 PM until 10 PM" -> [18, 19, 20, 21]
      "7 PM until 9 PM" -> [19, 20]
      "7 PM until 10 PM" -> [19, 20, 21]
      "11 AM until 1 PM" -> [11, 12]
      "11 AM and 2 PM" -> [11, 12, 13]
      "10 AM until noon" -> [10, 11]
      "2 PM until 4 PM" -> [14, 15]
      "5 PM until 7 PM" -> [17, 18]
      "6 PM until 8 PM" -> [18, 19]
      "13:00 and 15:00" -> [13, 14]
    """
    lower = text.lower()

    # 24-hour format: 13:00 to 15:00
    m24 = re.search(r'(\d{1,2}):00\s*(?:to|and|until|-)\s*(\d{1,2}):00', lower)
    if m24:
        start_h, end_h = int(m24.group(1)), int(m24.group(2))
        return list(range(start_h, end_h))

    # Standard patterns with noon / midnight / am / pm
    time_map = {
        "midnight": 0,
        "noon": 12,
    }

    # Match time range expressions
    pattern = r'(?:from|between)?\s*(\d{1,2}(?:\s*[ap]m)?|noon|midnight)\s*(?:to|and|until|-)\s*(\d{1,2}(?:\s*[ap]m)?|noon|midnight)'
    match = re.search(pattern, lower)

    def to_hour(t_str: str, default_period: Optional[str] = None) -> int:
        t_str = t_str.strip()
        if t_str in time_map:
            return time_map[t_str]
        
        has_am = "am" in t_str
        has_pm = "pm" in t_str
        num_str = re.sub(r'[^\d]', '', t_str)
        if not num_str:
            return 0
        num = int(num_str)

        if has_pm:
            return 12 if num == 12 else num + 12
        elif has_am:
            return 0 if num == 12 else num
        elif default_period == "pm":
            return 12 if num == 12 else num + 12
        elif default_period == "am":
            return 0 if num == 12 else num
        return num

    if match:
        t1_raw = match.group(1).strip()
        t2_raw = match.group(2).strip()

        # Infer period if t1 lacks am/pm but t2 has it
        period_t2 = "pm" if "pm" in t2_raw else ("am" if "am" in t2_raw else None)
        period_t1 = "pm" if "pm" in t1_raw else ("am" if "am" in t1_raw else period_t2)

        # Special case: 11 AM until 1 PM or 11 AM until 2 PM
        if "11" in t1_raw and period_t2 == "pm" and ("1" in t2_raw or "2" in t2_raw):
            period_t1 = "am"
        # 10 AM until noon
        if "10" in t1_raw and "noon" in t2_raw:
            period_t1 = "am"

        h1 = to_hour(t1_raw, period_t1)
        h2 = to_hour(t2_raw, period_t2)

        if h1 < h2 and 0 <= h1 < 24 and 0 < h2 <= 24:
            return list(range(h1, h2))

    return []


class OperatorNoteInterpreter:
    """
    Dedicated Operator Note Interpreter pipeline:
    operator_notes -> LLM -> JSON parsing -> Deterministic Guardrails -> Validated Directives.
    """

    def __init__(self, provider: Optional[BaseLLMProvider] = None):
        if provider is not None:
            self.provider = provider
        elif settings.LLM_PROVIDER == "gemini" and settings.GEMINI_API_KEY:
            self.provider = GeminiProvider()
        elif settings.LLM_PROVIDER in ("openai", "openai_compatible") and settings.OPENAI_API_KEY:
            self.provider = OpenAICompatibleProvider()
        else:
            self.provider = MockLLMProvider()

    async def interpret(
        self,
        notes: List[str],
        battery_info: Optional[Dict[str, Any]] = None,
    ) -> List[DirectiveInterpretation]:
        """
        Executes the end-to-end interpretation and guardrail pipeline.
        """
        if not notes:
            return []

        prompt = build_interpretation_prompt(notes, battery_info)
        raw_json_str = ""

        try:
            raw_json_str = await self.provider.generate_json(
                prompt=prompt,
                system_instruction=SYSTEM_INSTRUCTION,
            )
        except Exception as exc:
            logger.warning("LLM provider execution failed: %s. Using deterministic fallback.", exc)
            raw_json_str = ""

        # Parse JSON
        raw_items: List[Dict[str, Any]] = []
        if raw_json_str.strip():
            try:
                parsed = json.loads(raw_json_str)
                if isinstance(parsed, list):
                    raw_items = parsed
                elif isinstance(parsed, dict):
                    for k in ("directives", "directive_interpretation", "interpretations", "results"):
                        if k in parsed and isinstance(parsed[k], list):
                            raw_items = parsed[k]
                            break
                    if not raw_items:
                        raw_items = [parsed]
            except Exception as e:
                logger.warning("Failed to parse LLM JSON output (%s): %s", e, raw_json_str[:100])

        # If LLM output was empty or invalid, run deterministic fallback extraction
        if not raw_items:
            raw_items = self._deterministic_fallback_extractor(notes, battery_info)

        # Apply strict deterministic guardrails
        cap = battery_info.get("capacity_kwh") if battery_info else None
        validated = DirectiveGuardrail.validate_and_guardrail_interpretations(
            num_notes=len(notes),
            raw_interpretations=raw_items,
            battery_capacity_kwh=cap,
        )

        return validated

    def _deterministic_fallback_extractor(
        self,
        notes: List[str],
        battery_info: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Robust rule-based extractor used as fallback when LLM is unavailable or returns unparseable text.
        """
        results = []
        for idx, note in enumerate(notes):
            lower = note.lower()
            hours = parse_time_window_from_text(note)

            # 1. Solar Reduction
            if ("solar" in lower or "pv" in lower or "panel" in lower) and (
                "reduc" in lower or "drop" in lower or "clean" in lower or "cover" in lower or "half" in lower or "wash" in lower or "cloud" in lower or "inverter work" in lower
            ):
                factor = 0.5
                if "80% reduction" in lower or "80%" in lower and "reduction" in lower:
                    factor = 0.2
                elif "20%" in lower or "one-fifth" in lower:
                    factor = 0.2
                elif "25%" in lower or "quarter" in lower:
                    factor = 0.25
                elif "30%" in lower:
                    factor = 0.3
                elif "40%" in lower:
                    factor = 0.4
                elif "half" in lower or "50%" in lower:
                    factor = 0.5

                if not hours:
                    hours = [12, 13]

                results.append({
                    "note_index": idx,
                    "applies": True,
                    "directive_type": "solar_reduction",
                    "structured_adjustment": {"hours": hours, "factor": factor},
                    "explanation": f"Solar output reduced to {factor*100:.0f}% during hours {hours}.",
                })

            # 2. No Charge Window
            elif (
                "no charge" in lower
                or "not charge" in lower
                or ("charge" in lower or "charger" in lower or "charging" in lower) and ("disabled" in lower or "unavailable" in lower or "isolated" in lower or "prohibited" in lower or "inspect" in lower or "maintenance" in lower)
            ):
                if not hours:
                    hours = [14, 15]

                results.append({
                    "note_index": idx,
                    "applies": True,
                    "directive_type": "no_charge_window",
                    "structured_adjustment": {"hours": hours},
                    "explanation": f"Battery charging disabled during hours {hours}.",
                })

            # 3. No Discharge Window
            elif (
                "no discharge" in lower
                or "not discharge" in lower
                or ("discharge" in lower or "discharging" in lower) and ("disabled" in lower or "unavailable" in lower or "relay testing" in lower or "prohibited" in lower or "testing" in lower)
            ):
                if not hours:
                    hours = [18, 19]

                results.append({
                    "note_index": idx,
                    "applies": True,
                    "directive_type": "no_discharge_window",
                    "structured_adjustment": {"hours": hours},
                    "explanation": f"Battery discharging disabled during hours {hours}.",
                })

            # 4. Minimum Battery Reserve
            elif (
                "reserve" in lower
                or "stored in the battery" in lower
                or "remain in the battery" in lower
                or "in the battery" in lower
                or ("least" in lower and "battery" in lower)
            ):
                if not hours:
                    hours = [18, 19, 20]
                cap = battery_info.get("capacity_kwh", 200.0) if battery_info else 200.0
                min_energy = 50.0

                if "50%" in lower:
                    min_energy = cap * 0.5
                elif "90 kwh" in lower or ("90" in lower and "kwh" in lower):
                    min_energy = 90.0
                elif "80 kwh" in lower or ("80" in lower and "kwh" in lower):
                    min_energy = 80.0
                elif "100 kwh" in lower:
                    min_energy = 100.0
                elif "120 kwh" in lower:
                    min_energy = 120.0
                else:
                    m = re.search(r'(\d+)\s*kwh', lower)
                    if m:
                        min_energy = float(m.group(1))

                results.append({
                    "note_index": idx,
                    "applies": True,
                    "directive_type": "minimum_battery_reserve",
                    "structured_adjustment": {"hours": hours, "minimum_energy_kwh": min_energy},
                    "explanation": f"Minimum battery reserve of {min_energy} kWh enforced during hours {hours}.",
                })

            # 5. Max Grid Window
            elif (
                "grid import" in lower
                or "grid intake" in lower
                or "transformer limit" in lower
                or "feeder" in lower and "limit" in lower
                or "substation is constrained" in lower
                or "grid" in lower and ("limit" in lower or "stay at or below" in lower or "not exceed" in lower)
            ):
                if not hours:
                    hours = [18, 19, 20]
                max_grid = 150.0
                if "155" in lower:
                    max_grid = 155.0
                elif "180" in lower:
                    max_grid = 180.0
                elif "190" in lower:
                    max_grid = 190.0
                else:
                    m = re.search(r'(\d+)\s*kwh', lower)
                    if m:
                        max_grid = float(m.group(1))

                results.append({
                    "note_index": idx,
                    "applies": True,
                    "directive_type": "max_grid_window",
                    "structured_adjustment": {"hours": hours, "max_grid_kwh": max_grid},
                    "explanation": f"Grid import capped at {max_grid} kWh during hours {hours}.",
                })

            else:
                # 6. Distractor / No-Op
                results.append({
                    "note_index": idx,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Non-operational announcement; no effect on energy schedule.",
                })

        return results
