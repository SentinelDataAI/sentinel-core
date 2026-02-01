"""
Sentinel — The Neuro-Symbolic Trust Layer for watsonx Orchestrate.

Built with IBM Project BOB (AI-Assisted Rapid Prototyping).
Team: Symbolic Overlords / Sentinel Data AI
Hackathon: IBM "AI Demystified" 2025

Modules:
    - sentinel_engine: Core validation pipeline (Granite Guardian + Db2 rules)
    - db2_manager: Production Db2 connection pooling
    - audit_service: Async audit trail logging
"""

__version__ = "1.0.0"
__author__ = "Symbolic Overlords"
__project_bob__ = True

from .sentinel_engine import SentinelEngine, Verdict, VerdictType
from .db2_manager import Db2Manager, PersistentConnection
from .audit_service import AuditService, log_event

__all__ = [
    "SentinelEngine",
    "Verdict",
    "VerdictType",
    "Db2Manager",
    "PersistentConnection",
    "AuditService",
    "log_event",
    "__version__",
]
