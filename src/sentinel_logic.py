"""
Sentinel Core Logic — Neuro-Symbolic Handshake Layer.

This module implements the "fail-closed" governance layer that sits between
watsonx Orchestrate (LLM-generated SQL) and Db2 execution. It performs the
Neuro-Symbolic Handshake: the LLM's neural output is validated against
symbolic rules stored in Db2 before any query is executed.

Architecture flow:
  [User Prompt] -> [IBM Granite LLM] -> [Generated SQL]
       -> [SentinelGuard.validate_intent()] -> [Db2 Rules Lookup*]
       -> ALLOW | BLOCK | REWRITE (suggested_fix)

* In production, rule_set is fetched from Db2 via db2_connector.
  This implementation uses a mocked rule_set for hackathon demo.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SentinelAction(str, Enum):
    """Actions Sentinel can take after validating generated SQL."""

    ALLOW = "ALLOW"
    BLOCK_CRITICAL = "BLOCK_CRITICAL"
    INTERCEPT_REWRITE = "INTERCEPT_REWRITE"


@dataclass
class ValidationResult:
    """Structured result of Sentinel validation (Blocking Object when action is not ALLOW)."""

    allowed: bool
    action: SentinelAction
    rule_id: Optional[str] = None
    message: Optional[str] = None
    suggested_fix: Optional[str] = None
    raw_sql: Optional[str] = None


class SentinelGuard:
    """
    The core guard that performs the Neuro-Symbolic Handshake.

    Neuro-Symbolic Handshake (simplified):
    1. NEURAL: LLM (e.g. IBM Granite) produces SQL from natural language.
    2. SYMBOLIC: Sentinel compares the SQL against a rule_set (from Db2 SENTINEL_RULES).
    3. DECISION: If any rule matches, we BLOCK or REWRITE; otherwise ALLOW.

    In production, rule_set is loaded from Db2 via db2_connector.get_active_rules().
    Here we accept rule_set as a parameter to simulate that lookup for demo/unit tests.
    """

    def __init__(self, rule_set: Optional[list[dict]] = None):
        """
        Initialize the guard with a rule set.

        Args:
            rule_set: List of rule dicts with keys: rule_id, pattern, action.
                      If None, uses default demo rules (mocked Db2 response).
        """
        self._rule_set = rule_set or self._default_rules()

    def _default_rules(self) -> list[dict]:
        """
        Default rules matching governance_schema.sql inserts.
        Simulates the result of: SELECT rule_id, pattern, action FROM SENTINEL_RULES WHERE active = 1
        """
        return [
            {
                "rule_id": "GOV-404",
                "pattern": "DROP TABLE",
                "action": "BLOCK_CRITICAL",
                "description": "Destructive DDL — table drop forbidden",
            },
            {
                "rule_id": "GOV-101",
                "pattern": "DELETE",
                "action": "INTERCEPT_REWRITE",
                "description": "Bulk delete — suggest soft-delete rewrite",
            },
        ]

    def validate_intent(self, generated_sql: str, rule_set: Optional[list[dict]] = None) -> ValidationResult:
        """
        Validate LLM-generated SQL against the symbolic rule set.

        This is the main entry point for the Neuro-Symbolic Handshake:
        - generated_sql: The raw SQL produced by the LLM (neural output).
        - rule_set: Override for this call; if None, uses instance rule_set (from Db2 in prod).

        Returns a ValidationResult (Blocking Object when not ALLOW) with:
        - allowed: True only if no rule matched (safe to execute).
        - action: ALLOW | BLOCK_CRITICAL | INTERCEPT_REWRITE.
        - rule_id, message, suggested_fix: Set when action is not ALLOW.
        """
        rules = rule_set if rule_set is not None else self._rule_set
        sql_upper = (generated_sql or "").strip().upper()

        for rule in rules:
            pattern = (rule.get("pattern") or "").upper()
            if not pattern or pattern not in sql_upper:
                continue

            rule_id = rule.get("rule_id", "UNKNOWN")
            action_str = (rule.get("action") or "BLOCK_CRITICAL").upper()

            if "BLOCK" in action_str or action_str == "BLOCK_CRITICAL":
                return ValidationResult(
                    allowed=False,
                    action=SentinelAction.BLOCK_CRITICAL,
                    rule_id=rule_id,
                    message="Destructive Operation Detected",
                    suggested_fix=None,
                    raw_sql=generated_sql,
                )

            if "REWRITE" in action_str or action_str == "INTERCEPT_REWRITE":
                return ValidationResult(
                    allowed=False,
                    action=SentinelAction.INTERCEPT_REWRITE,
                    rule_id=rule_id,
                    message="Bulk delete intercepted; use soft-delete.",
                    suggested_fix="UPDATE target_table SET status = 'ARCHIVED', deleted_at = CURRENT_TIMESTAMP WHERE <your_conditions>",
                    raw_sql=generated_sql,
                )

        return ValidationResult(
            allowed=True,
            action=SentinelAction.ALLOW,
            raw_sql=generated_sql,
        )


def validate_sql(generated_sql: str, rule_set: Optional[list[dict]] = None) -> ValidationResult:
    """
    Convenience function: one-shot validation using default SentinelGuard.

    Args:
        generated_sql: SQL string from the LLM.
        rule_set: Optional override; if None, uses schema default rules.

    Returns:
        ValidationResult (Blocking Object when not ALLOW).
    """
    guard = SentinelGuard(rule_set=rule_set)
    return guard.validate_intent(generated_sql)
