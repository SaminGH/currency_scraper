import logger

from .connection import get_connection


def save_snapshot_summary(snapshot_id, summary, connection=None):
    db = connection or get_connection()
    if not snapshot_id:
        raise ValueError("snapshot_id is required")
    if not isinstance(summary, dict):
        raise ValueError("summary must be a dict")
    required = ("status", "sources_attempted", "sources_successful", "sources_failed", "raw_rates", "valid_rates", "outliers", "final_rates", "publishable_rates")
    for field in required:
        if field not in summary:
            raise ValueError(f"summary_field_missing: {field}")
    with db.cursor() as cursor:
        cursor.execute("""
            INSERT INTO public.snapshot_summary
                (snapshot_id, status, sources_attempted, sources_successful, sources_failed, raw_rates, valid_rates, outliers, final_rates, publishable_rates)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (snapshot_id) DO UPDATE SET
                status=EXCLUDED.status, sources_attempted=EXCLUDED.sources_attempted, sources_successful=EXCLUDED.sources_successful,
                sources_failed=EXCLUDED.sources_failed, raw_rates=EXCLUDED.raw_rates, valid_rates=EXCLUDED.valid_rates,
                outliers=EXCLUDED.outliers, final_rates=EXCLUDED.final_rates, publishable_rates=EXCLUDED.publishable_rates
        """, (snapshot_id, summary["status"], summary["sources_attempted"], summary["sources_successful"], summary["sources_failed"], summary["raw_rates"], summary["valid_rates"], summary["outliers"], summary["final_rates"], summary["publishable_rates"]))
    logger.log_event(level="INFO", event="snapshot_summary_saved", component="database", snapshot_id=snapshot_id)
    return True
