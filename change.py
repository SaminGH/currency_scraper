from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import database
import logs.logger as logger


def _extract_price(val: Any) -> Optional[float]:
    """Extract float price from either a numeric primitive, string, or nested dictionary."""
    if val is None:
        return None
    if isinstance(val, dict):
        val = val.get("price")
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        # Normalize Persian/Arabic digits, strip commas, whitespace, and symbols
        s = val.strip()
        trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩،", "01234567890123456789,")
        s = s.translate(trans).replace(",", "")
        try:
            return float(s)
        except (TypeError, ValueError):
            return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _format_change_pct(
    current_price: Optional[float],
    previous_price: Optional[float]
) -> Tuple[Optional[float], Optional[str]]:
    """
    Calculate price difference and formatted percentage change.

    Formula: ((current_price - previous_price) / previous_price) * 100
    Format: Explicit sign and 2 decimal places (e.g. '+0.01%', '-0.05%', '0.00%').

    Returns:
        (price_change, change_24h_str)
    """
    if current_price is None or previous_price is None:
        return None, None
    try:
        cur = float(current_price)
        prev = float(previous_price)
        if prev == 0:
            return None, None

        price_diff = cur - prev
        price_change = 0.0 if abs(price_diff) < 1e-9 else round(price_diff, 4)
        pct = (price_diff / prev) * 100.0

        formatted = f"{pct:.2f}"
        if formatted in ("0.00", "-0.00") or abs(pct) < 1e-9:
            pct_str = "0.00%"
        elif not formatted.startswith("-"):
            pct_str = f"+{formatted}%"
        else:
            pct_str = f"{formatted}%"

        return price_change, pct_str
    except (TypeError, ValueError, ZeroDivisionError):
        return None, None


def _get_snapshot_rates(cursor, snapshot_id: int) -> Dict[str, float]:
    """Fetch currency rates for a snapshot from published_rates, with fallback to aggregated_rates."""
    rates: Dict[str, float] = {}
    if not snapshot_id:
        return rates

    # 1. Primary source: published_rates
    cursor.execute("""
        SELECT c.code, pr.price
        FROM public.published_rates pr
        JOIN public.currencies c ON c.id = pr.currency_id
        WHERE pr.snapshot_id = %s
    """, (snapshot_id,))
    for code, price in cursor.fetchall():
        p = _extract_price(price)
        if p is not None:
            rates[code] = p

    # 2. Fallback source: aggregated_rates if published_rates is empty
    if not rates:
        cursor.execute("""
            SELECT c.code, a.price
            FROM public.aggregated_rates a
            JOIN public.currencies c ON c.id = a.currency_id
            WHERE a.snapshot_id = %s
        """, (snapshot_id,))
        for code, price in cursor.fetchall():
            p = _extract_price(price)
            if p is not None:
                rates[code] = p

    return rates


