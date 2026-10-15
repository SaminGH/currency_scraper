"""
Dedicated Deterministic Confidence Score Engine.

Calculates confidence ratings ("HIGH", "MEDIUM", "LOW") strictly based on:
1. Valid sources remaining after validation.
2. Price dispersion (relative spread across valid prices).
3. Data freshness (relative to snapshot_time / execution time).
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

import confidence_config
from confidence_config import ConfidenceConfig, DEFAULT_CONFIG
import logs.logger as logger


def _parse_timestamp(ts: Any) -> Optional[datetime]:
    """Parse various datetime representations into a datetime object."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(ts, str):
        ts_str = ts.strip()
        try:
            return datetime.fromisoformat(ts_str)
        except ValueError:
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y/%m/%d %H:%M:%S",
                "%Y-%m-%d",
            ):
                try:
                    return datetime.strptime(ts_str, fmt)
                except ValueError:
                    continue
    return None


def _calculate_age_seconds(snap_dt: datetime, src_dt: datetime) -> float:
    """Calculate age in seconds between snapshot datetime and source datetime."""
    # Harmonize timezone awareness to avoid TypeError
    if snap_dt.tzinfo is not None and src_dt.tzinfo is None:
        src_dt = src_dt.replace(tzinfo=snap_dt.tzinfo)
    elif snap_dt.tzinfo is None and src_dt.tzinfo is not None:
        snap_dt = snap_dt.replace(tzinfo=src_dt.tzinfo)

    diff = (snap_dt - src_dt).total_seconds()
    return max(0.0, diff)


