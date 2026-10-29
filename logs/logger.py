"""
Structured event logging system for currency scraper pipeline.

Supports configurable dispatching to JSON file, PostgreSQL database, or both,
with automatic fallback, multiprocessing safety, connection cooldown, stdout/stderr streaming for Docker,
and strict failure isolation.
"""

import atexit
import json
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Optional psycopg2 import for database logging
try:
    import psycopg2
except ImportError:
    psycopg2 = None

# Configuration module import with fallback for varied execution environments
try:
    from . import log_config
except (ImportError, ValueError):
    try:
        import logs.log_config as log_config
    except ImportError:
        import log_config


# Destination mapping sets
_JSON_DESTS = {"json", "file"}
_DB_DESTS = {"db", "database", "postgres", "postgresql"}
_BOTH_DESTS = {"both", "all", "db,json", "json,db", "file,db", "db,file", "file,database", "database,file"}

# Regex for safe SQL identifier (table names e.g. public.pipeline_logs)
_SAFE_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9_]+(\.[a-zA-Z0-9_]+)?$")


# ============================================================
# Backward-Compatible Module Constants & Direct Assignment Support
# ============================================================

def __getattr__(name: str) -> Any:
    """Module-level attribute fallback for backward compatibility (PEP 562)."""
    if name == "LOG_DIR":
        return getattr(log_config, "LOG_DIR", "logs")
    if name == "LOG_FILE":
        return _get_active_log_file()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def _get_active_log_file() -> str:
    """Return active log file, respecting direct logger overrides or log_config."""
    mod_globals = globals()
    if "LOG_FILE" in mod_globals:
        return mod_globals["LOG_FILE"]
    if "LOG_DIR" in mod_globals:
        file_name = getattr(log_config, "LOG_FILE_NAME", "pipeline.jsonl")
        return os.path.join(mod_globals["LOG_DIR"], file_name)

    if callable(getattr(log_config, "get_log_file_path", None)):
        return log_config.get_log_file_path()

    return os.path.join(getattr(log_config, "LOG_DIR", "logs"), "pipeline.jsonl")


# ============================================================
# Run ID and Snapshot ID State
# ============================================================

_current_run_id: Optional[str] = None
_current_snapshot_id: Optional[Any] = None

# Recursion guard to prevent re-entrant loops
_in_log_event: bool = False

# Database connection and state
_db_connection: Optional[Any] = None
_db_pid: Optional[int] = None
_last_db_url: Optional[str] = None
_last_db_failure_time: float = 0.0
_orphaned_parent_conns: List[Any] = []
_verified_tables: set = set()
_db_lock = threading.Lock()


# ============================================================
# Directory Initialization
# ============================================================

try:
    target_dir = getattr(log_config, "LOG_DIR", "logs")
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)
except Exception:
    # Logger must never crash the pipeline
    pass


# ============================================================
# Public State Management API (Backward-Compatible)
# ============================================================

def start_run() -> str:
    """Generate and return a new unique run ID, clearing snapshot state."""
    global _current_run_id
    global _current_snapshot_id

    try:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        random_id = uuid.uuid4().hex[:4]
        _current_run_id = f"{timestamp}-{random_id}"
        _current_snapshot_id = None
        return _current_run_id
    except Exception:
        _current_run_id = "unknown-run"
        _current_snapshot_id = None
        return _current_run_id


def get_run_id() -> Optional[str]:
    """Return the current run ID."""
    return _current_run_id


def set_run_id(run_id: Optional[str]) -> None:
    """Set the current run ID (used by child worker processes)."""
    global _current_run_id
    try:
        _current_run_id = run_id
    except Exception:
        pass


def set_snapshot_id(snapshot_id: Optional[Any]) -> None:
    """Set the current snapshot ID."""
    global _current_snapshot_id
    try:
        _current_snapshot_id = snapshot_id
    except Exception:
        pass


def get_snapshot_id() -> Optional[Any]:
    """Return the current snapshot ID."""
    return _current_snapshot_id


# ============================================================
# Database Logging Connection & Table Setup
# ============================================================

def _reset_db_connection(reset_cooldown: bool = False) -> None:
    """Safely reset and close the cached database connection for this process."""
    global _db_connection, _db_pid, _last_db_url, _last_db_failure_time
    if _db_connection is not None:
        try:
            # Only close if in the same process that opened the socket
            if _db_pid == os.getpid() and hasattr(_db_connection, "close"):
                _db_connection.close()
        except Exception:
            pass
    _db_connection = None
    _db_pid = None
    _last_db_url = None
    if reset_cooldown:
        _last_db_failure_time = 0.0


def close_db_logging_connection() -> None:
    """Explicit public helper to clean up logger database resources and cooldown."""
    with _db_lock:
        _reset_db_connection(reset_cooldown=True)


atexit.register(close_db_logging_connection)


