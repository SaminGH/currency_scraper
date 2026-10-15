from datetime import datetime
from typing import Any, Dict

import confidence
import logs.logger as logger


def aggregate_prices(validated_prices: Dict[str, Any]) -> Dict[str, Any]:
    """
    Aggregate validated prices across sources and compute statistics and publishability.

    Parameters:
        validated_prices: Dictionary of validated currency data from validator.

    Returns:
        Dictionary of aggregated rates by currency.
    """
    logger.log_event(level="INFO", event="aggregation_started", component="aggregator")
    final_prices: Dict[str, Any] = {}

    try:
        if not isinstance(validated_prices, dict):
            raise ValueError("validator_prices_is_not_dict")

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for currency, data in validated_prices.items():
            try:
                if not isinstance(data, dict):
                    continue

                source_prices = data.get("prices", {})
                if not isinstance(source_prices, dict) or not source_prices:
                    continue

                status = data.get("status", "valid")
                source_info = data.get("source", "0/0")

                try:
                    sources_total = int(str(source_info).split("/", 1)[1])
                except (ValueError, IndexError):
                    sources_total = len(source_prices)

                sources_used = len(source_prices)
                final_price = sum(source_prices.values()) / sources_used

                conf_result = confidence.calculate_confidence(
                    valid_prices=source_prices,
                    total_sources=sources_total,
                    snapshot_time=timestamp,
                    currency=currency,
                )

                final_prices[currency] = {
                    "price": final_price,
                    "confidence": conf_result["rating"],
                    "confidence_reason": conf_result["score_reason"],
                    "confidence_metrics": conf_result.get("metrics"),
                    "sources": list(source_prices.keys()),
                    "sources_total": sources_total,
                    "sources_used": sources_used,
                    "status": status,
                    "publishable": sources_used >= 2,
                    "publishability_reason": "at_least_two_valid_sources" if sources_used >= 2 else "fewer_than_two_valid_sources",
                    "timestamp": timestamp,
                }

                logger.log_event(
                    level="INFO",
                    event="price_aggregated",
                    component="aggregator",
                    currency=currency,
                    price=final_price,
                    confidence=final_prices[currency]["confidence"],
                    sources=list(source_prices.keys()),
                    status=status
                )
            except Exception as error:
                logger.log_event(
                    level="ERROR",
                    event="aggregation_failed",
                    component="aggregator",
                    currency=currency,
                    reason=str(error)
                )

        logger.log_event(
            level="INFO",
            event="aggregation_completed",
            component="aggregator",
            currencies=len(final_prices)
        )

    except Exception as error:
        logger.log_event(
            level="ERROR",
            event="aggregation_failed",
            component="aggregator",
            reason=str(error)
        )

    return final_prices


if __name__ == "__main__":
    from scraper_output import get_scraper_output
    from validator import validate_prices

    raw_prices, _ = get_scraper_output()
    validated = validate_prices(raw_prices)
    final = aggregate_prices(validated)
    print(f"Aggregation Completed: {len(final)} currencies aggregated.")
    for curr, data in final.items():
        print(f"  {curr}: price={data.get('price')} publishable={data.get('publishable')} confidence={data.get('confidence')}")
