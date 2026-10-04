import logs.logger as logger
from psycopg2.extras import execute_values

from .connection import get_connection
from .lookup import get_currency_ids


def save_published_rates(snapshot_id, published_rates, connection=None):
    db = connection or get_connection()
    if not snapshot_id:
        raise ValueError("snapshot_id is required")
    if not isinstance(published_rates, dict):
        raise ValueError("published_rates must be a dict")
    currency_ids = get_currency_ids(db)
    rows = []
    for currency, data in published_rates.items():
        if currency not in currency_ids:
            continue
        if not isinstance(data, dict):
            raise ValueError(f"published_rate_data_is_not_dict: {currency}")
        price = data.get("price")
        if price is None:
            raise ValueError(f"published_price_missing: {currency}")
        sources_total = data.get("sources_total")
        if sources_total is None and isinstance(data.get("source"), str) and "/" in data["source"]:
            try: sources_total = int(data["source"].split("/", 1)[1])
            except ValueError: pass
        if sources_total is None:
            raise ValueError(f"published_sources_total_missing: {currency}")
        sources = data.get("sources", [])
        sources_used = data.get("sources_used", len(sources) if isinstance(sources, list) else 0)
        rows.append((snapshot_id, currency_ids[currency], price, data.get("change_24h"), sources_total, sources_used, data.get("confidence", "unknown")))
    if rows:
        with db.cursor() as cursor:
            execute_values(cursor, """
                INSERT INTO public.published_rates
                    (snapshot_id, currency_id, price, change_24h, sources_total, sources_used, confidence)
                VALUES %s
                ON CONFLICT (snapshot_id, currency_id) DO UPDATE SET
                    price = EXCLUDED.price, change_24h = EXCLUDED.change_24h, sources_total = EXCLUDED.sources_total,
                    sources_used = EXCLUDED.sources_used, confidence = EXCLUDED.confidence
            """, rows)
    logger.log_event(level="INFO", event="published_rates_saved", component="database", snapshot_id=snapshot_id, currencies=len(rows))
    return len(rows)