def _get_db_connection() -> Optional[Any]:
    """
    Acquire or reuse a dedicated per-process PostgreSQL connection for logger.

    Guarantees multiprocessing safety: if the current PID differs from the PID
    that created the connection, the reference is retained in _orphaned_parent_conns
    to prevent child GC from sending PQfinish on the parent's socket, and a fresh
    connection is lazily established for the child process.

    Includes circuit-breaker cooldown when database connection attempts fail,
    preventing multi-second pipeline stalls on each log call during outages.
    """
    global _db_connection, _db_pid, _last_db_url, _last_db_failure_time

    current_pid = os.getpid()

    # Detect process boundary (e.g. multiprocessing spawn/fork)
    if _db_connection is not None and _db_pid != current_pid:
        # Prevent GC in child process from sending PQfinish termination packet on parent socket
        _orphaned_parent_conns.append(_db_connection)
        _db_connection = None
        _db_pid = None
        _last_db_url = None

    raw_url = getattr(log_config, "DATABASE_URL", None) or os.getenv("DATABASE_URL")
    db_url = raw_url.strip().strip("'\"") if isinstance(raw_url, str) else None
    if not db_url:
        return None

    # Detect runtime configuration change of DATABASE_URL
    if _db_connection is not None and _last_db_url != db_url:
        _reset_db_connection(reset_cooldown=True)

    # Reuse healthy existing connection
    if _db_connection is not None:
        try:
            if getattr(_db_connection, "closed", 0) == 0:
                return _db_connection
        except Exception:
            pass
        _reset_db_connection(reset_cooldown=False)

    if psycopg2 is None:
        return None

    # Circuit breaker: cooldown window before attempting to reconnect to offline DB
    reconnect_interval = getattr(log_config, "DB_RECONNECT_INTERVAL", 30)
    now = time.monotonic()
    if _last_db_failure_time > 0 and (now - _last_db_failure_time) < reconnect_interval:
        return None

    connect_timeout = getattr(log_config, "DB_CONNECT_TIMEOUT", 10)

    try:
        conn = psycopg2.connect(db_url, connect_timeout=connect_timeout)
        # Use autocommit so log events do not hold open transactions or table locks
        conn.autocommit = True
        _db_connection = conn
        _db_pid = current_pid
        _last_db_url = db_url
        _last_db_failure_time = 0.0
        return _db_connection
    except Exception as exc:
        _last_db_failure_time = time.monotonic()
        _reset_db_connection(reset_cooldown=False)
        try:
            sys.stderr.write(f"[LOGGER DB CONNECT ERROR] {exc}\n")
            sys.stderr.flush()
        except Exception:
            pass
        return None


