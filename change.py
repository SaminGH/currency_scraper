from datetime import date, datetime, timedelta
import math
from typing import Any, Dict, Optional, Tuple

import database
import logs.logger as logger


# Module-level cache for today's daily percentage change:
# Key: datetime.date (the calendar date of the snapshot)
# Value: Dict[currency_code, Dict[str, Any]] containing "price_change" and "change_24h"
_DAILY_CHANGE_CACHE: Dict[date, Dict[str, Dict[str, Any]]] = {}


def clear_daily_change_cache() -> None:
    """Clear the in-memory daily change cache (useful for testing or manual resets)."""
    _DAILY_CHANGE_CACHE.clear()


def _extract_price(val: Any) -> Optional[float]:
    """Extract float price from either a numeric primitive, string, or nested dictionary."""
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, dict):
        val = val.get("price")
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        f_val = float(val)
        if math.isnan(f_val) or math.isinf(f_val) or f_val <= 0:
            return None
        return f_val
    if isinstance(val, str):
        # Normalize Persian/Arabic digits, strip commas, whitespace, and symbols
        s = val.strip()
        trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩،", "01234567890123456789,")
        s = s.translate(trans).replace(",", "")
        try:
            f_val = float(s)
            if math.isnan(f_val) or math.isinf(f_val) or f_val <= 0:
                return None
            return f_val
        except (TypeError, ValueError):
            return None
    try:
        f_val = float(val)
        if math.isnan(f_val) or math.isinf(f_val) or f_val <= 0:
            return None
        return f_val
    except (TypeError, ValueError):
        return None


def _format_pct_value(pct: Any) -> Optional[str]:
    """
    Format a numeric percentage into a standard string representation:
    e.g. 0.0 -> '0.00%', 0.01 -> '+0.01%', -0.05 -> '-0.05%'.
    """
    if pct is None or isinstance(pct, bool):
        return None
    try:
        if isinstance(pct, str):
            pct = pct.replace("%", "").strip()
        val = float(pct)
        if math.isnan(val) or math.isinf(val):
            return None
        formatted = f"{val:.2f}"
        if formatted in ("0.00", "-0.00") or abs(val) < 1e-9:
            return "0.00%"
        elif not formatted.startswith("-"):
            return f"+{formatted}%"
        else:
            return f"{formatted}%"
    except (TypeError, ValueError):
        return None


