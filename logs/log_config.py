"""
Logging configuration module for currency scraper.

Supports logging to JSON file, PostgreSQL database, or both simultaneously.
Settings can be configured via environment variables or programmatically.
"""

import os
from pathlib import Path
from typing import Optional

# Attempt to load environment variables from environment/.env
try:
    from dotenv import load_dotenv

    _BASE_DIR = Path(__file__).resolve().parent.parent
    _ENV_PATH = _BASE_DIR / "environment" / ".env"
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH)
    else:
        load_dotenv()
except Exception:
    pass


def _clean_str(val: Optional[str]) -> str:
    """Strip whitespace and surrounding quotes."""
    if val is None:
        return ""
    return val.strip().strip("'\"")


def _parse_bool_env(name: str, default: bool = True) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return _clean_str(val).lower() in ("true", "1", "yes", "on")


def _parse_int_env(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return int(_clean_str(val))
    except (ValueError, TypeError):
        return default


# ============================================================
# Configurable Settings
# ============================================================

# Target destination: "json", "db", or "both"
LOG_DESTINATION: str = _clean_str(os.getenv("LOG_DESTINATION", "both")).lower() or "both"

# Directory for JSON logs
LOG_DIR: str = _clean_str(os.getenv("LOG_DIR", "logs")) or "logs"

# Filename for JSON logs
LOG_FILE_NAME: str = _clean_str(os.getenv("LOG_FILE_NAME", "pipeline.jsonl")) or "pipeline.jsonl"

# Target PostgreSQL table for database logging
LOG_TABLE_NAME: str = _clean_str(os.getenv("LOG_TABLE_NAME", "public.pipeline_logs")) or "public.pipeline_logs"
LOG_JSON_COLUMN: str = _clean_str(os.getenv("LOG_JSON_COLUMN", "details")) or "details"

# If True, writing to JSON file is attempted when DB logging fails
FALLBACK_TO_FILE_ON_DB_ERROR: bool = _parse_bool_env(
    "FALLBACK_TO_FILE_ON_DB_ERROR", default=True
)

# Optional database URL override; defaults to DATABASE_URL from environment
DATABASE_URL: Optional[str] = _clean_str(os.getenv("DATABASE_URL")) or None

# Database connect timeout in seconds
DB_CONNECT_TIMEOUT: int = _parse_int_env("DB_CONNECT_TIMEOUT", default=10)

# Cooldown interval before retrying connection to offline DB (seconds)
DB_RECONNECT_INTERVAL: int = _parse_int_env("DB_RECONNECT_INTERVAL", default=30)


# ============================================================
# Helper Functions
# ============================================================

def get_log_file_path() -> str:
    """Return the resolved path to the JSON log file."""
    return os.path.join(LOG_DIR, LOG_FILE_NAME)


def configure(
    destination: Optional[str] = None,
    log_dir: Optional[str] = None,
    file_name: Optional[str] = None,
    table_name: Optional[str] = None,
    fallback: Optional[bool] = None,
    database_url: Optional[str] = None,
    connect_timeout: Optional[int] = None,
    reconnect_interval: Optional[int] = None,
) -> None:
    """
    Dynamically update logging configuration.

    Parameters:
        destination: "json", "db", or "both"
        log_dir: Directory path for JSON logs
        file_name: Filename for JSON logs (e.g. "pipeline.jsonl")
        table_name: PostgreSQL table name (e.g. "public.pipeline_logs")
        fallback: If True, fallback to JSON file on DB failure
        database_url: PostgreSQL connection string
        connect_timeout: Connection timeout in seconds
        reconnect_interval: Retry cooldown in seconds when DB is unreachable
    """
    global LOG_DESTINATION, LOG_DIR, LOG_FILE_NAME, LOG_TABLE_NAME, FALLBACK_TO_FILE_ON_DB_ERROR
    global DATABASE_URL, DB_CONNECT_TIMEOUT, DB_RECONNECT_INTERVAL

    if destination is not None:
        LOG_DESTINATION = _clean_str(destination).lower()
    if log_dir is not None:
        LOG_DIR = _clean_str(log_dir)
    if file_name is not None:
        LOG_FILE_NAME = _clean_str(file_name)
    if table_name is not None:
        LOG_TABLE_NAME = _clean_str(table_name)
    if fallback is not None:
        FALLBACK_TO_FILE_ON_DB_ERROR = bool(fallback)
    if database_url is not None:
        DATABASE_URL = _clean_str(database_url) or None
    if connect_timeout is not None:
        DB_CONNECT_TIMEOUT = int(connect_timeout)
    if reconnect_interval is not None:
        DB_RECONNECT_INTERVAL = int(reconnect_interval)


def reset_to_defaults() -> None:
    """Reset configuration back to environment variable values or defaults."""
    global LOG_DESTINATION, LOG_DIR, LOG_FILE_NAME, LOG_TABLE_NAME, FALLBACK_TO_FILE_ON_DB_ERROR
    global DATABASE_URL, DB_CONNECT_TIMEOUT, DB_RECONNECT_INTERVAL

    LOG_DESTINATION = _clean_str(os.getenv("LOG_DESTINATION", "both")).lower() or "both"
    LOG_DIR = _clean_str(os.getenv("LOG_DIR", "logs")) or "logs"
    LOG_FILE_NAME = _clean_str(os.getenv("LOG_FILE_NAME", "pipeline.jsonl")) or "pipeline.jsonl"
    LOG_TABLE_NAME = _clean_str(os.getenv("LOG_TABLE_NAME", "public.pipeline_logs")) or "public.pipeline_logs"
    FALLBACK_TO_FILE_ON_DB_ERROR = _parse_bool_env(
        "FALLBACK_TO_FILE_ON_DB_ERROR", default=True
    )
    DATABASE_URL = _clean_str(os.getenv("DATABASE_URL")) or None
    DB_CONNECT_TIMEOUT = _parse_int_env("DB_CONNECT_TIMEOUT", default=10)
    DB_RECONNECT_INTERVAL = _parse_int_env("DB_RECONNECT_INTERVAL", default=30)
