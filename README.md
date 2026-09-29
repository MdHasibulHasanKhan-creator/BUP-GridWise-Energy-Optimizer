# BUP GridWise Energy Optimizer

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![SciPy HiGHS](https://img.shields.io/badge/Solver-SciPy%20HiGHS-orange.svg)](https://scipy.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)

Production-grade LLM-Assisted Smart Campus Energy Scheduling and Optimization service built for the **BUP CSE Fest 2026 Hackathon (Preliminary Round)**.

---

## 1. Project Overview

The service receives a 24-hour campus energy forecast (demand, solar generation, and time-varying grid tariff) alongside 1–3 natural-language operator notes. It performs:
1. **Natural-Language Interpretation**: Extracts structured machine-checkable operational directives via Generative LLM.
2. **Deterministic Guardrails**: Validates, sanitizes, and bounds all directives before optimization.
3. **Continuous Linear Optimization**: Solves the exact cost-minimizing dispatch schedule using SciPy HiGHS simplex/interior-point solver ($< 5\text{ms}$).
4. **Independent Energy Replay**: Verifies all physical and directive constraints (energy balance, rate limits, active reserves, and end-of-day neutrality).
5. **Canonical API Response**: Returns validated directive interpretations, 24-hour hourly schedule, and recalculated totals.

---

## 2. System Architecture

```
                                      ┌─────────────────────────────────┐
                                      │       FastAPI Web Server        │
                                      │   GET /health, POST /optimize   │
                                      └────────────────┬────────────────┘
                                                       │
                                                       ▼
                                      ┌─────────────────────────────────┐
                                      │         Request Parsing         │
                                      │     (Pydantic V2 Validation)    │
                                      └────────────────┬────────────────┘
                                                       │
                                                       ▼
                                      ┌─────────────────────────────────┐
                                      │      LLM Directive Extractor    │
                                      │ (Gemini / OpenAI / Fallback)    │
                                      └────────────────┬────────────────┘
                                                       │
                                                       ▼
                                      ┌─────────────────────────────────┐
                                      │     Deterministic Guardrails    │
                                      │ (Enum check, hour sorting, etc) │
                                      └────────────────┬────────────────┘
                                                       │
                                                       ▼
                                      ┌─────────────────────────────────┐
                                      │      SciPy HiGHS LP Solver      │
                                      │   (Exact Cost Minimization)     │
                                      └────────────────┬────────────────┘
                                                       │
                                                       ▼
                                      ┌─────────────────────────────────┐
                                      │  Replay & Consistency Validator │
                                      │  (Energy balance & Neutrality)  │
                                      └────────────────┬────────────────┘
                                                       │
                                                       ▼
                                      ┌─────────────────────────────────┐
                                      │      Canonical JSON Response    │
                                      └─────────────────────────────────┘
```

---

## 3. Directory Structure

```
.
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app, middleware, centralized exception handling
│   ├── config.py                   # Pydantic environment configuration
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py               # GET /health, POST /optimize-energy
│   ├── models/
│   │   ├── __init__.py
│   │   ├── directives.py           # Structured adjustments & DirectiveType enum
│   │   ├── request.py              # ScenarioRequest, HourInput, BatteryInput
│   │   └── response.py             # ScenarioResponse, HourlyPlanEntry, DirectiveInterpretation
│   ├── guardrails/
│   │   ├── __init__.py
│   │   ├── validator.py            # DirectiveGuardrail sanitizer & safe fallback
│   │   └── constraints.py          # ScenarioConstraints compiler
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py               # LLMClient interface
│   │   ├── interpreter.py          # OperatorNoteInterpreter pipeline
│   │   ├── prompts.py              # Constrained system prompts & schema definitions
│   │   └── providers/              # Abstract LLM provider layer
│   │       ├── base.py             # BaseLLMProvider
│   │       ├── gemini_provider.py  # Google Gemini REST client
│   │       ├── openai_provider.py  # OpenAI/Groq compatible client
│   │       └── mock_provider.py    # Zero-network mock provider
│   ├── energy/
│   │   ├── __init__.py
│   │   ├── balance.py              # Solar, battery reserve, and grid cap calculations
│   │   ├── battery.py              # Deterministic single-hour BatterySimulator
│   │   ├── simulation.py           # 24-hour deterministic simulation engine
│   │   └── replay.py               # Replay verifier and metric recalculator
│   └── optimizer/
│       ├── __init__.py
│       └── solver.py               # High-speed SciPy HiGHS LP Optimizer
├── docs/                           # Official competition problem statement & sample pack
├── tests/                          # 59 automated unit, integration, edge, and E2E tests
│   ├── __init__.py
│   ├── test_api.py                 # Endpoint and schema tests
│   ├── test_energy_model.py        # Energy balance, efficiency, and neutrality tests
│   ├── test_interpreter_and_guardrails.py # LLM & guardrails tests
│   ├── test_hidden_edge_cases.py   # Adversarial & edge case test suite
│   ├── test_e2e_api.py             # End-to-end API test over all 10 sample cases
│   └── benchmark.py                # Performance & latency profiling harness
├── Dockerfile                      # Production slim multi-stage Docker container
├── .dockerignore
├── .env.example
├── requirements.txt
└── README.md
```

---

## 4. Local Quickstart (Clean Environment)

### Prerequisites
- Python 3.11+ or `uv`

### Installation
```bash
# 1. Clone repository
git clone <repo-url>
cd BUP-GridWise-Energy-Optimizer

# 2. Setup Virtual Environment
uv venv --python 3.12 .venv
source .venv/bin/activate       # On Windows: .venv\Scripts\activate

# 3. Install Dependencies
uv pip install -r requirements.txt
```

### Running the API Server
```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```
API will be live at `http://localhost:8000`.

---

## 5. Environment Variables Configuration

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|---|---|---|
| `HOST` | Bind host address | `0.0.0.0` |
| `PORT` | Service port | `8000` |
| `APP_ENV` | Application environment (`development` / `production`) | `development` |
| `LOG_LEVEL` | Logging verbosity (`INFO`, `DEBUG`, `WARNING`) | `INFO` |
| `LLM_PROVIDER` | Active LLM engine (`gemini`, `openai`, `openai_compatible`) | `gemini` |
| `GEMINI_API_KEY` | Google Gemini API key | `""` |
| `GEMINI_MODEL` | Gemini model name | `gemini-2.5-flash` |
| `OPENAI_API_KEY` | OpenAI / Groq API key | `""` |
| `OPENAI_BASE_URL`| Custom base URL (e.g. for Groq or OpenRouter) | `https://api.openai.com/v1` |
| `OPENAI_MODEL` | OpenAI compatible model name | `llama-3.3-70b-versatile` |
| `LLM_TIMEOUT_SECONDS` | Maximum network timeout for LLM calls | `8.0` |

*Note: If no API key is provided, the service automatically utilizes its deterministic fallback interpreter, ensuring 100% test passing and offline functionality.*

---

## 6. Docker Deployment

### Build Docker Image
```bash
docker build -t gridwise-optimizer:latest .
```

### Run Docker Container
```bash
docker run -d -p 8000:8000 \
  -e GEMINI_API_KEY="your-api-key" \
  --name gridwise-service \
  gridwise-optimizer:latest
```

---

## 7. Running the Automated Test Suite

Run all 59 tests across all test suites:

```bash
uv run pytest -v
```

### Running the Performance Benchmark
```bash
uv run python tests/benchmark.py
```

---

## 8. API Specification & Sample Curl Requests

### `GET /health`
- **Response**: `200 OK`
```json
{
  "status": "ok"
}
```

### `POST /optimize-energy`
- **Headers**: `Content-Type: application/json`
- **Sample Request**:
```bash
curl -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d '{
    "scenario_id": "SAMPLE-01",
    "operator_notes": [
      "Facilities will wash the rooftop solar panels from noon until 2 PM. During cleaning, usable solar should be treated as roughly 25% of the forecast.",
      "The sports office moved next month'\''s registration deadline."
    ],
    "hours": [
      {"hour": 0, "demand_kwh": 90, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
      {"hour": 1, "demand_kwh": 85, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
      {"hour": 2, "demand_kwh": 80, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
      {"hour": 3, "demand_kwh": 80, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
      {"hour": 4, "demand_kwh": 85, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
      {"hour": 5, "demand_kwh": 95, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
      {"hour": 6, "demand_kwh": 110, "solar_kwh": 5, "tariff_bdt_per_kwh": 8},
      {"hour": 7, "demand_kwh": 130, "solar_kwh": 20, "tariff_bdt_per_kwh": 10},
      {"hour": 8, "demand_kwh": 150, "solar_kwh": 50, "tariff_bdt_per_kwh": 12},
      {"hour": 9, "demand_kwh": 165, "solar_kwh": 90, "tariff_bdt_per_kwh": 14},
      {"hour": 10, "demand_kwh": 175, "solar_kwh": 130, "tariff_bdt_per_kwh": 16},
      {"hour": 11, "demand_kwh": 180, "solar_kwh": 160, "tariff_bdt_per_kwh": 16},
      {"hour": 12, "demand_kwh": 185, "solar_kwh": 180, "tariff_bdt_per_kwh": 15},
      {"hour": 13, "demand_kwh": 180, "solar_kwh": 170, "tariff_bdt_per_kwh": 14},
      {"hour": 14, "demand_kwh": 175, "solar_kwh": 140, "tariff_bdt_per_kwh": 14},
      {"hour": 15, "demand_kwh": 160, "solar_kwh": 100, "tariff_bdt_per_kwh": 15},
      {"hour": 16, "demand_kwh": 150, "solar_kwh": 60, "tariff_bdt_per_kwh": 17},
      {"hour": 17, "demand_kwh": 155, "solar_kwh": 25, "tariff_bdt_per_kwh": 19},
      {"hour": 18, "demand_kwh": 170, "solar_kwh": 5, "tariff_bdt_per_kwh": 20},
      {"hour": 19, "demand_kwh": 180, "solar_kwh": 0, "tariff_bdt_per_kwh": 20},
      {"hour": 20, "demand_kwh": 175, "solar_kwh": 0, "tariff_bdt_per_kwh": 18},
      {"hour": 21, "demand_kwh": 160, "solar_kwh": 0, "tariff_bdt_per_kwh": 14},
      {"hour": 22, "demand_kwh": 130, "solar_kwh": 0, "tariff_bdt_per_kwh": 10},
      {"hour": 23, "demand_kwh": 105, "solar_kwh": 0, "tariff_bdt_per_kwh": 7}
    ],
    "battery": {
      "capacity_kwh": 300,
      "initial_energy_kwh": 120,
      "minimum_energy_kwh": 30,
      "max_charge_kwh_per_hour": 60,
      "max_discharge_kwh_per_hour": 60
    }
  }'
```

---

## 9. Performance & Benchmark Metrics

- **HiGHS LP Solver Latency**: Median $1.96\text{ ms}$, p95 $2.17\text{ ms}$
- **End-to-End API Pipeline Latency**: Median $6.53\text{ ms}$, p95 $8.13\text{ ms}$ (Official requirement: $\le 5000\text{ ms}$)
- **Memory Footprint**: $< 120\text{ MB}$
- **Secret Safety**: 0 secrets committed; API keys injected solely via process environment variables.
