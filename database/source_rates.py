import logs.logger as logger
from psycopg2.extras import execute_values

from .connection import get_connection
from .lookup import get_source_ids, get_currency_ids


def save_source_rates(snapshot_id, raw_prices, removed_sources=None, connection=None):
    db = connection or get_connection()
    if not snapshot_id:
        raise ValueError("snapshot_id is required")
    if not isinstance(raw_prices, dict):
        raise ValueError("raw_prices must be a dict")
    removed_sources = {} if removed_sources is None else removed_sources
    if not isinstance(removed_sources, dict):
        raise ValueError("removed_sources must be a dict")

    source_ids = get_source_ids(db)
    currency_ids = get_currency_ids(db)
    rows = []
    missing = 0
    outliers = 0
    outlier_map = {c: set(s.keys()) if isinstance(s, dict) else set() for c, s in removed_sources.items()}

    for currency, data in raw_prices.items():
        if currency not in currency_ids:
            logger.log_event(level="WARNING", event="unknown_currency_skipped", component="database", snapshot_id=snapshot_id, currency=currency)
            continue
        if not isinstance(data, dict) or not isinstance(data.get("prices", {}), dict):
            continue
        prices = data["prices"]
        for source_name, source_id in source_ids.items():
            price = prices.get(source_name)
            if source_name not in prices or price is None:
                status, rejection_reason = "missing", None
                missing += 1
            elif source_name in outlier_map.get(currency, set()):
                status, rejection_reason = "outlier", "outlier_above_1_percent"
                outliers += 1
            else:
                status, rejection_reason = "valid", None
            rows.append((snapshot_id, source_id, currency_ids[currency], price, status, rejection_reason))

    if rows:
        with db.cursor() as cursor:
            execute_values(cursor, """
                INSERT INTO public.source_rates
                    (snapshot_id, source_id, currency_id, price, status, rejection_reason)
                VALUES %s
                ON CONFLICT (snapshot_id, source_id, currency_id) DO UPDATE SET
                    price = EXCLUDED.price, status = EXCLUDED.status, rejection_reason = EXCLUDED.rejection_reason
            """, rows)
    result = {"inserted": len(rows), "missing": missing, "outliers": outliers}
    logger.log_event(level="INFO", event="source_rates_saved", component="database", snapshot_id=snapshot_id, **result)
    return result
