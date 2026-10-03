from datetime import datetime

import logger

from .connection import get_connection


def create_snapshot(run_id, connection=None):
    """Insert a running snapshot into the caller-owned transaction."""
    db = connection or get_connection()
    if not run_id:
        raise ValueError("run_id is required")
    try:
        with db.cursor() as cursor:
            cursor.execute("""
                INSERT INTO public.snapshots (run_id, started_at, status)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (run_id, datetime.now(), "running"))
            snapshot_id = cursor.fetchone()[0]
        logger.log_event(level="INFO", event="snapshot_created", component="database", snapshot_id=snapshot_id, run_id=run_id, status="running")
        return snapshot_id
    except Exception as error:
        logger.log_event(level="ERROR", event="snapshot_create_failed", component="database", run_id=run_id, reason=str(error))
        raise


def complete_snapshot(snapshot_id, run_id, status="completed", connection=None):
    db = connection or get_connection()
    if not snapshot_id:
        raise ValueError("snapshot_id is required")
    if status not in ("completed", "completed_with_warnings", "partial", "failed"):
        raise ValueError(f"invalid snapshot status: {status}")
    try:
        with db.cursor() as cursor:
            cursor.execute("""
                UPDATE public.snapshots
                SET completed_at = %s, status = %s
                WHERE id = %s
            """, (datetime.now(), status, snapshot_id))
            if cursor.rowcount != 1:
                raise ValueError(f"snapshot_not_found: {snapshot_id}")
        logger.log_event(level="INFO", event="snapshot_completed", component="database", snapshot_id=snapshot_id, run_id=run_id, status=status)
    except Exception as error:
        logger.log_event(level="ERROR", event="snapshot_complete_failed", component="database", snapshot_id=snapshot_id, run_id=run_id, reason=str(error))
        raise
