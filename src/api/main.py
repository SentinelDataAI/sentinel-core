"""
Sentinel API — FastAPI application.

Public Evaluation Build: Full production-ready API surface.
Routes: /v1/validate, /v1/optimize, /health.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .models import (
    ErrorResponse,
    HealthResponse,
    OptimizeRequest,
    OptimizeResponse,
    ValidateRequest,
    ValidateResponse,
)

# Agents: reference interfaces (logic redacted in public build)
try:
    from src.agents.policy_enforcer import PolicyEnforcer
    from src.agents.optimizer import Optimizer
except ImportError:
    from agents.policy_enforcer import PolicyEnforcer
    from agents.optimizer import Optimizer

__version__ = "1.0.0-public"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    yield
    # Shutdown: close pools, flush audit, etc. (redacted in public build)


app = FastAPI(
    title="Sentinel API",
    description="Neuro-Symbolic Trust Layer for watsonx Orchestrate — Public Evaluation Build",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared agent instances (mocked in public build)
_policy_enforcer: Optional[PolicyEnforcer] = None
_optimizer: Optional[Optimizer] = None


def get_policy_enforcer() -> PolicyEnforcer:
    global _policy_enforcer
    if _policy_enforcer is None:
        _policy_enforcer = PolicyEnforcer()
    return _policy_enforcer


def get_optimizer() -> Optimizer:
    global _optimizer
    if _optimizer is None:
        _optimizer = Optimizer()
    return _optimizer


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health():
    """
    Health check endpoint for load balancers and monitoring.

    Returns status, version, and optional component health (Db2, Granite Guardian).
    """
    start = time.perf_counter()
    # In production: check Db2 pool, Granite Guardian endpoint (redacted)
    latency_ms = (time.perf_counter() - start) * 1000
    return HealthResponse(
        status="ok",
        version=__version__,
        db2_connected=None,
        guardian_available=None,
        latency_ms=round(latency_ms, 2),
    )


@app.post(
    "/v1/validate",
    response_model=ValidateResponse,
    responses={400: {"model": ErrorResponse, "description": "Bad request"}},
)
async def validate(request: ValidateRequest):
    """
    Validate a SQL query against policy and Granite Guardian.

    Returns whether the query is allowed, and if not, reason and optional suggested rewrite.
    """
    start = time.perf_counter()
    try:
        enforcer = get_policy_enforcer()
        verdict = enforcer.validate_query(
            sql=request.sql,
            session_id=request.session_id or "",
            context=request.context,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        return ValidateResponse(
            allowed=verdict.allowed,
            reason=verdict.reason,
            rule_id=verdict.rule_id,
            suggested_rewrite=verdict.suggested_rewrite,
            risk_score=verdict.risk_score,
            latency_ms=round(latency_ms, 2),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/v1/optimize",
    response_model=OptimizeResponse,
    responses={400: {"model": ErrorResponse, "description": "Bad request"}},
)
async def optimize(request: OptimizeRequest):
    """
    Attempt to rewrite a blocked or risky query into a safe alternative.

    Returns rewritten SQL (if success), reason, and list of changes applied.
    """
    try:
        opt = get_optimizer()
        result = opt.rewrite_query(
            sql=request.sql,
            rule_id=request.rule_id,
            context=request.context,
        )
        return OptimizeResponse(
            success=result.success,
            rewritten_sql=result.rewritten_sql,
            reason=result.reason,
            changes=result.changes,
            original_sql=result.original_sql,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    """Root redirect to docs."""
    return {
        "service": "Sentinel API",
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
        "validate": "POST /v1/validate",
        "optimize": "POST /v1/optimize",
    }
