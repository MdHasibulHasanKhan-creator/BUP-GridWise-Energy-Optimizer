import logging
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from app.config import settings
from app.api.routes import router

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("gridwise")

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    docs_url="/docs" if settings.APP_ENV != "production" else None,
    redoc_url="/redoc" if settings.APP_ENV != "production" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _format_errors(raw_errors):
    formatted = []
    for err in raw_errors:
        loc = err.get("loc", ())
        msg = err.get("msg", "Invalid value")
        err_type = err.get("type", "value_error")
        formatted.append({"loc": [str(x) for x in loc], "msg": str(msg), "type": str(err_type)})
    return formatted


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Handle malformed JSON / request structure errors strictly with HTTP 400.
    """
    formatted_errors = _format_errors(exc.errors())
    logger.warning("Request validation failed: %s", formatted_errors)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "Malformed JSON or structurally invalid request.", "errors": formatted_errors},
    )


@app.exception_handler(ValidationError)
async def pydantic_validation_exception_handler(request: Request, exc: ValidationError):
    """
    Handle Pydantic model validation errors with HTTP 400.
    """
    formatted_errors = _format_errors(exc.errors())
    logger.warning("Pydantic validation error: %s", formatted_errors)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "Invalid request parameters.", "errors": formatted_errors},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Controlled 500 error handler that never leaks secrets, paths, or tracebacks.
    """
    logger.error("Unhandled exception processing request: %s", str(exc), exc_info=False)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error occurred while processing the energy schedule."},
    )


app.include_router(router)
