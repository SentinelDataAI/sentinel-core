"""
Settings Management — Pydantic-Based Configuration.

Centralized configuration for Sentinel using Pydantic settings.
Supports environment variables, .env files, and sensible defaults.

Environment Variable Prefix: SENTINEL_

Built with IBM Project BOB.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All Sentinel configuration is centralized here. Environment variables
    are prefixed with SENTINEL_ (e.g., SENTINEL_DB2_DSN).

    Db2 Configuration:
        - db2_dsn: Database name or DSN
        - db2_host: Database host (default: localhost)
        - db2_port: Database port (default: 50000)
        - db2_user: Database username
        - db2_password: Database password
        - db2_pool_size: Connection pool size (default: 5)

    Granite Guardian Configuration:
        - granite_api_key: IBM watsonx API key
        - granite_api_endpoint: API endpoint URL
        - granite_project_id: watsonx project ID

    Cache Configuration:
        - cache_ttl: Cache TTL in seconds (default: 300)
        - cache_enabled: Enable/disable caching (default: True)

    Audit Configuration:
        - audit_enabled: Enable/disable audit logging (default: True)
        - audit_batch_size: Batch size for async writes (default: 10)
        - audit_flush_interval: Flush interval in seconds (default: 5.0)

    Application Configuration:
        - log_level: Logging level (default: INFO)
        - debug: Enable debug mode (default: False)
        - api_host: FastAPI host (default: 0.0.0.0)
        - api_port: FastAPI port (default: 8000)
    """

    model_config = SettingsConfigDict(
        env_prefix="SENTINEL_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Db2 Configuration
    # -------------------------------------------------------------------------

    db2_dsn: str = Field(
        default="SENTINELDB",
        description="Db2 database name or DSN",
    )

    db2_host: str = Field(
        default="localhost",
        description="Db2 database host",
    )

    db2_port: int = Field(
        default=50000,
        description="Db2 database port",
    )

    db2_user: str = Field(
        default="db2inst1",
        description="Db2 username",
    )

    db2_password: str = Field(
        default="",
        description="Db2 password",
    )

    db2_pool_size: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Db2 connection pool size",
    )

    db2_connect_timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Db2 connection timeout in seconds",
    )

    db2_query_timeout: int = Field(
        default=60,
        ge=10,
        le=300,
        description="Db2 query timeout in seconds",
    )

    # -------------------------------------------------------------------------
    # Granite Guardian Configuration
    # -------------------------------------------------------------------------

    granite_api_key: Optional[str] = Field(
        default=None,
        description="IBM watsonx API key for Granite Guardian",
    )

    granite_api_endpoint: str = Field(
        default="https://us-south.ml.cloud.ibm.com",
        description="IBM watsonx API endpoint",
    )

    granite_project_id: Optional[str] = Field(
        default=None,
        description="IBM watsonx project ID",
    )

    granite_model_id: str = Field(
        default="ibm/granite-guardian-3.0-8b",
        description="Granite Guardian model ID",
    )

    granite_timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Granite Guardian API timeout in seconds",
    )

    # -------------------------------------------------------------------------
    # Cache Configuration
    # -------------------------------------------------------------------------

    cache_enabled: bool = Field(
        default=True,
        description="Enable verdict caching",
    )

    cache_ttl: int = Field(
        default=300,
        ge=0,
        le=3600,
        description="Cache TTL in seconds",
    )

    cache_max_size: int = Field(
        default=1000,
        ge=100,
        le=100000,
        description="Maximum cache entries",
    )

    # -------------------------------------------------------------------------
    # Audit Configuration
    # -------------------------------------------------------------------------

    audit_enabled: bool = Field(
        default=True,
        description="Enable audit logging to Db2",
    )

    audit_batch_size: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Audit write batch size",
    )

    audit_flush_interval: float = Field(
        default=5.0,
        ge=1.0,
        le=60.0,
        description="Audit flush interval in seconds",
    )

    # -------------------------------------------------------------------------
    # Application Configuration
    # -------------------------------------------------------------------------

    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )

    debug: bool = Field(
        default=False,
        description="Enable debug mode",
    )

    api_host: str = Field(
        default="0.0.0.0",
        description="FastAPI server host",
    )

    api_port: int = Field(
        default=8000,
        ge=1024,
        le=65535,
        description="FastAPI server port",
    )

    api_workers: int = Field(
        default=4,
        ge=1,
        le=32,
        description="Number of API workers",
    )

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Ensure log level is valid."""
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {valid}")
        return upper

    # -------------------------------------------------------------------------
    # Computed Properties
    # -------------------------------------------------------------------------

    @property
    def db2_connection_string(self) -> str:
        """Build Db2 connection string."""
        return (
            f"DATABASE={self.db2_dsn};"
            f"HOSTNAME={self.db2_host};"
            f"PORT={self.db2_port};"
            f"PROTOCOL=TCPIP;"
            f"UID={self.db2_user};"
            f"PWD={self.db2_password};"
            f"CONNECTTIMEOUT={self.db2_connect_timeout};"
        )

    @property
    def is_granite_configured(self) -> bool:
        """Check if Granite Guardian is configured."""
        return bool(self.granite_api_key and self.granite_project_id)


# -----------------------------------------------------------------------------
# Singleton Access
# -----------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Get the cached application settings.

    Returns a singleton Settings instance. The first call loads from
    environment variables and .env file; subsequent calls return cached.

    Returns:
        Settings instance.
    """
    return Settings()


def reload_settings() -> Settings:
    """
    Force reload of settings (clears cache).

    Useful for testing or dynamic reconfiguration.

    Returns:
        Fresh Settings instance.
    """
    get_settings.cache_clear()
    return get_settings()
