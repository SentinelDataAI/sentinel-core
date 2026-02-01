"""
Sentinel Engine — Core Validation Pipeline.

This module orchestrates the neuro-symbolic validation flow:
    1. Receive Intent (raw SQL from watsonx Orchestrate)
    2. Check Cache (return cached verdict if available)
    3. Granite Guardian Validation (semantic risk assessment)
    4. Db2 Rules Lookup (pattern matching against SENTINEL_RULES)
    5. Emit Verdict (ALLOW | BLOCK | REWRITE)

Integrates with IBM Granite Guardian 3.0 for neural validation
and IBM Db2 for symbolic rule enforcement.

Built with IBM Project BOB.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Optional

from config.settings import get_settings
from .db2_manager import get_db2_manager, Db2QueryError

# Granite Guardian integration
try:
    from ibm_generative_ai.client import Client as GenAIClient
    from ibm_generative_ai.credentials import Credentials

    GENAI_AVAILABLE = True
except ImportError:
    GenAIClient = None  # type: ignore
    Credentials = None  # type: ignore
    GENAI_AVAILABLE = False

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Verdict Types
# -----------------------------------------------------------------------------


class VerdictType(str, Enum):
    """Possible outcomes of Sentinel validation."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    REWRITE = "REWRITE"


class RiskLevel(str, Enum):
    """Risk levels from Granite Guardian assessment."""

    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# -----------------------------------------------------------------------------
# Data Classes
# -----------------------------------------------------------------------------


@dataclass
class GraniteGuardianResult:
    """Result from Granite Guardian 3.0 semantic analysis."""

    risk_level: RiskLevel
    risk_score: float  # 0.0 - 1.0
    risk_categories: list[str]
    explanation: str
    latency_ms: float


@dataclass
class RuleMatch:
    """A matched rule from the SENTINEL_RULES table."""

    rule_id: str
    pattern: str
    action: str
    description: str


@dataclass
class Verdict:
    """
    Final verdict from Sentinel validation.

    Attributes:
        verdict_type: ALLOW, BLOCK, or REWRITE
        allowed: True only if verdict_type is ALLOW
        rule_id: ID of matched rule (if any)
        message: Human-readable explanation
        suggested_rewrite: Safe alternative SQL (for REWRITE verdicts)
        granite_result: Granite Guardian assessment details
        matched_rules: All rules that matched
        original_sql: The SQL that was validated
        session_id: Session identifier for audit correlation
        latency_ms: Total validation time in milliseconds
    """

    verdict_type: VerdictType
    allowed: bool
    rule_id: Optional[str] = None
    message: str = ""
    suggested_rewrite: Optional[str] = None
    granite_result: Optional[GraniteGuardianResult] = None
    matched_rules: list[RuleMatch] = field(default_factory=list)
    original_sql: str = ""
    session_id: str = ""
    latency_ms: float = 0.0


# -----------------------------------------------------------------------------
# Cache
# -----------------------------------------------------------------------------


class VerdictCache:
    """
    LRU cache for validation verdicts.

    Caches verdicts by SQL hash to avoid re-validating identical queries.
    Cache entries expire after TTL seconds.
    """

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 300):
        self._cache: dict[str, tuple[Verdict, float]] = {}
        self._max_size = max_size
        self._ttl = ttl_seconds

    def _hash_sql(self, sql: str) -> str:
        """Generate cache key from SQL."""
        normalized = " ".join(sql.strip().upper().split())
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def get(self, sql: str) -> Optional[Verdict]:
        """Retrieve cached verdict if exists and not expired."""
        key = self._hash_sql(sql)

        if key not in self._cache:
            return None

        verdict, timestamp = self._cache[key]

        if time.time() - timestamp > self._ttl:
            del self._cache[key]
            return None

        logger.debug(f"Cache hit for SQL hash {key}")
        return verdict

    def put(self, sql: str, verdict: Verdict) -> None:
        """Store verdict in cache."""
        # Evict oldest entries if at capacity
        if len(self._cache) >= self._max_size:
            oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]

        key = self._hash_sql(sql)
        self._cache[key] = (verdict, time.time())

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()


# -----------------------------------------------------------------------------
# Granite Guardian Interface
# -----------------------------------------------------------------------------


