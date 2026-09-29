import json
import pytest
from app.models.directives import (
    DirectiveType,
    SolarReductionAdjustment,
    MinimumBatteryReserveAdjustment,
    NoChargeWindowAdjustment,
    NoDischargeWindowAdjustment,
    MaxGridWindowAdjustment,
)
from app.models.response import DirectiveInterpretation
from app.models.request import ScenarioRequest, BatteryInput, HourInput
from app.guardrails.validator import DirectiveGuardrail
from app.guardrails.constraints import compile_scenario_constraints
from app.llm.interpreter import OperatorNoteInterpreter
from app.llm.providers.mock_provider import MockLLMProvider


@pytest.fixture
def sample_battery():
    return BatteryInput(
        capacity_kwh=300.0,
        initial_energy_kwh=120.0,
        minimum_energy_kwh=30.0,
        max_charge_kwh_per_hour=60.0,
        max_discharge_kwh_per_hour=60.0,
    )


@pytest.fixture
def sample_scenario_request(sample_battery):
    hours = [
        HourInput(
            hour=h,
            demand_kwh=100.0,
            solar_kwh=50.0 if 8 <= h <= 16 else 0.0,
            tariff_bdt_per_kwh=10.0 if 17 <= h <= 21 else 5.0,
        )
        for h in range(24)
    ]
    return ScenarioRequest(
        scenario_id="REQ-TEST-01",
        operator_notes=["Note 1", "Note 2"],
        hours=hours,
        battery=sample_battery,
    )


# A. Every official directive type
@pytest.mark.asyncio
async def test_all_official_directive_types_parsed():
    mock_json = json.dumps([
        {"note_index": 0, "applies": True, "directive_type": "solar_reduction", "structured_adjustment": {"hours": [12, 13], "factor": 0.25}, "explanation": "exp"},
        {"note_index": 1, "applies": True, "directive_type": "minimum_battery_reserve", "structured_adjustment": {"hours": [18, 19], "minimum_energy_kwh": 90.0}, "explanation": "exp"},
        {"note_index": 2, "applies": True, "directive_type": "no_charge_window", "structured_adjustment": {"hours": [2, 3, 4]}, "explanation": "exp"},
    ])
    interpreter = OperatorNoteInterpreter(provider=MockLLMProvider(mock_json))
    res = await interpreter.interpret(["note1", "note2", "note3"], {"capacity_kwh": 300})
    assert len(res) == 3
    assert res[0].directive_type == DirectiveType.SOLAR_REDUCTION
    assert res[1].directive_type == DirectiveType.MINIMUM_BATTERY_RESERVE
    assert res[2].directive_type == DirectiveType.NO_CHARGE_WINDOW


# B. Multiple natural-language phrasings for each directive (tested through fallback extractor)
@pytest.mark.asyncio
async def test_multiple_natural_language_phrasings():
    interpreter = OperatorNoteInterpreter(provider=MockLLMProvider(""))
    # Phrasing 1: 80% reduction in rooftop solar between 11 AM and 2 PM
    res1 = await interpreter.interpret(["Expect an 80% reduction in rooftop solar between 11 AM and 2 PM because of inverter work."])
    assert res1[0].directive_type == DirectiveType.SOLAR_REDUCTION
    assert res1[0].structured_adjustment["hours"] == [11, 12, 13]
    assert res1[0].structured_adjustment["factor"] == 0.2

    # Phrasing 2: PV production drop to 20% from 1 PM to 3 PM
    res2 = await interpreter.interpret(["Solar output will drop to about 20% from 1 PM to 3 PM."])
    assert res2[0].directive_type == DirectiveType.SOLAR_REDUCTION
    assert res2[0].structured_adjustment["hours"] == [13, 14]
    assert res2[0].structured_adjustment["factor"] == 0.2


# C. Valid structured LLM outputs
@pytest.mark.asyncio
async def test_valid_structured_output():
    mock_json = json.dumps([
        {"note_index": 0, "applies": True, "directive_type": "no_discharge_window", "structured_adjustment": {"hours": [18, 19]}, "explanation": "relay testing"}
    ])
    interpreter = OperatorNoteInterpreter(provider=MockLLMProvider(mock_json))
    res = await interpreter.interpret(["no discharge"], {"capacity_kwh": 300})
    assert len(res) == 1
    assert res[0].applies is True
    assert res[0].directive_type == DirectiveType.NO_DISCHARGE_WINDOW


