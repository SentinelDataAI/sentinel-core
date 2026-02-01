"""
Db2 Connector — Connection pattern only (no credentials in code).

Public Evaluation Build: Shows how Sentinel acquires Db2 connections.
Credentials are loaded from environment variables only; no secrets in repo.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Generator, Optional

# ibm_db is required in production; optional for public build
try:
    import ibm_db

    IBM_DB_AVAILABLE = True
except ImportError:
    ibm_db = None  # type: ignore
    IBM_DB_AVAILABLE = False


def _build_connection_string() -> str:
    """
    Build Db2 connection string from environment variables only.

    Required env vars (no defaults for credentials):
        - SENTINEL_DB2_DSN or DB2_DSN
        - SENTINEL_DB2_HOST or DB2_HOST (default: localhost)
        - SENTINEL_DB2_PORT or DB2_PORT (default: 50000)
        - SENTINEL_DB2_USER or DB2_USER
        - SENTINEL_DB2_PASSWORD or DB2_PASSWORD

    No credentials are stored in this file.
    """
    dsn = os.environ.get("SENTINEL_DB2_DSN") or os.environ.get("DB2_DSN", "")
    host = os.environ.get("SENTINEL_DB2_HOST") or os.environ.get("DB2_HOST", "localhost")
    port = os.environ.get("SENTINEL_DB2_PORT") or os.environ.get("DB2_PORT", "50000")
    user = os.environ.get("SENTINEL_DB2_USER") or os.environ.get("DB2_USER", "")
    password = os.environ.get("SENTINEL_DB2_PASSWORD") or os.environ.get("DB2_PASSWORD", "")

    return (
        f"DATABASE={dsn};"
        f"HOSTNAME={host};"
        f"PORT={port};"
        f"PROTOCOL=TCPIP;"
        f"UID={user};"
        f"PWD={password};"
        f"CONNECTTIMEOUT=30;"
    )


@contextmanager
def get_connection() -> Generator[Any, None, None]:
    """
    Context manager for a single Db2 connection.

    Usage:
        with get_connection() as conn:
            # execute queries via conn
            pass

    Connection is closed on exit. Credentials come only from environment.
    """
    if not IBM_DB_AVAILABLE:
        yield None
        return

    conn_str = _build_connection_string()
    conn = None

    try:
        conn = ibm_db.connect(conn_str, "", "")
        yield conn
    finally:
        if conn is not None:
            try:
                ibm_db.close(conn)
            except Exception:
                pass
