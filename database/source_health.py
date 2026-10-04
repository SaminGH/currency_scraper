import logs.logger as logger
from psycopg2.extras import execute_values

from .connection import get_connection
from .lookup import get_source_ids


def save_source_health(snapshot_id, source_status, connection=None):
    db = connection or get_connection()
    if not snapshot_id:
        raise ValueError("snapshot_id is required")
    if not isinstance(source_status, dict):
        raise ValueError("source_status must be a dict")
    source_ids = get_source_ids(db)
    rows = []
    for source_name, data in source_status.items():
        if source_name not in source_ids:
            raise ValueError(f"unknown_source: {source_name}")
        if not isinstance(data, dict):
            raise ValueError(f"invalid_source_status: {source_name}")
        status = data.get("status")
        if status not in ("success", "partial", "failed"):
            raise ValueError(f"invalid_source_status_value: {source_name}:{status}")
        rows.append((snapshot_id, source_ids[source_name], status, data.get("failure_reason"), data.get("currencies_received", 0)))
    if rows:
        with db.cursor() as cursor:
            execute_values(cursor, """
                INSERT INTO public.snapshot_source_status
                    (snapshot_id, source_id, status, failure_reason, currencies_received)
                VALUES %s
                ON CONFLICT (snapshot_id, source_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    failure_reason = EXCLUDED.failure_reason,
                    currencies_received = EXCLUDED.currencies_received
            """, rows)
    logger.log_event(level="INFO", event="source_status_saved", component="database", snapshot_id=snapshot_id, sources=len(rows))
    return len(rows)
