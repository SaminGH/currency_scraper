import logs.logger as logger

from .connection import get_connection
from .snapshot import complete_snapshot
from .source_health import save_source_health
from .source_rates import save_source_rates
from .aggregated_rates import save_aggregated_rates
from .published_rates import save_published_rates
from .summary import save_snapshot_summary


def _validate_status(status):
    if status not in ("completed", "completed_with_warnings", "partial", "failed"):
        raise ValueError(f"invalid snapshot status: {status}")


def publish_snapshot(*, snapshot_id, run_id, source_status, raw_prices, removed_sources, aggregated_rates, published_rates, summary, snapshot_status, connection=None):
    """Persist one prepared snapshot atomically and commit it."""
    db = connection or get_connection()
    _validate_status(snapshot_status)
    if not snapshot_id:
        raise ValueError("snapshot_id is required")

    logger.log_event(level="INFO", event="publisher_started", component="publisher", snapshot_id=snapshot_id)
    savepoint = "publisher_write"
    try:
        with db.cursor() as cursor:
            cursor.execute(f"SAVEPOINT {savepoint}")

        source_health_result = save_source_health(snapshot_id, source_status, connection=db)
        source_rates_result = save_source_rates(snapshot_id, raw_prices, removed_sources=removed_sources, connection=db)
        aggregated_result = save_aggregated_rates(snapshot_id, aggregated_rates, connection=db)

        published_count = 0
        if snapshot_status in ("completed", "completed_with_warnings"):
            published_count = save_published_rates(snapshot_id, published_rates, connection=db)

        save_snapshot_summary(snapshot_id, summary, connection=db)
        complete_snapshot(snapshot_id, run_id, status=snapshot_status, connection=db)

        with db.cursor() as cursor:
            cursor.execute(f"RELEASE SAVEPOINT {savepoint}")
        db.commit()

        result = {
            "snapshot_id": snapshot_id,
            "status": snapshot_status,
            "source_health": source_health_result,
            "source_rates": source_rates_result,
            "aggregated_rates": aggregated_result,
            "published_rates": published_count,
        }
        logger.log_event(level="INFO", event="publisher_committed", component="publisher", snapshot_id=snapshot_id, status=snapshot_status, published_rates=published_count)
        return result

    except Exception as error:
        try:
            with db.cursor() as cursor:
                cursor.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            complete_snapshot(snapshot_id, run_id, status="failed", connection=db)
            db.commit()
        except Exception as recovery_error:
            try:
                db.rollback()
            except Exception:
                pass
            logger.log_event(level="ERROR", event="publisher_failure_recovery_failed", component="publisher", snapshot_id=snapshot_id, reason=str(recovery_error))
        logger.log_event(level="ERROR", event="publisher_failed", component="publisher", snapshot_id=snapshot_id, reason=str(error))
        raise


def fail_snapshot(*, snapshot_id, run_id, connection=None):
    """Finalize a snapshot as failed. Publisher remains the transaction owner."""
    db = connection or get_connection()
    try:
        complete_snapshot(snapshot_id, run_id, status="failed", connection=db)
        db.commit()
        logger.log_event(level="INFO", event="publisher_failed_snapshot_committed", component="publisher", snapshot_id=snapshot_id)
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
