from datetime import datetime

import validator
import logger

logger.log_event(level="INFO", event="aggregation_started", component="aggregator")
final_prices = {}

try:
    validated_prices = validator.prices
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
            final_prices[currency] = {
                "price": final_price,
                "confidence": data.get("confidence", f"{sources_used}/{sources_total}"),
                "confidence_reason": "validator_output",
                "sources": list(source_prices.keys()),
                "sources_total": sources_total,
                "sources_used": sources_used,
                "status": status,
                "publishable": sources_used >= 2,
                "publishability_reason": "at_least_two_valid_sources" if sources_used >= 2 else "fewer_than_two_valid_sources",
                "timestamp": timestamp,
            }
            logger.log_event(level="INFO", event="price_aggregated", component="aggregator", currency=currency, price=final_price, confidence=final_prices[currency]["confidence"], sources=list(source_prices.keys()), status=status)
        except Exception as error:
            logger.log_event(level="ERROR", event="aggregation_failed", component="aggregator", currency=currency, reason=str(error))
    logger.log_event(level="INFO", event="aggregation_completed", component="aggregator", currencies=len(final_prices))
except Exception as error:
    logger.log_event(level="ERROR", event="aggregation_failed", component="aggregator", reason=str(error))