class GraniteGuardian:
    """
    Interface to IBM Granite Guardian 3.0 for semantic risk assessment.

    Granite Guardian analyzes SQL for:
    - Prompt injection attempts
    - Data exfiltration patterns
    - Destructive operations
    - Policy violations

    Note: Requires GRANITE_API_KEY and GRANITE_PROJECT_ID environment variables.
    """

    MODEL_ID = "ibm/granite-guardian-3.0-8b"

    def __init__(self):
        self._client: Optional[Any] = None
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Lazy initialization of GenAI client."""
        if self._initialized:
            return

        if not GENAI_AVAILABLE:
            logger.warning("ibm-generative-ai not installed; Granite Guardian disabled")
            self._initialized = True
            return

        settings = get_settings()

        if not settings.granite_api_key:
            logger.warning("GRANITE_API_KEY not set; Granite Guardian disabled")
            self._initialized = True
            return

        try:
            credentials = Credentials(
                api_key=settings.granite_api_key,
                api_endpoint=settings.granite_api_endpoint,
            )
            self._client = GenAIClient(credentials=credentials)
            logger.info("Granite Guardian 3.0 client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Granite Guardian: {e}")

        self._initialized = True

    def assess_risk(self, sql: str, context: Optional[str] = None) -> GraniteGuardianResult:
        """
        Assess semantic risk of SQL using Granite Guardian 3.0.

        Args:
            sql: SQL statement to analyze.
            context: Optional context about the request.

        Returns:
            GraniteGuardianResult with risk assessment.
        """
        self._ensure_initialized()
        start_time = time.time()

        # Fallback if client not available
        if self._client is None:
            return self._heuristic_assessment(sql, start_time)

        try:
            # Construct guardian prompt
            prompt = self._build_guardian_prompt(sql, context)

            # Call Granite Guardian
            response = self._client.generate(
                model_id=self.MODEL_ID,
                prompt=prompt,
                params={
                    "max_new_tokens": 256,
                    "temperature": 0.0,
                    "top_p": 1.0,
                },
            )

            # Parse response
            return self._parse_guardian_response(response, start_time)

        except Exception as e:
            logger.error(f"Granite Guardian call failed: {e}")
            return self._heuristic_assessment(sql, start_time)

    def _build_guardian_prompt(self, sql: str, context: Optional[str]) -> str:
        """Build the prompt for Granite Guardian analysis."""
        return f"""<|system|>
You are a security analyzer for SQL queries. Assess the risk level of the following SQL.
Respond with JSON: {{"risk_level": "NONE|LOW|MEDIUM|HIGH|CRITICAL", "risk_score": 0.0-1.0, "risk_categories": [...], "explanation": "..."}}
</|system|>

<|user|>
SQL: {sql}
{f"Context: {context}" if context else ""}
</|user|>