# D. Invalid JSON from LLM (triggers safe fallback)
@pytest.mark.asyncio
async def test_invalid_json_from_llm():
    interpreter = OperatorNoteInterpreter(provider=MockLLMProvider("Invalid non-json response text"))
    res = await interpreter.interpret(["Do not charge the battery between 2 PM and 4 PM."])
    assert len(res) == 1
    assert res[0].directive_type == DirectiveType.NO_CHARGE_WINDOW
    assert res[0].structured_adjustment["hours"] == [14, 15]


# E. Missing fields in LLM output
def test_missing_fields_sanitization():
    # Missing structured_adjustment
    res = DirectiveGuardrail.sanitize_directive(
        note_index=0,
        raw_directive={"directive_type": "solar_reduction"},
    )
    assert res.applies is False
    assert res.directive_type == DirectiveType.NO_OP
    assert res.structured_adjustment is None


# F. Wrong field types
def test_wrong_field_types_sanitization():
    # String for factor and non-int in hours
    res = DirectiveGuardrail.sanitize_directive(
        note_index=0,
        raw_directive={"directive_type": "solar_reduction", "structured_adjustment": {"hours": ["12", "bad", 13], "factor": "0.4"}},
    )
    assert res.applies is True
    assert res.structured_adjustment["hours"] == [12, 13]
    assert res.structured_adjustment["factor"] == 0.4


# G. Unknown directive types
def test_unknown_directive_type():
    res = DirectiveGuardrail.sanitize_directive(
        note_index=0,
        raw_directive={"directive_type": "hyper_turbo_charge", "structured_adjustment": {"hours": [1, 2]}},
    )
    assert res.applies is False
    assert res.directive_type == DirectiveType.NO_OP
    assert res.structured_adjustment is None


# H. Invalid hour ranges (out of bounds 0..23, duplicates, unsorted)
def test_invalid_hour_ranges():
    assert DirectiveGuardrail.sanitize_hours([-5, 23, 24, 12, 12, 0]) == [0, 12, 23]
    assert DirectiveGuardrail.sanitize_hours([]) == []
    assert DirectiveGuardrail.sanitize_hours("not a list") == []


# I. Invalid parameter ranges (factor > 1.0 or < 0.0, reserve > capacity)
def test_invalid_parameter_ranges():
    res_factor = DirectiveGuardrail.sanitize_directive(
        note_index=0,
        raw_directive={"directive_type": "solar_reduction", "structured_adjustment": {"hours": [12], "factor": 2.5}},
    )
    assert res_factor.structured_adjustment["factor"] == 1.0

    res_res = DirectiveGuardrail.sanitize_directive(
        note_index=0,
        raw_directive={"directive_type": "minimum_battery_reserve", "structured_adjustment": {"hours": [18], "minimum_energy_kwh": 500.0}},
        battery_capacity_kwh=300.0,
    )
    assert res_res.structured_adjustment["minimum_energy_kwh"] == 300.0


# J. Boundary values (hours 0 and 23, factor 0.0 and 1.0)
def test_boundary_values():
    res = DirectiveGuardrail.sanitize_directive(
        note_index=0,
        raw_directive={"directive_type": "solar_reduction", "structured_adjustment": {"hours": [0, 23], "factor": 0.0}},
    )
    assert res.structured_adjustment["hours"] == [0, 23]
    assert res.structured_adjustment["factor"] == 0.0


# K. Multiple operator notes alignment (ensures 1:1 index alignment)
def test_multiple_notes_alignment():
    raw_list = [
        {"note_index": 1, "directive_type": "no_charge_window", "structured_adjustment": {"hours": [14, 15]}},
        {"note_index": 0, "directive_type": "no_op", "structured_adjustment": None},
    ]
    sanitized = DirectiveGuardrail.validate_and_guardrail_interpretations(
        num_notes=2,
        raw_interpretations=raw_list,
    )
    assert len(sanitized) == 2
    assert sanitized[0].note_index == 0
    assert sanitized[0].directive_type == DirectiveType.NO_OP
    assert sanitized[1].note_index == 1
    assert sanitized[1].directive_type == DirectiveType.NO_CHARGE_WINDOW


# L. Conflicting operator instructions (handled safely by guardrails)
def test_conflicting_charge_and_discharge_windows(sample_scenario_request):
    directives = [
        DirectiveInterpretation(note_index=0, applies=True, directive_type=DirectiveType.NO_CHARGE_WINDOW, structured_adjustment={"hours": [18, 19]}, explanation="no charge"),
        DirectiveInterpretation(note_index=1, applies=True, directive_type=DirectiveType.NO_DISCHARGE_WINDOW, structured_adjustment={"hours": [18, 19]}, explanation="no discharge"),
    ]
    constraints = compile_scenario_constraints(sample_scenario_request, directives)
    assert 18 in constraints.forbidden_charge_hours
    assert 18 in constraints.forbidden_discharge_hours


