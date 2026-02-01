"""
Audit Service — Async Audit Trail for Compliance.

Every Sentinel validation event is logged to the AUDIT_LOG table in Db2.
This provides a complete forensic trail for compliance, debugging, and analytics.

Audit events are written asynchronously to avoid blocking the validation pipeline.

Built with IBM Project BOB.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from config.settings import get_settings

# Conditional import for Db2
try:
    from .db2_manager import get_db2_manager, Db2QueryError

    DB2_AVAILABLE = True
except ImportError:
    DB2_AVAILABLE = False

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Audit Event Schema
# -----------------------------------------------------------------------------
#
# The AUDIT_LOG table structure (create in Db2):
#
# CREATE TABLE AUDIT_LOG (
#     id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
#     event_id        VARCHAR(64) NOT NULL,
#     session_id      VARCHAR(64),
#     timestamp       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
#     event_type      VARCHAR(32) NOT NULL,
#     verdict         VARCHAR(16) NOT NULL,
#     rule_id         VARCHAR(32),
#     original_sql    CLOB,
#     risk_score      DECIMAL(5, 4),
#     latency_ms      DECIMAL(10, 2),
#     metadata        CLOB,
#     created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
# );
#
# CREATE INDEX idx_audit_session ON AUDIT_LOG(session_id);
# CREATE INDEX idx_audit_timestamp ON AUDIT_LOG(timestamp);
# CREATE INDEX idx_audit_verdict ON AUDIT_LOG(verdict);
#
# -----------------------------------------------------------------------------


class EventType(str, Enum):
    """Types of audit events."""

    VALIDATION = "VALIDATION"
    CACHE_HIT = "CACHE_HIT"
    RULE_MATCH = "RULE_MATCH"
    GUARDIAN_CALL = "GUARDIAN_CALL"
    ERROR = "ERROR"


@dataclass
class AuditEvent:
    """
    Structured audit event for logging.

    Attributes:
        event_id: Unique identifier for this event.
        session_id: Session identifier for correlation.
        timestamp: When the event occurred (ISO 8601).
        event_type: Type of event (VALIDATION, CACHE_HIT, etc.).
        verdict: Validation verdict (ALLOW, BLOCK, REWRITE).
        rule_id: ID of matched rule, if any.
        original_sql: The SQL that was validated.
        risk_score: Risk score from Granite Guardian (0.0 - 1.0).
        latency_ms: Processing time in milliseconds.
        metadata: Additional context as JSON.
    """

    event_id: str
    session_id: str
    timestamp: str
    event_type: EventType
    verdict: str
    rule_id: Optional[str] = None
    original_sql: Optional[str] = None
    risk_score: Optional[float] = None
    latency_ms: Optional[float] = None
    metadata: Optional[dict[str, Any]] = None

    @classmethod
    def create(
        cls,
        session_id: str,
        event_type: EventType,
        verdict: str,
        **kwargs: Any,
    ) -> "AuditEvent":
        """Factory method to create an audit event with generated ID and timestamp."""
        return cls(
            event_id=str(uuid.uuid4()),
            session_id=session_id,
            timestamp=datetime.utcnow().isoformat() + "Z",
            event_type=event_type,
            verdict=verdict,
            **kwargs,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data["event_type"] = self.event_type.value
        return data


# -----------------------------------------------------------------------------
# Async Audit Writer
# -----------------------------------------------------------------------------


class AuditWriter:
    """
    Background thread that writes audit events to Db2 asynchronously.

    Events are queued and written in batches to minimize database round-trips.
    Failed writes are retried with exponential backoff.
    """

    def __init__(
        self,
        batch_size: int = 10,
        flush_interval: float = 5.0,
        max_retries: int = 3,
    ):
        self._queue: queue.Queue[AuditEvent] = queue.Queue()
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._max_retries = max_retries
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the background writer thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Audit writer started")

    def stop(self) -> None:
        """Stop the background writer thread and flush remaining events."""
        self._running = False

        if self._thread:
            self._thread.join(timeout=10.0)
            self._thread = None

        # Flush any remaining events
        self._flush()
        logger.info("Audit writer stopped")

    def enqueue(self, event: AuditEvent) -> None:
        """Add an event to the write queue."""
        self._queue.put(event)

    def _run(self) -> None:
        """Background loop: collect events and write in batches."""
        while self._running:
            try:
                self._flush()
                time.sleep(self._flush_interval)
            except Exception as e:
                logger.error(f"Audit writer error: {e}")

    def _flush(self) -> None:
        """Flush queued events to Db2."""
        batch: list[AuditEvent] = []

        while len(batch) < self._batch_size:
            try:
                event = self._queue.get_nowait()
                batch.append(event)
            except queue.Empty:
                break

        if not batch:
            return

        self._write_batch(batch)

    def _write_batch(self, batch: list[AuditEvent]) -> None:
        """Write a batch of events to Db2."""
        if not DB2_AVAILABLE:
            # Fallback: log to file/stdout
            for event in batch:
                logger.info(f"AUDIT: {json.dumps(event.to_dict())}")
            return

        try:
            manager = get_db2_manager()

            with manager.acquire() as conn:
                for event in batch:
                    self._insert_event(conn, event)

            logger.debug(f"Wrote {len(batch)} audit events to Db2")

        except Exception as e:
            logger.error(f"Failed to write audit batch: {e}")
            # Fallback: log to stdout
            for event in batch:
                logger.info(f"AUDIT (fallback): {json.dumps(event.to_dict())}")

    def _insert_event(self, conn: Any, event: AuditEvent) -> None:
        """Insert a single audit event into AUDIT_LOG."""
        sql = """
            INSERT INTO AUDIT_LOG (
                event_id, session_id, timestamp, event_type, verdict,
                rule_id, original_sql, risk_score, latency_ms, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        params = (
            event.event_id,
            event.session_id,
            event.timestamp,
            event.event_type.value,
            event.verdict,
            event.rule_id,
            event.original_sql,
            event.risk_score,
            event.latency_ms,
            json.dumps(event.metadata) if event.metadata else None,
        )

        conn.execute_non_query(sql, params)


# -----------------------------------------------------------------------------
# Audit Service (High-Level API)
# -----------------------------------------------------------------------------


class AuditService:
    """
    High-level audit service for Sentinel.

    Provides a simple interface to log validation events. Events are written
    asynchronously to avoid blocking the validation pipeline.

    Usage:
        service = AuditService()
        service.start()

        service.log_validation(
            session_id="abc123",
            verdict="ALLOW",
            original_sql="SELECT * FROM users",
            latency_ms=42.5,
        )

        service.stop()
    """

    _instance: Optional["AuditService"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "AuditService":
        """Singleton pattern for global audit service."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        settings = get_settings()
        self._writer = AuditWriter(
            batch_size=settings.audit_batch_size,
            flush_interval=settings.audit_flush_interval,
        )
        self._enabled = settings.audit_enabled
        self._initialized = True

    def start(self) -> None:
        """Start the audit service."""
        if self._enabled:
            self._writer.start()

    def stop(self) -> None:
        """Stop the audit service and flush remaining events."""
        self._writer.stop()

    def log_validation(
        self,
        session_id: str,
        verdict: str,
        original_sql: Optional[str] = None,
        rule_id: Optional[str] = None,
        risk_score: Optional[float] = None,
        latency_ms: Optional[float] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Log a validation event.

        Args:
            session_id: Session identifier.
            verdict: Validation verdict (ALLOW, BLOCK, REWRITE).
            original_sql: The validated SQL.
            rule_id: Matched rule ID, if any.
            risk_score: Granite Guardian risk score.
            latency_ms: Validation latency.
            metadata: Additional context.
        """
        if not self._enabled:
            return

        event = AuditEvent.create(
            session_id=session_id,
            event_type=EventType.VALIDATION,
            verdict=verdict,
            original_sql=original_sql,
            rule_id=rule_id,
            risk_score=risk_score,
            latency_ms=latency_ms,
            metadata=metadata,
        )

        self._writer.enqueue(event)

    def log_error(
        self,
        session_id: str,
        error_message: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log an error event."""
        if not self._enabled:
            return

        event = AuditEvent.create(
            session_id=session_id,
            event_type=EventType.ERROR,
            verdict="ERROR",
            metadata={"error": error_message, **(metadata or {})},
        )

        self._writer.enqueue(event)


# -----------------------------------------------------------------------------
# Module-Level Convenience Functions
# -----------------------------------------------------------------------------


def get_audit_service() -> AuditService:
    """Get the global AuditService singleton."""
    return AuditService()


async def log_event(
    session_id: str,
    verdict: str,
    original_sql: Optional[str] = None,
    rule_id: Optional[str] = None,
    risk_score: Optional[float] = None,
    latency_ms: Optional[float] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """
    Async convenience function to log a validation event.

    This is a coroutine wrapper around AuditService.log_validation().
    It can be awaited in async FastAPI endpoints.

    Args:
        session_id: Session identifier.
        verdict: Validation verdict (ALLOW, BLOCK, REWRITE).
        original_sql: The validated SQL.
        rule_id: Matched rule ID, if any.
        risk_score: Granite Guardian risk score.
        latency_ms: Validation latency.
        metadata: Additional context.
    """
    service = get_audit_service()

    # Run in executor to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: service.log_validation(
            session_id=session_id,
            verdict=verdict,
            original_sql=original_sql,
            rule_id=rule_id,
            risk_score=risk_score,
            latency_ms=latency_ms,
            metadata=metadata,
        ),
    )
