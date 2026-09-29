import logging
from fastapi import APIRouter, HTTPException, status
from app.models.request import ScenarioRequest
from app.models.response import HealthResponse, ScenarioResponse
from app.llm.client import LLMClient
from app.optimizer.solver import EnergyOptimizer, InfeasibleScheduleError
from app.energy.replay import replay_and_validate_plan

logger = logging.getLogger(__name__)
router = APIRouter()

llm_client = LLMClient()


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Service Readiness Probe",
)
async def health_check() -> HealthResponse:
    """
    Returns HTTP 200 with status='ok' when the service is ready.
    """
    return HealthResponse(status="ok")


@router.post(
    "/optimize-energy",
    response_model=ScenarioResponse,
    status_code=status.HTTP_200_OK,
    summary="LLM-Assisted Smart Campus Energy Optimizer",
)
async def optimize_energy(request: ScenarioRequest) -> ScenarioResponse:
    """
    End-to-End Pipeline:
      1. Interpret operator notes via LLM with structured prompts.
      2. Apply deterministic guardrails to sanitize & bound directives.
      3. Solve cost-minimizing Linear Program via SciPy HiGHS.
      4. Replay and verify all energy, battery, and directive constraints.
      5. Construct and return canonical response payload.
    """
    try:
        # Step 1 & 2: LLM Interpretation & Guardrails
        validated_directives = await llm_client.interpret_operator_notes(
            notes=request.operator_notes,
            battery_info=request.battery.model_dump(),
        )

        # Step 3: Mathematical Optimization
        try:
            hourly_plan = EnergyOptimizer.solve(
                request=request,
                directives=validated_directives,
            )
        except InfeasibleScheduleError as inf_err:
            logger.warning("Infeasible scenario %s: %s", request.scenario_id, inf_err)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Infeasible scenario: {str(inf_err)}",
            )

        # Step 4: Replay & Validation
        is_valid, violations, metrics = replay_and_validate_plan(
            plan=hourly_plan,
            request=request,
            directives=validated_directives,
        )

        if not is_valid:
            logger.error("Schedule verification failed for %s: %s", request.scenario_id, violations)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Schedule verification failed internal energy constraints.",
            )

        # Step 5: Construct Canonical Summary & Response
        applied_types = [d.directive_type.value for d in validated_directives if d.applies]
        summary = (
            f"24-hour schedule successfully optimized for scenario {request.scenario_id}. "
            f"Applied {len(applied_types)} active operator directive(s) ({', '.join(applied_types) if applied_types else 'none'}). "
            f"Total grid import: {metrics['total_grid_kwh']} kWh, total cost: {metrics['total_cost_bdt']} BDT, peak grid: {metrics['peak_grid_kwh']} kWh."
        )

        return ScenarioResponse(
            scenario_id=request.scenario_id,
            directive_interpretation=validated_directives,
            hourly_plan=hourly_plan,
            total_grid_kwh=metrics["total_grid_kwh"],
            total_cost_bdt=metrics["total_cost_bdt"],
            peak_grid_kwh=metrics["peak_grid_kwh"],
            plan_summary=summary,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Unhandled error processing scenario %s: %s", request.scenario_id, exc, exc_info=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred while computing the energy schedule.",
        )
