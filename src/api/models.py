"""
Sentinel API — Pydantic Request/Response schemas.

Public Evaluation Build: Real schemas for validate, optimize, health.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# -----------------------------------------------------------------------------
# Validate
# -----------------------------------------------------------------------------


class ValidateRequest(BaseModel):
    """Request body for /v1/validate."""

    sql: str = Field(..., description="SQL query to validate")
    session_id: Optional[str] = Field(None, description="Session identifier for audit")
    context: Optional[dict[str, Any]] = Field(None, description="Optional request context")


class ValidateResponse(BaseModel):
    """Response body for /v1/validate."""

    allowed: bool = Field(..., description="Whether the query is allowed")
    reason: str = Field(..., description="Human-readable reason or policy message")
    rule_id: Optional[str] = Field(None, description="Matched rule ID if blocked/rewritten")
    suggested_rewrite: Optional[str] = Field(None, description="Safe alternative SQL if applicable")
    risk_score: Optional[float] = Field(None, ge=0, le=1, description="Risk score from Granite Guardian")
    latency_ms: Optional[float] = Field(None, description="Validation latency in milliseconds")


# -----------------------------------------------------------------------------
# Optimize
# -----------------------------------------------------------------------------


class OptimizeRequest(BaseModel):
    """Request body for /v1/optimize."""

    sql: str = Field(..., description="SQL query to optimize/rewrite")
    rule_id: Optional[str] = Field(None, description="Rule that triggered the intercept")
    context: Optional[dict[str, Any]] = Field(None, description="Optional context")


class OptimizeResponse(BaseModel):
    """Response body for /v1/optimize."""

    success: bool = Field(..., description="Whether a safe rewrite was produced")
    rewritten_sql: Optional[str] = Field(None, description="Safe alternative SQL")
    reason: str = Field(..., description="Explanation of the rewrite")
    changes: list[str] = Field(default_factory=list, description="List of changes applied")
    original_sql: str = Field(..., description="Original SQL that was rewritten")


# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """Response body for /health."""

    status: str = Field(..., description="Overall status: ok | degraded | error")
    version: str = Field(..., description="API version")
    db2_connected: Optional[bool] = Field(None, description="Db2 connectivity status")
    guardian_available: Optional[bool] = Field(None, description="Granite Guardian availability")
    latency_ms: Optional[float] = Field(None, description="Health check latency")


# -----------------------------------------------------------------------------
# Error
# -----------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str = Field(..., description="Error type or code")
    message: str = Field(..., description="Human-readable error message")
    detail: Optional[dict[str, Any]] = Field(None, description="Additional detail")