def _ensure_table_exists(conn: Any, table_name: str) -> None:
    """Idempotently ensure target table exists in PostgreSQL."""
    if table_name in _verified_tables:
        return

    # Validate identifier format to prevent SQL injection or formatting issues
    if not _SAFE_IDENTIFIER_RE.match(table_name):
        _verified_tables.add(table_name)
        return

    try:
        with conn.cursor() as cursor:
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id BIGSERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ DEFAULT NOW(),
                    run_id TEXT,
                    snapshot_id BIGINT,
                    level VARCHAR(50),
                    event VARCHAR(128),
                    component VARCHAR(64),
                    details JSONB DEFAULT '{{}}'::jsonb
                );
            """)
        _verified_tables.add(table_name)
    except Exception as table_exc:
        # Cleanly rollback to protect connection state if not in autocommit mode
        try:
            if hasattr(conn, "rollback"):
                conn.rollback()
        except Exception:
            pass
        _verified_tables.add(table_name)
        try:
            sys.stderr.write(f"[LOGGER DB TABLE ERROR] Failed ensuring table {table_name}: {table_exc}\n")
            sys.stderr.flush()
        except Exception:
            pass


# ============================================================
# Write Handlers
# ============================================================

def _log_to_file(log_data: Dict[str, Any]) -> bool:
    """Write log entry to JSONL file and stream to stdout/stderr for Docker logging."""
    try:
        log_file_path = _get_active_log_file()
        target_dir = os.path.dirname(log_file_path)
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)

        raw_line = json.dumps(log_data, default=str, ensure_ascii=False)
        with open(log_file_path, "a", encoding="utf-8") as f:
            f.write(raw_line + "\n")

        # Standard stdout/stderr stream per Docker deployment standards
        level_str = str(log_data.get("level", "")).upper()
        stream = sys.stderr if level_str == "ERROR" else sys.stdout
        stream.write(raw_line + "\n")
        stream.flush()

        return True
    except Exception:
        return False


def _log_to_db(
    timestamp: datetime,
    run_id: str,
    snapshot_id: Optional[Any],
    level: str,
    event: str,
    component: str,
    extra_data: Dict[str, Any],
) -> bool:
    """Insert log entry into PostgreSQL table."""
    with _db_lock:
        try:
            conn = _get_db_connection()
            if conn is None:
                return False

            raw_table = getattr(log_config, "LOG_TABLE_NAME", "public.pipeline_logs")
            table_name = raw_table.strip().strip("'\"") if isinstance(raw_table, str) else "public.pipeline_logs"
            if not _SAFE_IDENTIFIER_RE.match(table_name):
                return False

            _ensure_table_exists(conn, table_name)

            # Convert numeric snapshot_id if possible
            snap_val = snapshot_id
            if snap_val is not None:
                try:
                    snap_val = int(snap_val)
                except (ValueError, TypeError):
                    snap_val = None

            details_json = json.dumps(extra_data, default=str, ensure_ascii=False)

            def _execute_insert(target_conn: Any, col: str, current_snap: Optional[int]) -> bool:
                insert_sql = f"""
                    INSERT INTO {table_name} (timestamp, run_id, snapshot_id, level, event, component, {col})
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                """
                params = (
                    timestamp,
                    run_id,
                    current_snap,
                    str(level or "INFO"),
                    str(event or "unknown"),
                    str(component or "unknown"),
                    details_json,
                )
                with target_conn.cursor() as cursor:
                    cursor.execute(insert_sql, params)
                return True

            primary_col = getattr(log_config, "LOG_JSON_COLUMN", "details")
            candidate_cols = [primary_col]
            alt_col = "extra_data" if primary_col == "details" else "details"
            if alt_col not in candidate_cols:
                candidate_cols.append(alt_col)

            for col in candidate_cols:
                try:
                    return _execute_insert(conn, col, snap_val)
                except Exception as insert_exc:
                    err_msg = str(insert_exc).lower()

                    # If column does not exist, try the alternate column name
                    if f'column "{col}"' in err_msg or (col in err_msg and "does not exist" in err_msg):
                        continue

                    # If foreign key violation on snapshot_id, retry with snapshot_id=None
                    if "foreign key" in err_msg and "snapshot_id" in err_msg and snap_val is not None:
                        try:
                            return _execute_insert(conn, col, None)
                        except Exception:
                            pass

                    try:
                        sys.stderr.write(f"[LOGGER DB INSERT ERROR] {insert_exc}\n")
                        sys.stderr.flush()
                    except Exception:
                        pass

                    # Reconnect once on connection failure
                    _reset_db_connection(reset_cooldown=True)
                    conn = _get_db_connection()
                    if conn is not None:
                        try:
                            return _execute_insert(conn, col, snap_val)
                        except Exception as retry_exc:
                            if "foreign key" in str(retry_exc).lower() and snap_val is not None:
                                try:
                                    return _execute_insert(conn, col, None)
                                except Exception:
                                    pass
                            try:
                                sys.stderr.write(f"[LOGGER DB RETRY ERROR] {retry_exc}\n")
                                sys.stderr.flush()
                            except Exception:
                                pass
                    return False

            return False

        except Exception as outer_db_exc:
            try:
                sys.stderr.write(f"[LOGGER DB OP ERROR] {outer_db_exc}\n")
                sys.stderr.flush()
            except Exception:
                pass
            _reset_db_connection(reset_cooldown=False)
            return False


# ============================================================
# Main Logging Dispatcher
# ============================================================

def log_event(
    level: str = "INFO",
    event: str = "unknown",
    component: str = "unknown",
    **kwargs: Any,
) -> None:
    """
    Log an event to configured destinations (JSON file, DB, or both).

    Guarantees strict failure isolation: this function will never raise an exception.
    """
    global _in_log_event

    # Recursion guard to prevent infinite re-entrant loops
    if _in_log_event:
        return

    _in_log_event = True
    try:
        # Determine effective run_id and snapshot_id
        run_id = kwargs.pop("run_id", None) or _current_run_id or "unknown-run"
        snapshot_id = kwargs.pop("snapshot_id", None) if "snapshot_id" in kwargs else _current_snapshot_id

        now_utc = datetime.now(timezone.utc)
        now_iso = datetime.now().isoformat(timespec="seconds")

        # Prepare JSON payload matching original log format
        file_log_data = {
            "timestamp": now_iso,
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "level": level or "INFO",
            "event": event or "unknown",
            "component": component or "unknown",
        }
        file_log_data.update(kwargs)

        raw_dest = getattr(log_config, "LOG_DESTINATION", "both")
        dest = raw_dest.strip().strip("'\"").lower() if isinstance(raw_dest, str) else "both"
        fallback_on_db_error = getattr(log_config, "FALLBACK_TO_FILE_ON_DB_ERROR", True)

        if dest in _JSON_DESTS:
            _log_to_file(file_log_data)

        elif dest in _DB_DESTS:
            success = _log_to_db(
                timestamp=now_utc,
                run_id=run_id,
                snapshot_id=snapshot_id,
                level=level,
                event=event,
                component=component,
                extra_data=kwargs,
            )
            if not success and fallback_on_db_error:
                _log_to_file(file_log_data)

        elif dest in _BOTH_DESTS:
            _log_to_file(file_log_data)
            _log_to_db(
                timestamp=now_utc,
                run_id=run_id,
                snapshot_id=snapshot_id,
                level=level,
                event=event,
                component=component,
                extra_data=kwargs,
            )

        else:
            # Safe default fallback for any unrecognized destination
            _log_to_file(file_log_data)

    except Exception:
        # Strict failure isolation: Logger NEVER crashes the caller
        pass
    finally:
        _in_log_event = False
