"""
Db2 Connection Manager — Production-Grade Connection Pooling.

This module provides persistent, health-checked connections to IBM Db2.
Schema verified against a live Db2 on Docker instance (db2:11.5.8.0).

Built with IBM Project BOB.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator, Optional

# Production import: ibm_db
# Graceful fallback for environments without the driver installed
try:
    import ibm_db
    import ibm_db_dbi

    IBM_DB_AVAILABLE = True
except ImportError:
    ibm_db = None  # type: ignore
    ibm_db_dbi = None  # type: ignore
    IBM_DB_AVAILABLE = False

from config.settings import get_settings

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------------


class Db2ConnectionError(Exception):
    """Raised when Db2 connection cannot be established or is unhealthy."""

    pass


class Db2QueryError(Exception):
    """Raised when a query execution fails."""

    pass


# -----------------------------------------------------------------------------
# Connection Configuration
# -----------------------------------------------------------------------------


@dataclass
class Db2Config:
    """Configuration for Db2 connection."""

    dsn: str
    user: str
    password: str
    pool_size: int = 5
    connect_timeout: int = 30
    query_timeout: int = 60
    health_check_interval: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0


# -----------------------------------------------------------------------------
# Persistent Connection (Single Connection Wrapper)
# -----------------------------------------------------------------------------


class PersistentConnection:
    """
    A single persistent Db2 connection with health checking.

    This class wraps an ibm_db connection handle and provides:
    - Automatic reconnection on failure
    - Health check via lightweight query
    - Thread-safe access via lock

    Note: Schema verified against live Db2 on Docker:
        docker run -d --name db2 -p 50000:50000 \
            -e DB2INST1_PASSWORD=sentinel \
            -e LICENSE=accept \
            ibmcom/db2:11.5.8.0
    """

    def __init__(self, config: Db2Config):
        self._config = config
        self._conn: Optional[Any] = None
        self._lock = threading.Lock()
        self._last_health_check: float = 0.0
        self._connected: bool = False

    @property
    def is_connected(self) -> bool:
        """Return True if connection is established."""
        return self._connected and self._conn is not None

    def connect(self) -> None:
        """
        Establish connection to Db2.

        Raises:
            Db2ConnectionError: If connection fails after retries.
        """
        if not IBM_DB_AVAILABLE:
            raise Db2ConnectionError(
                "ibm_db driver not installed. Run: pip install ibm_db"
            )

        with self._lock:
            if self._connected and self._conn is not None:
                return

            last_error: Optional[Exception] = None

            for attempt in range(1, self._config.max_retries + 1):
                try:
                    logger.info(
                        f"Db2 connection attempt {attempt}/{self._config.max_retries}"
                    )

                    # Build connection string
                    conn_str = (
                        f"DATABASE={self._config.dsn};"
                        f"HOSTNAME=localhost;"
                        f"PORT=50000;"
                        f"PROTOCOL=TCPIP;"
                        f"UID={self._config.user};"
                        f"PWD={self._config.password};"
                        f"CONNECTTIMEOUT={self._config.connect_timeout};"
                    )

                    self._conn = ibm_db.connect(conn_str, "", "")
                    self._connected = True
                    self._last_health_check = time.time()

                    logger.info("Db2 connection established successfully")
                    return

                except Exception as e:
                    last_error = e
                    logger.warning(f"Connection attempt {attempt} failed: {e}")

                    if attempt < self._config.max_retries:
                        time.sleep(self._config.retry_delay * attempt)

            raise Db2ConnectionError(
                f"Failed to connect to Db2 after {self._config.max_retries} attempts: {last_error}"
            )

    def disconnect(self) -> None:
        """Close the Db2 connection."""
        with self._lock:
            if self._conn is not None:
                try:
                    ibm_db.close(self._conn)
                    logger.info("Db2 connection closed")
                except Exception as e:
                    logger.warning(f"Error closing Db2 connection: {e}")
                finally:
                    self._conn = None
                    self._connected = False

    def health_check(self, force: bool = False) -> bool:
        """
        Verify connection is alive via lightweight query.

        Args:
            force: If True, bypass interval check and always query.

        Returns:
            True if connection is healthy, False otherwise.
        """
        if not self._connected or self._conn is None:
            return False

        now = time.time()
        if not force and (now - self._last_health_check) < self._config.health_check_interval:
            return True

        with self._lock:
            try:
                # Lightweight health check query
                stmt = ibm_db.exec_immediate(self._conn, "SELECT 1 FROM SYSIBM.SYSDUMMY1")
                ibm_db.fetch_tuple(stmt)
                ibm_db.free_stmt(stmt)

                self._last_health_check = now
                return True

            except Exception as e:
                logger.warning(f"Health check failed: {e}")
                self._connected = False
                return False

    def execute(self, sql: str, params: Optional[tuple] = None) -> list[dict]:
        """
        Execute a SQL query and return results as list of dicts.

        Args:
            sql: SQL statement to execute.
            params: Optional tuple of parameters for prepared statement.

        Returns:
            List of dictionaries (column_name: value).

        Raises:
            Db2QueryError: If query execution fails.
            Db2ConnectionError: If not connected.
        """
        if not self.is_connected:
            raise Db2ConnectionError("Not connected to Db2")

        with self._lock:
            try:
                if params:
                    stmt = ibm_db.prepare(self._conn, sql)
                    ibm_db.execute(stmt, params)
                else:
                    stmt = ibm_db.exec_immediate(self._conn, sql)

                results: list[dict] = []
                row = ibm_db.fetch_assoc(stmt)

                while row:
                    results.append(dict(row))
                    row = ibm_db.fetch_assoc(stmt)

                ibm_db.free_stmt(stmt)
                return results

            except Exception as e:
                logger.error(f"Query execution failed: {e}")
                raise Db2QueryError(f"Query failed: {e}") from e

    def execute_non_query(self, sql: str, params: Optional[tuple] = None) -> int:
        """
        Execute a non-SELECT statement (INSERT, UPDATE, DELETE).

        Args:
            sql: SQL statement to execute.
            params: Optional tuple of parameters.

        Returns:
            Number of affected rows.

        Raises:
            Db2QueryError: If execution fails.
        """
        if not self.is_connected:
            raise Db2ConnectionError("Not connected to Db2")

        with self._lock:
            try:
                if params:
                    stmt = ibm_db.prepare(self._conn, sql)
                    ibm_db.execute(stmt, params)
                else:
                    stmt = ibm_db.exec_immediate(self._conn, sql)

                affected = ibm_db.num_rows(stmt)
                ibm_db.free_stmt(stmt)
                return affected

            except Exception as e:
                logger.error(f"Non-query execution failed: {e}")
                raise Db2QueryError(f"Execution failed: {e}") from e


# -----------------------------------------------------------------------------
# Connection Pool Manager
# -----------------------------------------------------------------------------


@dataclass
class Db2Manager:
    """
    Production Db2 connection pool manager.

    Manages a pool of PersistentConnection instances with:
    - Lazy initialization
    - Automatic health checks
    - Context manager support for safe acquisition/release

    Usage:
        manager = Db2Manager.from_settings()
        with manager.acquire() as conn:
            results = conn.execute("SELECT * FROM SENTINEL_RULES WHERE active = 1")
    """

    config: Db2Config
    _pool: list[PersistentConnection] = field(default_factory=list)
    _available: list[PersistentConnection] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _initialized: bool = False

    @classmethod
    def from_settings(cls) -> "Db2Manager":
        """Create manager from application settings."""
        settings = get_settings()

        config = Db2Config(
            dsn=settings.db2_dsn,
            user=settings.db2_user,
            password=settings.db2_password,
            pool_size=settings.db2_pool_size,
        )

        return cls(config=config)

    def initialize(self) -> None:
        """Initialize the connection pool."""
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return

            logger.info(f"Initializing Db2 pool with {self.config.pool_size} connections")

            for i in range(self.config.pool_size):
                conn = PersistentConnection(self.config)
                conn.connect()
                self._pool.append(conn)
                self._available.append(conn)

            self._initialized = True
            logger.info("Db2 connection pool initialized")

    def shutdown(self) -> None:
        """Close all connections and shutdown the pool."""
        with self._lock:
            logger.info("Shutting down Db2 connection pool")

            for conn in self._pool:
                conn.disconnect()

            self._pool.clear()
            self._available.clear()
            self._initialized = False

    @contextmanager
    def acquire(self) -> Generator[PersistentConnection, None, None]:
        """
        Acquire a connection from the pool.

        Usage:
            with manager.acquire() as conn:
                results = conn.execute("SELECT ...")

        Yields:
            PersistentConnection instance.

        Raises:
            Db2ConnectionError: If no connections available.
        """
        if not self._initialized:
            self.initialize()

        conn: Optional[PersistentConnection] = None

        with self._lock:
            if not self._available:
                raise Db2ConnectionError("No connections available in pool")

            conn = self._available.pop()

        try:
            # Health check before use
            if not conn.health_check():
                logger.info("Reconnecting unhealthy connection")
                conn.connect()

            yield conn

        finally:
            # Return connection to pool
            with self._lock:
                self._available.append(conn)


# -----------------------------------------------------------------------------
# Module-Level Singleton
# -----------------------------------------------------------------------------

_manager: Optional[Db2Manager] = None
_manager_lock = threading.Lock()


def get_db2_manager() -> Db2Manager:
    """Get or create the global Db2Manager singleton."""
    global _manager

    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = Db2Manager.from_settings()

    return _manager
