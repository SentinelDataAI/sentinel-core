"""
Integration Tests — API and agent interfaces (mocked engine).

Public Evaluation Build: Tests prove test coverage and API contract.
Core engine is mocked; no proprietary logic executed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Import app from api (path may vary by run context)
try:
    from src.api.main import app
except ImportError:
    from api.main import app


client = TestClient(app)


# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------


def test_health_returns_ok():
    """Health endpoint returns status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_root_returns_service_info():
    """Root returns service name and links."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "Sentinel API"
    assert "health" in data
    assert "validate" in data
    assert "optimize" in data


# -----------------------------------------------------------------------------
# Validate (mocked policy enforcer)
# -----------------------------------------------------------------------------


@patch("src.api.main.get_policy_enforcer")
def test_validate_accepts_sql_and_returns_verdict(mock_get_enforcer):
    """POST /v1/validate accepts SQL and returns allowed/reason."""
    mock_verdict = MagicMock()
    mock_verdict.allowed = True
    mock_verdict.reason = "Mocked for Public Demo"
    mock_verdict.rule_id = None
    mock_verdict.suggested_rewrite = None
    mock_verdict.risk_score = None

    mock_enforcer = MagicMock()
    mock_enforcer.validate_query.return_value = mock_verdict
    mock_get_enforcer.return_value = mock_enforcer

    response = client.post(
        "/v1/validate",
        json={"sql": "SELECT * FROM users WHERE id = 1"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["allowed"] is True
    assert "reason" in data
    assert "latency_ms" in data

    mock_enforcer.validate_query.assert_called_once()
    call_kwargs = mock_enforcer.validate_query.call_args[1]
    assert call_kwargs["sql"] == "SELECT * FROM users WHERE id = 1"


def test_validate_returns_structured_response_without_mock():
    """Validate endpoint returns valid schema (public build uses mocked enforcer)."""
    response = client.post(
        "/v1/validate",
        json={"sql": "SELECT 1", "session_id": "test-session"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "allowed" in data
    assert "reason" in data
    assert isinstance(data["allowed"], bool)
    assert isinstance(data["reason"], str)


# -----------------------------------------------------------------------------
# Optimize (mocked optimizer)
# -----------------------------------------------------------------------------


@patch("src.api.main.get_optimizer")
def test_optimize_accepts_sql_and_returns_rewrite_result(mock_get_optimizer):
    """POST /v1/optimize accepts SQL and returns rewrite result."""
    mock_result = MagicMock()
    mock_result.success = False
    mock_result.rewritten_sql = None
    mock_result.reason = "Mocked for Public Demo"
    mock_result.changes = []
    mock_result.original_sql = "DELETE FROM logs"

    mock_opt = MagicMock()
    mock_opt.rewrite_query.return_value = mock_result
    mock_get_optimizer.return_value = mock_opt

    response = client.post(
        "/v1/optimize",
        json={"sql": "DELETE FROM logs", "rule_id": "GOV-101"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["original_sql"] == "DELETE FROM logs"
    assert "reason" in data
    assert "changes" in data

    mock_opt.rewrite_query.assert_called_once()
    call_kwargs = mock_opt.rewrite_query.call_args[1]
    assert call_kwargs["sql"] == "DELETE FROM logs"
    assert call_kwargs["rule_id"] == "GOV-101"


def test_optimize_returns_structured_response_without_mock():
    """Optimize endpoint returns valid schema."""
    response = client.post(
        "/v1/optimize",
        json={"sql": "DELETE FROM temp"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "success" in data
    assert "reason" in data
    assert "original_sql" in data
    assert "changes" in data


# -----------------------------------------------------------------------------
# Agent interfaces (no mocks — public build returns mocked data)
# -----------------------------------------------------------------------------


def test_policy_enforcer_validate_returns_verdict():
    """PolicyEnforcer.validate_query returns PolicyVerdict."""
    try:
        from src.agents.policy_enforcer import PolicyEnforcer
    except ImportError:
        from agents.policy_enforcer import PolicyEnforcer

    enforcer = PolicyEnforcer()
    verdict = enforcer.validate_query("SELECT 1")
    assert verdict.allowed is True
    assert "reason" in verdict.reason


def test_optimizer_rewrite_query_returns_rewrite_result():
    """Optimizer.rewrite_query returns RewriteResult."""
    try:
        from src.agents.optimizer import Optimizer
    except ImportError:
        from agents.optimizer import Optimizer

    opt = Optimizer()
    result = opt.rewrite_query("DELETE FROM x")
    assert result.original_sql == "DELETE FROM x"
    assert isinstance(result.success, bool)
    assert isinstance(result.reason, str)