# M & N. Ambiguous notes and No-op behavior
@pytest.mark.asyncio
async def test_ambiguous_distractor_notes():
    interpreter = OperatorNoteInterpreter(provider=MockLLMProvider(""))
    res = await interpreter.interpret([
        "The cafeteria menu changes tomorrow.",
        "A seminar room booking was moved to next week.",
    ])
    assert len(res) == 2
    assert res[0].applies is False and res[0].directive_type == DirectiveType.NO_OP and res[0].structured_adjustment is None
    assert res[1].applies is False and res[1].directive_type == DirectiveType.NO_OP and res[1].structured_adjustment is None


# O. LLM unavailable/failure behavior (provider throwing exception)
class BrokenProvider(MockLLMProvider):
    async def generate_json(self, prompt, system_instruction, timeout_seconds=None):
        raise ConnectionError("Network unreachable")


@pytest.mark.asyncio
async def test_broken_provider_graceful_fallback():
    interpreter = OperatorNoteInterpreter(provider=BrokenProvider())
    res = await interpreter.interpret(["Do not charge the battery between 2 PM and 4 PM."])
    assert len(res) == 1
    assert res[0].applies is True
    assert res[0].directive_type == DirectiveType.NO_CHARGE_WINDOW
    assert res[0].structured_adjustment["hours"] == [14, 15]


# P. Deterministic guardrail behavior
def test_guardrail_guarantee():
    res = DirectiveGuardrail.validate_and_guardrail_interpretations(
        num_notes=3,
        raw_interpretations=[],
    )
    assert len(res) == 3
    for i in range(3):
        assert res[i].note_index == i
        assert res[i].directive_type == DirectiveType.NO_OP
        assert res[i].applies is False


# Q. Directive-to-constraint compilation
def test_directive_to_constraint_compilation(sample_scenario_request):
    directives = [
        DirectiveInterpretation(note_index=0, applies=True, directive_type=DirectiveType.SOLAR_REDUCTION, structured_adjustment={"hours": [12, 13], "factor": 0.5}, explanation="solar"),
        DirectiveInterpretation(note_index=1, applies=True, directive_type=DirectiveType.MAX_GRID_WINDOW, structured_adjustment={"hours": [18, 19], "max_grid_kwh": 120.0}, explanation="grid"),
    ]
    constraints = compile_scenario_constraints(sample_scenario_request, directives)
    # Hour 12 effective solar: 50.0 * 0.5 = 25.0
    assert constraints.effective_solar_kwh[12] == 25.0
    # Hour 18 max grid: 120.0
    assert constraints.max_grid_kwh_per_hour[18] == 120.0
    # Hour 0 max grid: inf
    assert constraints.max_grid_kwh_per_hour[0] == float("inf")


# Task 9: Public sample cases replay through interpreter + guardrail pipeline
@pytest.mark.asyncio
async def test_public_sample_cases_directive_extraction():
    data = json.load(open("docs/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json", encoding="utf-8"))
    interpreter = OperatorNoteInterpreter(provider=MockLLMProvider(""))

    for case in data["cases"]:
        cid = case["id"]
        notes = case["input"]["operator_notes"]
        bat = case["input"]["battery"]
        expected = case["expected_output"]["directive_interpretation"]

        extracted = await interpreter.interpret(notes, bat)
        assert len(extracted) == len(expected), f"Case {cid} length mismatch"

        for idx, (ext, exp) in enumerate(zip(extracted, expected)):
            assert ext.note_index == exp["note_index"], f"{cid} note {idx} index mismatch"
            assert ext.applies == exp["applies"], f"{cid} note {idx} applies mismatch"
            assert ext.directive_type == exp["directive_type"], f"{cid} note {idx} type mismatch"

            if exp["structured_adjustment"] is not None:
                assert ext.structured_adjustment is not None
                assert ext.structured_adjustment["hours"] == exp["structured_adjustment"]["hours"], f"{cid} hours mismatch"
                if "factor" in exp["structured_adjustment"]:
                    assert abs(ext.structured_adjustment["factor"] - exp["structured_adjustment"]["factor"]) <= 0.01
                if "minimum_energy_kwh" in exp["structured_adjustment"]:
                    assert abs(ext.structured_adjustment["minimum_energy_kwh"] - exp["structured_adjustment"]["minimum_energy_kwh"]) <= 0.01
                if "max_grid_kwh" in exp["structured_adjustment"]:
                    assert abs(ext.structured_adjustment["max_grid_kwh"] - exp["structured_adjustment"]["max_grid_kwh"]) <= 0.01
            else:
                assert ext.structured_adjustment is None