def _format_change_pct(
    current_price: Optional[float],
    previous_price: Optional[float],
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
    if isinstance(current_price, bool) or isinstance(previous_price, bool):
        return None, None
    try:
        cur = float(current_price)
        prev = float(previous_price)
        if math.isnan(cur) or math.isnan(prev) or math.isinf(cur) or math.isinf(prev):
            return None, None
        if prev <= 0 or cur <= 0:
            return None, None

        price_diff = cur - prev
        price_change = 0.0 if abs(price_diff) < 1e-9 else round(price_diff, 4)
        if price_change == 0.0:
            price_change = 0.0
        pct = (price_diff / prev) * 100.0

        pct_str = _format_pct_value(pct)
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

    # 2. Supplementary source: aggregated_rates for any currencies not found in published_rates
    cursor.execute("""
        SELECT c.code, a.price
        FROM public.aggregated_rates a
        JOIN public.currencies c ON c.id = a.currency_id
        WHERE a.snapshot_id = %s
    """, (snapshot_id,))
    for code, price in cursor.fetchall():
        if code not in rates:
            p = _extract_price(price)
            if p is not None:
                rates[code] = p

    return rates


def _find_yesterday_baseline_id(
    cursor,
    yesterday_midnight: datetime,
    today_midnight: datetime,
    snapshot_id: Optional[int] = None,
    emit_warnings: bool = True,
) -> Optional[int]:
    """
    Find yesterday's baseline snapshot ID:
    1. First snapshot in [yesterday_midnight, today_midnight)
    2. Fallback to latest snapshot prior to today_midnight
    """
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

    if yesterday_row:
        return yesterday_row[0]

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
        prior_id, prior_time = prior_row[0], prior_row[1]
        if emit_warnings:
            logger.log_event(
                level="WARNING",
                event="change_fallback_snapshot_used",
                component="change",
                baseline="yesterday_prior",
                snapshot_id=prior_id,
                started_at=prior_time.isoformat() if hasattr(prior_time, "isoformat") else str(prior_time),
            )
        return prior_id

    if emit_warnings:
        logger.log_event(
            level="WARNING",
            event="change_baseline_snapshot_missing",
            component="change",
            baseline="yesterday",
            snapshot_id=snapshot_id,
        )
    return None


def calculate_daily_change(
    snapshot_id: Optional[int] = None,
    current_rates: Optional[Dict[str, Any]] = None,
    connection: Optional[Any] = None,
    ref_time: Optional[datetime] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Calculate fixed daily percentage change for today.

    1. Calculated at the first available snapshot of today comparing the first
       available snapshot of today (>= today 00:00:00) against the first available
       snapshot of yesterday (>= yesterday 00:00:00 and < today 00:00:00, with
       fallback to latest prior snapshot if yesterday is missing).
    2. Caches the daily change in-memory for the current calendar date so subsequent
       snapshots during today carry forward the values without heavy queries or warnings.
    3. If restarted mid-day and cache is empty, falls back to fetching today's daily
       change from today's first completed snapshot in the database.

    Returns:
        dict: {
            "USD": {
                "price_change": 500.0,
                "change_24h": "+0.01%"
            },
            ...
        }
    """
    db = connection or database.get_connection()

    # Determine reference timestamp
    if ref_time is None and snapshot_id:
        try:
            with db.cursor() as cursor:
                cursor.execute(
                    "SELECT started_at FROM public.snapshots WHERE id = %s",
                    (snapshot_id,)
                )
                row = cursor.fetchone()
                if row and row[0] is not None:
                    ref_time = row[0]
        except Exception:
            ref_time = None

    if ref_time is None:
        ref_time = datetime.now()

    ref_date = ref_time.date()

    # Fast path: Check in-memory cache for today's date
    if ref_date in _DAILY_CHANGE_CACHE:
        cached = _DAILY_CHANGE_CACHE[ref_date]
        results = dict(cached)
        if current_rates and isinstance(current_rates, dict):
            for code in current_rates:
                if code not in results:
                    entry = {"price_change": None, "change_24h": None}
                    results[code] = entry
                    cached[code] = entry
        return results

    savepoint = "daily_change_calc"
    try:
        with db.cursor() as cursor:
            cursor.execute(f"SAVEPOINT {savepoint}")

            today_midnight = ref_time.replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_midnight = today_midnight - timedelta(days=1)
            tomorrow_midnight = today_midnight + timedelta(days=1)

            # Check if an earlier completed snapshot exists for today (Mid-day restart check)
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

            results: Dict[str, Dict[str, Any]] = {}
            calculated = 0
            unavailable = 0

            # ------------------------------------------------------------------
            # Scenario A: Mid-day restart (earlier completed snapshot found today)
            # ------------------------------------------------------------------
            if today_row and (snapshot_id is None or today_row[0] != snapshot_id):
                first_today_snapshot_id = today_row[0]

                # Fetch yesterday's baseline snapshot rates to allow reconstructing price_change
                yesterday_snapshot_id = _find_yesterday_baseline_id(
                    cursor, yesterday_midnight, today_midnight, snapshot_id=first_today_snapshot_id, emit_warnings=False
                )
                yesterday_rates = _get_snapshot_rates(cursor, yesterday_snapshot_id) if yesterday_snapshot_id else {}

                # 1. Primary: fetch published_rates of today's first snapshot
                cursor.execute("""
                    SELECT c.code, pr.price, pr.change_24h
                    FROM public.published_rates pr
                    JOIN public.currencies c ON c.id = pr.currency_id
                    WHERE pr.snapshot_id = %s
                """, (first_today_snapshot_id,))
                published_rows = cursor.fetchall()
                today_published = {code: (price, change_24h) for code, price, change_24h in published_rows}

                # 2. Supplementary: fetch first snapshot rates for unpublishable currencies
                today_first_rates = _get_snapshot_rates(cursor, first_today_snapshot_id)

                cursor.execute("SELECT code FROM public.currencies WHERE is_active = TRUE")
                active_currencies = {r[0] for r in cursor.fetchall()}
                all_curr = active_currencies | set(today_published.keys()) | set(today_first_rates.keys())
                if current_rates and isinstance(current_rates, dict):
                    all_curr |= set(current_rates.keys())

                for code in sorted(all_curr):
                    if code in today_published:
                        p_raw, change_24h = today_published[code]
                        p = _extract_price(p_raw)
                        change_24h_str = _format_pct_value(change_24h)
                        price_change = None

                        if p is not None and code in yesterday_rates:
                            diff = p - yesterday_rates[code]
                            price_change = 0.0 if abs(diff) < 1e-9 else round(diff, 4)
                        elif p is not None and change_24h is not None:
                            try:
                                pct_val = float(change_24h)
                                if pct_val != -100:
                                    prev_p = p / (1.0 + pct_val / 100.0)
                                    diff = p - prev_p
                                    price_change = 0.0 if abs(diff) < 1e-9 else round(diff, 4)
                            except (TypeError, ValueError, ZeroDivisionError):
                                price_change = None

                        if price_change == 0.0:
                            price_change = 0.0

                        if change_24h_str is not None:
                            calculated += 1
                        else:
                            unavailable += 1

                        results[code] = {
                            "price_change": price_change,
                            "change_24h": change_24h_str,
                        }
                    elif code in today_first_rates:
                        cur_p = today_first_rates.get(code)
                        prev_p = yesterday_rates.get(code)
                        price_change, change_24h_str = _format_change_pct(cur_p, prev_p)
                        if change_24h_str is not None:
                            calculated += 1
                        else:
                            unavailable += 1
                        results[code] = {
                            "price_change": price_change,
                            "change_24h": change_24h_str,
                        }
                    else:
                        unavailable += 1
                        results[code] = {
                            "price_change": None,
                            "change_24h": None,
                        }

                logger.log_event(
                    level="INFO",
                    event="daily_change_restored_from_db",
                    component="change",
                    snapshot_id=snapshot_id,
                    source_snapshot_id=first_today_snapshot_id,
                    currencies=len(results),
                    calculated=calculated,
                    unavailable=unavailable,
                )

            # ------------------------------------------------------------------
            # Scenario B: First snapshot of today
            # ------------------------------------------------------------------
            else:
                yesterday_snapshot_id = _find_yesterday_baseline_id(
                    cursor, yesterday_midnight, today_midnight, snapshot_id=snapshot_id, emit_warnings=True
                )
                previous_rates = _get_snapshot_rates(cursor, yesterday_snapshot_id) if yesterday_snapshot_id else {}

                # Determine current rates for today's first snapshot
                current_rates_map: Dict[str, Optional[float]] = {}
                if current_rates is not None:
                    if not isinstance(current_rates, dict):
                        raise ValueError(f"current_rates must be a dict, got {type(current_rates).__name__}")
                    for curr, val in current_rates.items():
                        current_rates_map[curr] = _extract_price(val)
                elif snapshot_id:
                    current_rates_map = _get_snapshot_rates(cursor, snapshot_id)

                cursor.execute("SELECT code FROM public.currencies WHERE is_active = TRUE")
                active_currencies = {row[0] for row in cursor.fetchall()}
                all_currencies = active_currencies | set(current_rates_map.keys()) | set(previous_rates.keys())

                for code in sorted(all_currencies):
                    cur_price = current_rates_map.get(code)
                    prev_price = previous_rates.get(code)
                    price_change, change_24h_str = _format_change_pct(cur_price, prev_price)

                    if change_24h_str is not None:
                        calculated += 1
                    else:
                        unavailable += 1

                    results[code] = {
                        "price_change": price_change,
                        "change_24h": change_24h_str,
                    }

                logger.log_event(
                    level="INFO",
                    event="daily_change_calculated",
                    component="change",
                    snapshot_id=snapshot_id,
                    yesterday_snapshot_id=yesterday_snapshot_id,
                    currencies_total=len(results),
                    calculated=calculated,
                    unavailable=unavailable,
                )

            # Store in cache unconditionally if results are populated
            if results:
                _DAILY_CHANGE_CACHE[ref_date] = dict(results)
                # Keep cache bounded to last 7 days
                if len(_DAILY_CHANGE_CACHE) > 7:
                    for old_k in sorted(_DAILY_CHANGE_CACHE.keys())[:-7]:
                        _DAILY_CHANGE_CACHE.pop(old_k, None)

            cursor.execute(f"RELEASE SAVEPOINT {savepoint}")

            out = dict(results)
            if current_rates and isinstance(current_rates, dict):
                for code in current_rates:
                    if code not in out:
                        out[code] = {"price_change": None, "change_24h": None}
            return out

    except Exception as error:
        try:
            with db.cursor() as cursor:
                cursor.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                cursor.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception:
            pass
        logger.log_event(
            level="ERROR",
            event="daily_change_failed",
            component="change",
            snapshot_id=snapshot_id,
            reason=str(error),
        )
        return {}


def calculate_daily_high_low(
    snapshot_id: Optional[int] = None,
    current_rates: Optional[Dict[str, Any]] = None,
    connection: Optional[Any] = None,
    ref_time: Optional[datetime] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Calculate today's high and low price extremes for each currency.

    Defined as the high and low prices of the current calendar day (from today 00:00:00
    up to the current snapshot). Dynamically evaluated on each snapshot by querying
    MAX(price) and MIN(price) from public.published_rates for today's snapshots
    (s.started_at >= today_midnight and s.started_at <= current_snapshot_time),
    and merging with the current snapshot's prepared rates (current_rates).

    Returns:
        dict: {
            "USD": {
                "high_24h": 60500.0,
                "low_24h": 59800.0,
                "high": 60500.0,
                "low": 59800.0
            },
            ...
        }
    """
    db = connection or database.get_connection()

    if ref_time is None and snapshot_id:
        try:
            with db.cursor() as cursor:
                cursor.execute(
                    "SELECT started_at FROM public.snapshots WHERE id = %s",
                    (snapshot_id,)
                )
                row = cursor.fetchone()
                if row and row[0] is not None:
                    ref_time = row[0]
        except Exception:
            ref_time = None

    if ref_time is None:
        ref_time = datetime.now()

    today_midnight = ref_time.replace(hour=0, minute=0, second=0, microsecond=0)
    current_snapshot_time = ref_time
    if current_snapshot_time < today_midnight:
        t_start, t_end = current_snapshot_time, today_midnight
    else:
        t_start, t_end = today_midnight, current_snapshot_time

    savepoint = "daily_high_low_calc"
    try:
        with db.cursor() as cursor:
            cursor.execute(f"SAVEPOINT {savepoint}")

            # 1. Query today's published rates extremes
            extremes: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
            cursor.execute("""
                SELECT c.code, MAX(pr.price), MIN(pr.price)
                FROM public.published_rates pr
                JOIN public.snapshots s ON s.id = pr.snapshot_id
                JOIN public.currencies c ON c.id = pr.currency_id
                WHERE s.started_at >= %s
                  AND s.started_at <= %s
                GROUP BY c.code
            """, (t_start, t_end))
            for code, max_p, min_p in cursor.fetchall():
                extremes[code] = (_extract_price(max_p), _extract_price(min_p))

            # 2. Extract current prepared rates
            current_rates_map: Dict[str, Optional[float]] = {}
            if current_rates is not None:
                if not isinstance(current_rates, dict):
                    raise ValueError(f"current_rates must be a dict, got {type(current_rates).__name__}")
                for curr, val in current_rates.items():
                    current_rates_map[curr] = _extract_price(val)
            elif snapshot_id:
                current_rates_map = _get_snapshot_rates(cursor, snapshot_id)

            # 3. Active currencies
            cursor.execute("SELECT code FROM public.currencies WHERE is_active = TRUE")
            active_currencies = {row[0] for row in cursor.fetchall()}

            all_currencies = active_currencies | set(current_rates_map.keys()) | set(extremes.keys())

            results: Dict[str, Dict[str, Any]] = {}
            for code in sorted(all_currencies):
                cur_price = current_rates_map.get(code)
                db_high, db_low = extremes.get(code, (None, None))
                candidates = [
                    p for p in (db_high, db_low, cur_price)
                    if p is not None and not math.isnan(p) and not math.isinf(p) and p > 0
                ]
                high_val = max(candidates) if candidates else None
                low_val = min(candidates) if candidates else None
                results[code] = {
                    "high_24h": high_val,
                    "low_24h": low_val,
                }

            cursor.execute(f"RELEASE SAVEPOINT {savepoint}")

        logger.log_event(
            level="INFO",
            event="daily_high_low_completed",
            component="change",
            snapshot_id=snapshot_id,
            currencies_total=len(results),
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
            event="daily_high_low_failed",
            component="change",
            snapshot_id=snapshot_id,
            reason=str(error),
        )
        return {}


def calculate_daily_change_and_range(
    snapshot_id: Optional[int] = None,
    current_rates: Optional[Dict[str, Any]] = None,
    connection: Optional[Any] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Coordinates and combines daily change calculation and daily high/low range.

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

    ref_time: Optional[datetime] = None
    if snapshot_id:
        try:
            with db.cursor() as cursor:
                cursor.execute(
                    "SELECT started_at FROM public.snapshots WHERE id = %s",
                    (snapshot_id,)
                )
                row = cursor.fetchone()
                if row and row[0] is not None:
                    ref_time = row[0]
        except Exception:
            ref_time = None

    if ref_time is None:
        ref_time = datetime.now()

    try:
        logger.log_event(
            level="INFO",
            event="change_calculation_started",
            component="change",
            snapshot_id=snapshot_id,
        )

        daily_change = calculate_daily_change(
            snapshot_id=snapshot_id,
            current_rates=current_rates,
            connection=db,
            ref_time=ref_time,
        )
        daily_high_low = calculate_daily_high_low(
            snapshot_id=snapshot_id,
            current_rates=current_rates,
            connection=db,
            ref_time=ref_time,
        )

        all_currencies = set(daily_change.keys()) | set(daily_high_low.keys())
        if current_rates and isinstance(current_rates, dict):
            all_currencies.update(current_rates.keys())

        results: Dict[str, Dict[str, Any]] = {}
        calculated = 0
        unavailable = 0

        for code in sorted(all_currencies):
            chg = daily_change.get(code, {})
            hl = daily_high_low.get(code, {})

            price_change = chg.get("price_change")
            change_24h_str = chg.get("change_24h")

            if change_24h_str is not None:
                calculated += 1
            else:
                unavailable += 1

            high_val = hl.get("high_24h")
            low_val = hl.get("low_24h")

            results[code] = {
                "price_change": price_change,
                "change_24h": change_24h_str,
                "high_24h": high_val,
                "low_24h": low_val,
            }

        logger.log_event(
            level="INFO",
            event="change_calculation_completed",
            component="change",
            snapshot_id=snapshot_id,
            currencies_total=len(results),
            calculated=calculated,
            unavailable=unavailable,
        )
        return results

    except Exception as error:
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
    "calculate_daily_change",
    "calculate_daily_high_low",
    "calculate_daily_change_and_range",
    "calculate_change_24h",
    "clear_daily_change_cache",
]