<|assistant|>"""

    def _parse_guardian_response(self, response: Any, start_time: float) -> GraniteGuardianResult:
        """Parse Granite Guardian response into structured result."""
        latency_ms = (time.time() - start_time) * 1000

        try:
            import json

            text = response.generated_text.strip()
            data = json.loads(text)

            return GraniteGuardianResult(
                risk_level=RiskLevel(data.get("risk_level", "NONE")),
                risk_score=float(data.get("risk_score", 0.0)),
                risk_categories=data.get("risk_categories", []),
                explanation=data.get("explanation", ""),
                latency_ms=latency_ms,
            )
        except Exception as e:
            logger.warning(f"Failed to parse Guardian response: {e}")
            return GraniteGuardianResult(
                risk_level=RiskLevel.MEDIUM,
                risk_score=0.5,
                risk_categories=["parse_error"],
                explanation="Could not parse Guardian response",
                latency_ms=latency_ms,
            )

    def _heuristic_assessment(self, sql: str, start_time: float) -> GraniteGuardianResult:
        """
        Fallback heuristic assessment when Granite Guardian is unavailable.

        Uses keyword detection as a basic risk signal.
        """
        latency_ms = (time.time() - start_time) * 1000
        sql_upper = sql.upper()

        risk_categories = []
        risk_score = 0.0

        # Critical risk patterns
        critical_patterns = ["DROP TABLE", "DROP DATABASE", "TRUNCATE", "--", ";--", "/*"]
        for pattern in critical_patterns:
            if pattern in sql_upper:
                risk_categories.append("destructive_ddl")
                risk_score = max(risk_score, 0.95)

        # High risk patterns
        high_patterns = ["DELETE FROM", "UPDATE.*SET.*WHERE 1=1", "GRANT", "REVOKE"]
        for pattern in high_patterns:
            if pattern.replace(".*", "") in sql_upper:
                risk_categories.append("data_modification")
                risk_score = max(risk_score, 0.75)

        # Medium risk patterns
        if "DELETE" in sql_upper:
            risk_categories.append("delete_operation")
            risk_score = max(risk_score, 0.5)

        # Determine risk level
        if risk_score >= 0.9:
            risk_level = RiskLevel.CRITICAL
        elif risk_score >= 0.7:
            risk_level = RiskLevel.HIGH
        elif risk_score >= 0.4:
            risk_level = RiskLevel.MEDIUM
        elif risk_score > 0:
            risk_level = RiskLevel.LOW
        else:
            risk_level = RiskLevel.NONE

        return GraniteGuardianResult(
            risk_level=risk_level,
            risk_score=risk_score,
            risk_categories=risk_categories,
            explanation="Heuristic assessment (Granite Guardian unavailable)",
            latency_ms=latency_ms,
        )


# -----------------------------------------------------------------------------
# Sentinel Engine
# -----------------------------------------------------------------------------


class SentinelEngine:
    """
    Core Sentinel validation engine.

    Orchestrates the complete validation pipeline:
    1. Receive Intent — Accept SQL from watsonx Orchestrate
    2. Check Cache — Return cached verdict if available (< 5ms)
    3. Granite Guardian Validation — Semantic risk assessment
    4. Db2 Rules Lookup — Pattern matching against SENTINEL_RULES
    5. Emit Verdict — ALLOW, BLOCK, or REWRITE

    Usage:
        engine = SentinelEngine()
        verdict = engine.validate("SELECT * FROM users WHERE id = 1")
        if verdict.allowed:
            # Execute query
        else:
            # Handle block/rewrite
    """

    def __init__(self, cache_enabled: bool = True):
        settings = get_settings()

        self._cache = VerdictCache(
            max_size=1000,
            ttl_seconds=settings.cache_ttl,
        ) if cache_enabled else None

        self._guardian = GraniteGuardian()
        self._db2_manager = get_db2_manager()

    def validate(
        self,
        sql: str,
        session_id: str = "",
        skip_cache: bool = False,
        context: Optional[str] = None,
    ) -> Verdict:
        """
        Validate SQL through the complete Sentinel pipeline.

        Args:
            sql: SQL statement to validate.
            session_id: Session ID for audit correlation.
            skip_cache: If True, bypass cache lookup.
            context: Optional context about the request.

        Returns:
            Verdict with validation result.
        """
        start_time = time.time()

        # ─────────────────────────────────────────────────────────────────────
        # STEP 1: Receive Intent
        # ─────────────────────────────────────────────────────────────────────
        logger.info(f"[{session_id}] Validating SQL: {sql[:100]}...")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 2: Check Cache
        # ─────────────────────────────────────────────────────────────────────
        if self._cache and not skip_cache:
            cached = self._cache.get(sql)
            if cached is not None:
                logger.info(f"[{session_id}] Cache hit, returning cached verdict")
                cached.session_id = session_id
                cached.latency_ms = (time.time() - start_time) * 1000
                return cached

        # ─────────────────────────────────────────────────────────────────────
        # STEP 3: Granite Guardian Validation (Neural Layer)
        # ─────────────────────────────────────────────────────────────────────
        guardian_result = self._guardian.assess_risk(sql, context)

        if guardian_result.risk_level == RiskLevel.CRITICAL:
            verdict = Verdict(
                verdict_type=VerdictType.BLOCK,
                allowed=False,
                rule_id="GRANITE-CRITICAL",
                message=f"Granite Guardian detected critical risk: {guardian_result.explanation}",
                granite_result=guardian_result,
                original_sql=sql,
                session_id=session_id,
                latency_ms=(time.time() - start_time) * 1000,
            )
            self._cache_verdict(sql, verdict)
            return verdict

        # ─────────────────────────────────────────────────────────────────────
        # STEP 4: Db2 Rules Lookup (Symbolic Layer)
        # ─────────────────────────────────────────────────────────────────────
        matched_rules = self._lookup_rules(sql)

        # Check for blocking rules
        for rule in matched_rules:
            if rule.action == "BLOCK_CRITICAL":
                verdict = Verdict(
                    verdict_type=VerdictType.BLOCK,
                    allowed=False,
                    rule_id=rule.rule_id,
                    message=f"Blocked by rule {rule.rule_id}: {rule.description}",
                    granite_result=guardian_result,
                    matched_rules=matched_rules,
                    original_sql=sql,
                    session_id=session_id,
                    latency_ms=(time.time() - start_time) * 1000,
                )
                self._cache_verdict(sql, verdict)
                return verdict

        # Check for rewrite rules
        for rule in matched_rules:
            if rule.action == "INTERCEPT_REWRITE":
                verdict = Verdict(
                    verdict_type=VerdictType.REWRITE,
                    allowed=False,
                    rule_id=rule.rule_id,
                    message=f"Intercepted by rule {rule.rule_id}: {rule.description}",
                    suggested_rewrite=self._generate_safe_alternative(sql, rule),
                    granite_result=guardian_result,
                    matched_rules=matched_rules,
                    original_sql=sql,
                    session_id=session_id,
                    latency_ms=(time.time() - start_time) * 1000,
                )
                self._cache_verdict(sql, verdict)
                return verdict

        # ─────────────────────────────────────────────────────────────────────
        # STEP 5: Emit Verdict — ALLOW
        # ─────────────────────────────────────────────────────────────────────
        verdict = Verdict(
            verdict_type=VerdictType.ALLOW,
            allowed=True,
            message="Query validated successfully",
            granite_result=guardian_result,
            matched_rules=matched_rules,
            original_sql=sql,
            session_id=session_id,
            latency_ms=(time.time() - start_time) * 1000,
        )
        self._cache_verdict(sql, verdict)

        logger.info(f"[{session_id}] Verdict: ALLOW ({verdict.latency_ms:.1f}ms)")
        return verdict

    def _lookup_rules(self, sql: str) -> list[RuleMatch]:
        """
        Query SENTINEL_RULES table for matching patterns.

        Args:
            sql: SQL to check against rules.

        Returns:
            List of matched RuleMatch objects.
        """
        try:
            with self._db2_manager.acquire() as conn:
                rows = conn.execute(
                    "SELECT rule_id, pattern, action, description "
                    "FROM SENTINEL_RULES WHERE active = 1"
                )

            matched: list[RuleMatch] = []
            sql_upper = sql.upper()

            for row in rows:
                pattern = (row.get("PATTERN") or row.get("pattern") or "").upper()
                if pattern and pattern in sql_upper:
                    matched.append(
                        RuleMatch(
                            rule_id=row.get("RULE_ID") or row.get("rule_id", ""),
                            pattern=pattern,
                            action=row.get("ACTION") or row.get("action", ""),
                            description=row.get("DESCRIPTION") or row.get("description", ""),
                        )
                    )

            return matched

        except Db2QueryError as e:
            logger.error(f"Failed to lookup rules: {e}")
            # Fail-closed: return a synthetic blocking rule
            return [
                RuleMatch(
                    rule_id="SYS-FAIL-CLOSED",
                    pattern="*",
                    action="BLOCK_CRITICAL",
                    description="Db2 rules lookup failed; fail-closed policy active",
                )
            ]

        except Exception as e:
            logger.error(f"Unexpected error in rules lookup: {e}")
            # Use in-memory fallback rules
            return self._fallback_rules_check(sql)

    def _fallback_rules_check(self, sql: str) -> list[RuleMatch]:
        """
        In-memory fallback rules when Db2 is unavailable.

        Mirrors the rules in governance_schema.sql.
        """
        sql_upper = sql.upper()
        matched: list[RuleMatch] = []

        fallback_rules = [
            ("GOV-404", "DROP TABLE", "BLOCK_CRITICAL", "Destructive DDL — table drop forbidden"),
            ("GOV-101", "DELETE", "INTERCEPT_REWRITE", "Bulk delete intercepted; suggest soft-delete"),
        ]

        for rule_id, pattern, action, description in fallback_rules:
            if pattern in sql_upper:
                matched.append(
                    RuleMatch(
                        rule_id=rule_id,
                        pattern=pattern,
                        action=action,
                        description=description,
                    )
                )

        return matched

    def _generate_safe_alternative(self, sql: str, rule: RuleMatch) -> str:
        """
        Generate a safe alternative for intercepted queries.

        For DELETE operations, suggests soft-delete pattern.
        """
        if "DELETE" in rule.pattern.upper():
            return (
                "-- Suggested safe alternative (soft-delete):\n"
                "UPDATE target_table SET\n"
                "    status = 'ARCHIVED',\n"
                "    deleted_at = CURRENT_TIMESTAMP\n"
                "WHERE <your_conditions>;"
            )

        return "-- Please contact your administrator for a safe alternative."

    def _cache_verdict(self, sql: str, verdict: Verdict) -> None:
        """Store verdict in cache if caching is enabled."""
        if self._cache:
            self._cache.put(sql, verdict)


# -----------------------------------------------------------------------------
# Module-Level Convenience
# -----------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_sentinel_engine() -> SentinelEngine:
    """Get or create the global SentinelEngine singleton."""
    return SentinelEngine()


def validate_sql(sql: str, session_id: str = "") -> Verdict:
    """
    One-shot SQL validation using the global engine.

    Args:
        sql: SQL statement to validate.
        session_id: Optional session ID for audit.

    Returns:
        Verdict with validation result.
    """
    return get_sentinel_engine().validate(sql, session_id)