def calculate_confidence(
    valid_prices: Dict[str, float],
    total_sources: int,
    snapshot_time: Optional[Union[datetime, str]] = None,
    source_timestamps: Optional[Dict[str, Any]] = None,
    config: Optional[ConfidenceConfig] = None,
    currency: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Evaluates quality confidence rating for a single currency rate.

    Parameters:
        valid_prices: Healthy price dictionary {source_name: price} from validator.
        total_sources: Total attempted sources for this currency.
        snapshot_time: Optional timestamp of current pipeline run.
        source_timestamps: Optional dictionary of source timestamps.
        config: Optional ConfidenceConfig override. Defaults to DEFAULT_CONFIG.
        currency: Optional currency code string (e.g. 'USD', 'EUR') for telemetry.

    Returns:
        dict: {
            "rating": "HIGH",  # "HIGH" | "MEDIUM" | "LOW"
            "score_reason": "valid_sources_above_threshold_low_dispersion",
            "metrics": {
                "valid_sources_count": 3,
                "total_sources_count": 4,
                "dispersion_pct": 0.0033
            }
        }
    """
    cfg = config or DEFAULT_CONFIG
    curr = currency or kwargs.get("currency") or kwargs.get("currency_code")

    try:
        # ========================================================
        # 1. Input Sanitization & Validation
        # ========================================================
        if not isinstance(valid_prices, dict):
            raise TypeError("valid_prices_must_be_dict")

        clean_prices: Dict[str, float] = {}
        for source_name, price in valid_prices.items():
            if isinstance(price, (int, float)) and not isinstance(price, bool):
                clean_prices[str(source_name)] = float(price)

        valid_count = len(clean_prices)
        total_sources_count = max(int(total_sources) if isinstance(total_sources, (int, float)) else 0, valid_count)

        # ========================================================
        # 2. Source Count Gate (< 2 yields LOW)
        # ========================================================
        if valid_count < cfg.min_valid_sources_medium:
            score_reason = "insufficient_valid_sources" if valid_count > 0 else "no_valid_sources"
            reason_detail = (
                f"Valid source count ({valid_count}/{total_sources_count}) is below minimum "
                f"threshold ({cfg.min_valid_sources_medium}) required for MEDIUM/HIGH confidence -> rated LOW"
            ) if valid_count > 0 else (
                f"No valid sources available (0/{total_sources_count}) -> rated LOW"
            )

            log_kwargs = {
                "level": "INFO" if valid_count > 0 else "WARNING",
                "event": "confidence_evaluated",
                "component": "confidence",
                "rating": "LOW",
                "score_reason": score_reason,
                "reason_detail": reason_detail,
                "valid_sources": valid_count,
                "total_sources": total_sources_count,
                "dispersion_pct": None,
            }
            if curr:
                log_kwargs["currency"] = curr
            logger.log_event(**log_kwargs)

            return {
                "rating": "LOW",
                "score_reason": score_reason,
                "metrics": {
                    "valid_sources_count": valid_count,
                    "total_sources_count": total_sources_count,
                    "dispersion_pct": None,
                },
            }

        # Determine initial potential rating based on source count
        if valid_count >= cfg.min_valid_sources_high:
            potential_rating = "HIGH"
        else:
            potential_rating = "MEDIUM"

        # ========================================================
        # 3. Dispersion Evaluation (Relative Spread)
        # Dispersion = (Max(P_valid) - Min(P_valid)) / Mean(P_valid)
        # ========================================================
        price_values = list(clean_prices.values())
        mean_price = sum(price_values) / len(price_values)

        if mean_price == 0:
            reason_detail = "Mean price is 0; cannot evaluate dispersion -> rated LOW"
            log_kwargs = {
                "level": "WARNING",
                "event": "confidence_evaluated",
                "component": "confidence",
                "rating": "LOW",
                "score_reason": "mean_price_is_zero",
                "reason_detail": reason_detail,
                "valid_sources": valid_count,
                "total_sources": total_sources_count,
                "dispersion_pct": None,
                "mean_price": 0.0,
            }
            if curr:
                log_kwargs["currency"] = curr
            logger.log_event(**log_kwargs)

            return {
                "rating": "LOW",
                "score_reason": "mean_price_is_zero",
                "metrics": {
                    "valid_sources_count": valid_count,
                    "total_sources_count": total_sources_count,
                    "dispersion_pct": None,
                },
            }

        max_price = max(price_values)
        min_price = min(price_values)
        dispersion = (max_price - min_price) / mean_price

        # Grade rating according to dispersion thresholds
        if potential_rating == "HIGH":
            if dispersion <= cfg.max_dispersion_high:
                current_rating = "HIGH"
                score_reason = "valid_sources_above_threshold_low_dispersion"
                reason_detail = (
                    f"Valid sources ({valid_count}/{total_sources_count}) >= {cfg.min_valid_sources_high} "
                    f"and dispersion ({dispersion:.4%}) <= {cfg.max_dispersion_high:.2%} -> rated HIGH"
                )
            elif dispersion <= cfg.max_dispersion_medium:
                current_rating = "MEDIUM"
                score_reason = "moderate_dispersion_degraded_to_medium"
                reason_detail = (
                    f"Valid sources ({valid_count}/{total_sources_count}) >= {cfg.min_valid_sources_high} "
                    f"but dispersion ({dispersion:.4%}) exceeds high threshold ({cfg.max_dispersion_high:.2%}) "
                    f"(<= {cfg.max_dispersion_medium:.2%}) -> degraded to MEDIUM"
                )
            else:
                current_rating = "LOW"
                score_reason = "excessive_dispersion_degraded_to_low"
                reason_detail = (
                    f"Valid sources ({valid_count}/{total_sources_count}) >= {cfg.min_valid_sources_high} "
                    f"but dispersion ({dispersion:.4%}) exceeds maximum allowable threshold "
                    f"({cfg.max_dispersion_medium:.2%}) -> degraded to LOW"
                )
        else:  # potential_rating == "MEDIUM" (e.g. 2 sources)
            if dispersion <= cfg.max_dispersion_medium:
                current_rating = "MEDIUM"
                score_reason = "two_valid_sources_acceptable_dispersion"
                reason_detail = (
                    f"Valid sources ({valid_count}/{total_sources_count}) == {cfg.min_valid_sources_medium} "
                    f"with acceptable dispersion ({dispersion:.4%} <= {cfg.max_dispersion_medium:.2%}) -> rated MEDIUM"
                )
            else:
                current_rating = "LOW"
                score_reason = "excessive_dispersion_degraded_to_low"
                reason_detail = (
                    f"Valid sources ({valid_count}/{total_sources_count}) == {cfg.min_valid_sources_medium} "
                    f"but dispersion ({dispersion:.4%}) exceeds maximum allowable threshold "
                    f"({cfg.max_dispersion_medium:.2%}) -> degraded to LOW"
                )

        # ========================================================
        # 4. Freshness Evaluation
        # ========================================================
        max_age: Optional[float] = None
        is_stale: bool = False
        if source_timestamps and isinstance(source_timestamps, dict):
            snap_dt = _parse_timestamp(snapshot_time) or datetime.now()
            valid_ages = []
            for src in clean_prices:
                if src in source_timestamps:
                    src_dt = _parse_timestamp(source_timestamps[src])
                    if src_dt:
                        valid_ages.append(_calculate_age_seconds(snap_dt, src_dt))
                elif "timestamp" in source_timestamps:
                    src_dt = _parse_timestamp(source_timestamps["timestamp"])
                    if src_dt:
                        valid_ages.append(_calculate_age_seconds(snap_dt, src_dt))

            if valid_ages:
                max_age = max(valid_ages)
                if max_age > cfg.max_age_seconds:
                    is_stale = True
                    old_rating = current_rating
                    # Degrading tier due to stale data
                    if current_rating == "HIGH":
                        current_rating = "MEDIUM"
                        score_reason = f"{score_reason}_stale_data_degraded_to_medium"
                    elif current_rating == "MEDIUM":
                        current_rating = "LOW"
                        score_reason = f"{score_reason}_stale_data_degraded_to_low"
                    else:
                        score_reason = f"{score_reason}_stale_data"

                    reason_detail += (
                        f"; Stale data: max source age ({max_age:.1f}s) exceeds threshold "
                        f"({cfg.max_age_seconds:.0f}s) -> degraded from {old_rating} to {current_rating}"
                    )

        # ========================================================
        # 5. Telemetry & Deterministic Rating Output
        # ========================================================
        metrics: Dict[str, Any] = {
            "valid_sources_count": valid_count,
            "total_sources_count": total_sources_count,
            "dispersion_pct": round(dispersion, 6),
        }
        if max_age is not None:
            metrics["max_age_seconds"] = round(max_age, 2)

        log_level = "INFO" if current_rating in ("HIGH", "MEDIUM") else "WARNING"
        log_kwargs = {
            "level": log_level,
            "event": "confidence_evaluated",
            "component": "confidence",
            "rating": current_rating,
            "score_reason": score_reason,
            "reason_detail": reason_detail,
            "valid_sources": valid_count,
            "total_sources": total_sources_count,
            "dispersion_pct": round(dispersion, 6),
            "dispersion_threshold_high": cfg.max_dispersion_high,
            "dispersion_threshold_medium": cfg.max_dispersion_medium,
            "mean_price": round(mean_price, 4),
            "min_price": min_price,
            "max_price": max_price,
            "spread": round(max_price - min_price, 4),
        }
        if max_age is not None:
            log_kwargs["max_age_seconds"] = round(max_age, 2)
            log_kwargs["freshness_threshold"] = cfg.max_age_seconds
            log_kwargs["is_stale"] = is_stale
        if curr:
            log_kwargs["currency"] = curr

        logger.log_event(**log_kwargs)

        return {
            "rating": current_rating,
            "score_reason": score_reason,
            "metrics": metrics,
        }

    except Exception as error:
        log_kwargs = {
            "level": "ERROR",
            "event": "confidence_calculation_failed",
            "component": "confidence",
            "rating": "LOW",
            "reason": str(error),
            "reason_detail": f"Confidence evaluation failed due to unexpected error: {str(error)}",
            "valid_sources": len(valid_prices) if isinstance(valid_prices, dict) else 0,
            "total_sources": total_sources if isinstance(total_sources, int) else 0,
        }
        if curr:
            log_kwargs["currency"] = curr
        logger.log_event(**log_kwargs)

        return {
            "rating": "LOW",
            "score_reason": f"calculation_error: {str(error)}",
            "metrics": {
                "valid_sources_count": len(valid_prices) if isinstance(valid_prices, dict) else 0,
                "total_sources_count": total_sources if isinstance(total_sources, int) else 0,
                "dispersion_pct": None,
            },
        }
