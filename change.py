from datetime import datetime, timedelta

import logs.logger as logger
import database


CHANGE_HOURS = 24
CHANGE_RUN_HOUR = 0
CHANGE_RUN_MINUTE = 0


def _calculate_change(current_price, previous_price):
    try:
        if current_price is None or previous_price is None:
            return None
        current = float(current_price)
        previous = float(previous_price)
        if previous == 0:
            return None
        return ((current - previous) / previous) * 100
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def calculate_change_24h(snapshot_id, current_rates=None, connection=None):
    """Calculate 24h change from prepared current rates and the prior snapshot."""
    if not snapshot_id:
        raise ValueError("snapshot_id is required")
    db = connection or database.get_connection()
    try:
        logger.log_event(level="INFO", event="change_calculation_started", component="change", snapshot_id=snapshot_id)
        with db.cursor() as cursor:
            cursor.execute("SELECT started_at FROM public.snapshots WHERE id = %s", (snapshot_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"snapshot_not_found: {snapshot_id}")
            current_snapshot_time = row[0]
            target_time = current_snapshot_time - timedelta(hours=CHANGE_HOURS)
            cursor.execute("""
                SELECT id, started_at FROM public.snapshots
                WHERE id != %s
                  AND status IN ('completed','completed_with_warnings','partial')
                  AND started_at <= %s
                ORDER BY started_at DESC LIMIT 1
            """, (snapshot_id, target_time))
            previous_row = cursor.fetchone()
            if not previous_row:
                logger.log_event(level="WARNING", event="change_previous_snapshot_missing", component="change", snapshot_id=snapshot_id, target_time=target_time.isoformat())
                return {}
            previous_snapshot_id, previous_snapshot_time = previous_row
            cursor.execute("""
                SELECT c.code, a.price
                FROM public.aggregated_rates a
                JOIN public.currencies c ON c.id = a.currency_id
                WHERE a.snapshot_id = %s
            """, (previous_snapshot_id,))
            previous_rates = {code: price for code, price in cursor.fetchall()}

        if current_rates is None:
            current_rates = {}
            with db.cursor() as cursor:
                cursor.execute("""
                    SELECT c.code, a.price
                    FROM public.aggregated_rates a
                    JOIN public.currencies c ON c.id = a.currency_id
                    WHERE a.snapshot_id = %s
                """, (snapshot_id,))
                current_rates = {code: price for code, price in cursor.fetchall()}
        elif isinstance(current_rates, dict):
            current_rates = {
                currency: data.get("price") if isinstance(data, dict) else data
                for currency, data in current_rates.items()
            }
        else:
            raise ValueError("current_rates must be a dict")

        results = {}
        calculated = 0
        unavailable = 0
        for currency, current_price in current_rates.items():
            change = _calculate_change(current_price, previous_rates.get(currency))
            if change is None:
                unavailable += 1
            else:
                calculated += 1
            results[currency] = {"price": current_price, "change_24h": change}

        logger.log_event(level="INFO", event="change_calculation_completed", component="change", snapshot_id=snapshot_id, previous_snapshot_id=previous_snapshot_id, current_snapshot_time=current_snapshot_time.isoformat(), previous_snapshot_time=previous_snapshot_time.isoformat(), currencies_total=len(current_rates), calculated=calculated, unavailable=unavailable)
        return results
    except Exception as error:
        logger.log_event(level="ERROR", event="change_calculation_failed", component="change", snapshot_id=snapshot_id, reason=str(error))
        return {}
