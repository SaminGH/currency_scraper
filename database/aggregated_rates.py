import logs.logger as logger
from psycopg2.extras import execute_values

from .connection import get_connection
from .lookup import get_currency_ids


def save_aggregated_rates(snapshot_id, final_prices, connection=None):
    db = connection or get_connection()
    if not snapshot_id:
        raise ValueError("snapshot_id is required")
    if not isinstance(final_prices, dict):
        raise ValueError("final_prices must be a dict")
    currency_ids = get_currency_ids(db)
    rows = []
    for currency, data in final_prices.items():
        if currency not in currency_ids or not isinstance(data, dict):
            continue
        price = data.get("price")
        if price is None:
            continue
        sources = data.get("sources", [])
        if not isinstance(sources, list):
            raise ValueError(f"aggregated_sources_must_be_list: {currency}")
        source_info = data.get("source")
        sources_total = data.get("sources_total")
        if sources_total is None and isinstance(source_info, str) and "/" in source_info:
            try: sources_total = int(source_info.split("/", 1)[1])
            except ValueError: sources_total = None
        if sources_total is None:
            raise ValueError(f"sources_total_missing: {currency}")
        sources_used = data.get("sources_used", len(sources))
        rows.append((snapshot_id, currency_ids[currency], price, sources_total, sources_used, data.get("confidence", "unknown"), data.get("confidence_reason"), data.get("status", "valid"), data.get("publishable", True), data.get("publishability_reason")))
    if rows:
        with db.cursor() as cursor:
            execute_values(cursor, """
                INSERT INTO public.aggregated_rates
                    (snapshot_id, currency_id, price, sources_total, sources_used, confidence, confidence_reason, status, publishable, publishability_reason)
                VALUES %s
                ON CONFLICT (snapshot_id, currency_id) DO UPDATE SET
                    price = EXCLUDED.price, sources_total = EXCLUDED.sources_total, sources_used = EXCLUDED.sources_used,
                    confidence = EXCLUDED.confidence, confidence_reason = EXCLUDED.confidence_reason, status = EXCLUDED.status,
                    publishable = EXCLUDED.publishable, publishability_reason = EXCLUDED.publishability_reason
            """, rows)
    logger.log_event(level="INFO", event="aggregated_rates_saved", component="database", snapshot_id=snapshot_id, currencies=len(rows))
    return len(rows)