def calculate_daily_change_and_range(
    snapshot_id: Optional[int] = None,
    current_rates: Optional[Dict[str, Any]] = None,
    connection: Optional[Any] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Calculates 24h price change, price change percentage, 24h high, and 24h low prices
    relative to the midnight snapshots.

    Returns:
        dict: {
            "USD": {
                "price_change": 500.0,
                "change_24h": "+0.01%",
                "high_24h": 60500.0,
                "low_24h": 59800.0
            },
            ...
        }
    """
    db = connection or database.get_connection()
    savepoint = "change_calculation"

    try:
        logger.log_event(
            level="INFO",
            event="change_calculation_started",
            component="change",
            snapshot_id=snapshot_id,
        )

        with db.cursor() as cursor:
            cursor.execute(f"SAVEPOINT {savepoint}")

            # ------------------------------------------------------------------
            # 1. Determine reference timestamp and midnight comparison windows
            # ------------------------------------------------------------------
            ref_time: Optional[datetime] = None
            snapshot_started_at: Optional[datetime] = None

            if snapshot_id:
                cursor.execute(
                    "SELECT started_at FROM public.snapshots WHERE id = %s",
                    (snapshot_id,)
                )
                row = cursor.fetchone()
                if row and row[0] is not None:
                    snapshot_started_at = row[0]
                    ref_time = snapshot_started_at

            if ref_time is None:
                ref_time = datetime.now()

            # Preserve the tzinfo (naive or aware) of ref_time for consistent DB queries
            today_midnight = ref_time.replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_midnight = today_midnight - timedelta(days=1)
            tomorrow_midnight = today_midnight + timedelta(days=1)

            # ------------------------------------------------------------------
            # 2. Today's Baseline Snapshot selection
            # ------------------------------------------------------------------
            cursor.execute("""
                SELECT id, started_at
                FROM public.snapshots
                WHERE status IN ('completed', 'completed_with_warnings', 'partial')
                  AND started_at >= %s
                  AND started_at < %s
                ORDER BY started_at ASC
                LIMIT 1
            """, (today_midnight, tomorrow_midnight))
            today_row = cursor.fetchone()

            today_snapshot_id: Optional[int] = None
            today_snapshot_time: Optional[datetime] = None

            if today_row:
                today_snapshot_id, today_snapshot_time = today_row[0], today_row[1]
                if (today_snapshot_time.hour != 0 or
                    today_snapshot_time.minute != 0 or
                    today_snapshot_time.second != 0):
                    logger.log_event(
                        level="WARNING",
                        event="change_fallback_snapshot_used",
                        component="change",
                        baseline="today",
                        snapshot_id=today_snapshot_id,
                        started_at=today_snapshot_time.isoformat() if hasattr(today_snapshot_time, "isoformat") else str(today_snapshot_time),
                    )
            elif (snapshot_id and snapshot_started_at and
                  snapshot_started_at >= today_midnight and
                  snapshot_started_at < tomorrow_midnight):
                today_snapshot_id = snapshot_id
                today_snapshot_time = snapshot_started_at
                if (today_snapshot_time.hour != 0 or
                    today_snapshot_time.minute != 0 or
                    today_snapshot_time.second != 0):
                    logger.log_event(
                        level="WARNING",
                        event="change_fallback_snapshot_used",
                        component="change",
                        baseline="today_current",
                        snapshot_id=today_snapshot_id,
                        started_at=today_snapshot_time.isoformat() if hasattr(today_snapshot_time, "isoformat") else str(today_snapshot_time),
                    )
            else:
                logger.log_event(
                    level="WARNING",
                    event="change_baseline_snapshot_missing",
                    component="change",
                    baseline="today",
                    snapshot_id=snapshot_id,
                )

            # ------------------------------------------------------------------
            # 3. Yesterday's Baseline Snapshot selection
            # ------------------------------------------------------------------
            cursor.execute("""
                SELECT id, started_at
                FROM public.snapshots
                WHERE status IN ('completed', 'completed_with_warnings', 'partial')
                  AND started_at >= %s
                  AND started_at < %s
                ORDER BY started_at ASC
                LIMIT 1
            """, (yesterday_midnight, today_midnight))
            yesterday_row = cursor.fetchone()

            yesterday_snapshot_id: Optional[int] = None
            yesterday_snapshot_time: Optional[datetime] = None

            if yesterday_row:
                yesterday_snapshot_id, yesterday_snapshot_time = yesterday_row[0], yesterday_row[1]
                if (yesterday_snapshot_time.hour != 0 or
                    yesterday_snapshot_time.minute != 0 or
                    yesterday_snapshot_time.second != 0):
                    logger.log_event(
                        level="WARNING",
                        event="change_fallback_snapshot_used",
                        component="change",
                        baseline="yesterday",
                        snapshot_id=yesterday_snapshot_id,
                        started_at=yesterday_snapshot_time.isoformat() if hasattr(yesterday_snapshot_time, "isoformat") else str(yesterday_snapshot_time),
                    )
            else:
                # Fallback to the latest completed snapshot prior to today_midnight
                cursor.execute("""
                    SELECT id, started_at
                    FROM public.snapshots
                    WHERE status IN ('completed', 'completed_with_warnings', 'partial')
                      AND started_at < %s
                    ORDER BY started_at DESC
                    LIMIT 1
                """, (today_midnight,))
                prior_row = cursor.fetchone()
                if prior_row:
                    yesterday_snapshot_id, yesterday_snapshot_time = prior_row[0], prior_row[1]
                    logger.log_event(
                        level="WARNING",
                        event="change_fallback_snapshot_used",
                        component="change",
                        baseline="yesterday_prior",
                        snapshot_id=yesterday_snapshot_id,
                        started_at=yesterday_snapshot_time.isoformat() if hasattr(yesterday_snapshot_time, "isoformat") else str(yesterday_snapshot_time),
                    )
                else:
                    logger.log_event(
                        level="WARNING",
                        event="change_baseline_snapshot_missing",
                        component="change",
                        baseline="yesterday",
                        snapshot_id=snapshot_id,
                    )

            # ------------------------------------------------------------------
            # 4. Fetch previous baseline rates (yesterday)
            # ------------------------------------------------------------------
            previous_rates: Dict[str, float] = {}
            if yesterday_snapshot_id:
                previous_rates = _get_snapshot_rates(cursor, yesterday_snapshot_id)

            # ------------------------------------------------------------------
            # 5. Determine current rates
            # ------------------------------------------------------------------
            current_rates_map: Dict[str, Optional[float]] = {}
            if current_rates is not None:
                if not isinstance(current_rates, dict):
                    raise ValueError(f"current_rates must be a dict, got {type(current_rates).__name__}")
                for curr, val in current_rates.items():
                    current_rates_map[curr] = _extract_price(val)
            else:
                if snapshot_id:
                    current_rates_map = _get_snapshot_rates(cursor, snapshot_id)
                if not current_rates_map and today_snapshot_id:
                    current_rates_map = _get_snapshot_rates(cursor, today_snapshot_id)

            # ------------------------------------------------------------------
            # 6. Fetch 24h High and Low extremes from published_rates
            # ------------------------------------------------------------------
            extremes: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
            if yesterday_snapshot_time:
                window_start = yesterday_snapshot_time
                window_end = today_snapshot_time or ref_time
                if window_start > window_end:
                    window_start, window_end = window_end, window_start

                cursor.execute("""
                    SELECT c.code, MAX(pr.price), MIN(pr.price)
                    FROM public.published_rates pr
                    JOIN public.snapshots s ON s.id = pr.snapshot_id
                    JOIN public.currencies c ON c.id = pr.currency_id
                    WHERE s.started_at >= %s
                      AND s.started_at <= %s
                    GROUP BY c.code
                """, (window_start, window_end))
                for code, max_p, min_p in cursor.fetchall():
                    extremes[code] = (_extract_price(max_p), _extract_price(min_p))

            # ------------------------------------------------------------------
            # 7. Aggregate active currencies & compute per-currency metrics
            # ------------------------------------------------------------------
            cursor.execute("SELECT code FROM public.currencies WHERE is_active = TRUE")
            active_currencies = {row[0] for row in cursor.fetchall()}
            all_currencies = (
                active_currencies
                | set(current_rates_map.keys())
                | set(previous_rates.keys())
                | set(extremes.keys())
            )

            results: Dict[str, Dict[str, Any]] = {}
            calculated = 0
            unavailable = 0

            for code in sorted(all_currencies):
                cur_price = current_rates_map.get(code)
                prev_price = previous_rates.get(code)

                price_change, change_24h_str = _format_change_pct(cur_price, prev_price)

                if change_24h_str is not None:
                    calculated += 1
                else:
                    unavailable += 1

                db_high, db_low = extremes.get(code, (None, None))
                candidates = [p for p in (db_high, db_low, cur_price) if p is not None]
                high_24h = max(candidates) if candidates else None
                low_24h = min(candidates) if candidates else None

                results[code] = {
                    "price_change": price_change,
                    "change_24h": change_24h_str,
                    "high_24h": high_24h,
                    "low_24h": low_24h,
                }

            cursor.execute(f"RELEASE SAVEPOINT {savepoint}")

        logger.log_event(
            level="INFO",
            event="change_calculation_completed",
            component="change",
            snapshot_id=snapshot_id,
            yesterday_snapshot_id=yesterday_snapshot_id,
            today_snapshot_id=today_snapshot_id,
            currencies_total=len(results),
            calculated=calculated,
            unavailable=unavailable,
        )
        return results

    except Exception as error:
        try:
            with db.cursor() as cursor:
                cursor.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                cursor.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception:
            pass
        logger.log_event(
            level="ERROR",
            event="change_calculation_failed",
            component="change",
            snapshot_id=snapshot_id,
            reason=str(error),
        )
        return {}


def calculate_change_24h(
    snapshot_id: Optional[int] = None,
    current_rates: Optional[Dict[str, Any]] = None,
    connection: Optional[Any] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Backwards-compatible alias for calculate_daily_change_and_range.
    """
    return calculate_daily_change_and_range(
        snapshot_id=snapshot_id,
        current_rates=current_rates,
        connection=connection,
    )


__all__ = [
    "calculate_daily_change_and_range",
    "calculate_change_24h",
]
