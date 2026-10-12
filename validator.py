import statistics
from dataclasses import dataclass
from typing import Any, Dict

import logs.logger as logger


# ============================================================
# Contract های Validator
# ============================================================

@dataclass
class ValidationInput:
    currency: str
    prices: dict
    source: str


@dataclass
class ValidationResult:
    prices: dict
    source: str
    status: str
    removed_sources: dict


# ============================================================
# تنظیمات Validator
# ============================================================

OUTLIER_THRESHOLD = 0.01


def validate_prices(source_prices: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate currency prices across market sources and remove outliers.

    Parameters:
        source_prices: Dictionary of currency data from scraper_output.

    Returns:
        Dictionary of validated prices by currency.
    """
    # ============================================================
    # شروع Validator
    # ============================================================
    logger.log_event(
        level="INFO",
        event="validation_started",
        component="validator"
    )

    validated_prices: Dict[str, Any] = {}

    try:
        # ========================================================
        # بررسی معتبر بودن خروجی scraper_output
        # ========================================================
        if not isinstance(source_prices, dict):
            raise ValueError(
                "scraper_output_prices_is_not_dict"
            )

        # ========================================================
        # بررسی تمام ارزها
        # ========================================================
        for currency, data in source_prices.items():
            try:
                # ------------------------------------------------
                # بررسی ساختار Data
                # ------------------------------------------------
                if not isinstance(data, dict):
                    logger.log_event(
                        level="WARNING",
                        event="validation_failed",
                        component="validator",
                        currency=currency,
                        reason="currency_data_is_not_dict"
                    )
                    continue

                if "prices" not in data:
                    logger.log_event(
                        level="WARNING",
                        event="validation_failed",
                        component="validator",
                        currency=currency,
                        reason="prices_missing"
                    )
                    continue

                prices = data["prices"]

                if not isinstance(prices, dict):
                    logger.log_event(
                        level="WARNING",
                        event="validation_failed",
                        component="validator",
                        currency=currency,
                        reason="prices_is_not_dict"
                    )
                    continue

                # ------------------------------------------------
                # گرفتن Source Count از scraper_output
                # ------------------------------------------------
                source_info = data.get("source")

                if not isinstance(source_info, str):
                    logger.log_event(
                        level="WARNING",
                        event="validation_failed",
                        component="validator",
                        currency=currency,
                        reason="source_info_is_not_string"
                    )
                    continue

                try:
                    source_count_str, total_sources_str = (
                        source_info.split("/", 1)
                    )
                    source_count = int(source_count_str)
                    total_sources = int(total_sources_str)
                except (ValueError, AttributeError):
                    logger.log_event(
                        level="WARNING",
                        event="validation_failed",
                        component="validator",
                        currency=currency,
                        reason="invalid_source_info"
                    )
                    continue

                # ------------------------------------------------
                # Safety Check
                # ------------------------------------------------
                if source_count < 0:
                    source_count = 0

                if total_sources < 0:
                    total_sources = 0

                if source_count > total_sources:
                    source_count = len(prices)

                # برای جلوگیری از inconsistency
                # بین source string و prices واقعی
                source_count = len(prices)

                # =================================================
                # 0/N
                # =================================================
                if source_count == 0:
                    validated_prices[currency] = {
                        "prices": {},
                        "source": f"0/{total_sources}",
                        "status": "not_publishable",
                        "removed_sources": {}
                    }

                    logger.log_event(
                        level="WARNING",
                        event="validation_rejected",
                        component="validator",
                        currency=currency,
                        source=f"0/{total_sources}",
                        reason="no_valid_sources"
                    )
                    continue

                # =================================================
                # 1/N
                # =================================================
                if source_count == 1:
                    validated_prices[currency] = {
                        "prices": prices,
                        "source": f"1/{total_sources}",
                        "status": "not_publishable",
                        "removed_sources": {}
                    }

                    logger.log_event(
                        level="WARNING",
                        event="validation_rejected",
                        component="validator",
                        currency=currency,
                        source=f"1/{total_sources}",
                        reason="only_one_source"
                    )
                    continue

                # =================================================
                # 2/N
                # بدون Outlier Removal
                # =================================================
                if source_count == 2:
                    validated_prices[currency] = {
                        "prices": prices,
                        "source": f"2/{total_sources}",
                        "status": "valid",
                        "removed_sources": {}
                    }

                    logger.log_event(
                        level="INFO",
                        event="validation_success",
                        component="validator",
                        currency=currency,
                        source=f"2/{total_sources}",
                        status="valid"
                    )
                    continue

                # =================================================
                # 3/N یا بیشتر
                # شروع Outlier Removal
                # =================================================
                original_prices = prices.copy()

                # -------------------------------------------------
                # بررسی اینکه قیمت‌ها برای Median عددی باشند
                # -------------------------------------------------
                if not all(
                    isinstance(price, (int, float))
                    for price in original_prices.values()
                ):
                    logger.log_event(
                        level="WARNING",
                        event="validation_failed",
                        component="validator",
                        currency=currency,
                        reason="non_numeric_price"
                    )
                    continue

                # -------------------------------------------------
                # محاسبه Median
                # -------------------------------------------------
                median_price = statistics.median(
                    original_prices.values()
                )

                # جلوگیری از Division By Zero
                if median_price == 0:
                    logger.log_event(
                        level="WARNING",
                        event="validation_failed",
                        component="validator",
                        currency=currency,
                        reason="median_price_is_zero"
                    )
                    continue

                # -------------------------------------------------
                # پیدا کردن Price های معتبر و Outlier ها
                # -------------------------------------------------
                valid_prices = {}
                removed_sources = {}

                for source_name, price in original_prices.items():
                    try:
                        # -----------------------------------------
                        # درصد اختلاف با Median
                        # -----------------------------------------
                        difference = abs(
                            price - median_price
                        ) / median_price

                        # -----------------------------------------
                        # اگر اختلاف بیشتر از Threshold باشد
                        # -----------------------------------------
                        if difference > OUTLIER_THRESHOLD:
                            removed_sources[source_name] = {
                                "price": price,
                                "difference": difference
                            }

                            logger.log_event(
                                level="WARNING",
                                event="outlier_removed",
                                component="validator",
                                currency=currency,
                                source=source_name,
                                price=price,
                                median=median_price,
                                difference=difference,
                                threshold=OUTLIER_THRESHOLD
                            )
                        else:
                            valid_prices[source_name] = price

                    except Exception as error:
                        logger.log_event(
                            level="WARNING",
                            event="validation_failed",
                            component="validator",
                            currency=currency,
                            source=source_name,
                            reason=str(error)
                        )
                        continue

                # =================================================
                # تعیین Status
                # =================================================
                if removed_sources:
                    status = "outlier_removed"
                else:
                    status = "valid"

                # =================================================
                # ذخیره نتیجه
                # =================================================
                validated_prices[currency] = {
                    "prices": valid_prices,
                    "source": f"{source_count}/{total_sources}",
                    "status": status,
                    "removed_sources": removed_sources
                }

                # =================================================
                # Log نتیجه Validation
                # =================================================
                if remaining_count == 0:
                    logger.log_event(
                        level="ERROR",
                        event="validation_rejected",
                        component="validator",
                        currency=currency,
                        source=f"{source_count}/{total_sources}",
                        status=status,
                        reason="all_sources_removed"
                    )
                elif remaining_count == 1:
                    logger.log_event(
                        level="WARNING",
                        event="validation_rejected",
                        component="validator",
                        currency=currency,
                        source=f"{source_count}/{total_sources}",
                        status=status,
                        reason="only_one_source_remaining"
                    )
                else:
                    logger.log_event(
                        level="INFO",
                        event="validation_success",
                        component="validator",
                        currency=currency,
                        source=f"{source_count}/{total_sources}",
                        status=status
                    )

            except Exception as error:
                # ------------------------------------------------
                # خطای یک Currency نباید کل Validator را متوقف کند
                # ------------------------------------------------
                logger.log_event(
                    level="ERROR",
                    event="validation_failed",
                    component="validator",
                    currency=currency,
                    reason=str(error)
                )
                continue

        # ========================================================
        # پایان موفق Validator
        # ========================================================
        logger.log_event(
            level="INFO",
            event="validation_completed",
            component="validator",
            currencies=len(validated_prices)
        )

        return validated_prices

    except Exception as error:
        # ========================================================
        # خطای کلی Validator
        # ========================================================
        logger.log_event(
            level="ERROR",
            event="validation_failed",
            component="validator",
            reason=str(error)
        )
        return validated_prices


if __name__ == "__main__":
    from scraper_output import get_scraper_output
    raw_prices, _ = get_scraper_output()
    results = validate_prices(raw_prices)
    print(f"Validation Completed: {len(results)} currencies processed.")
    for curr, data in results.items():
        print(f"  {curr}: status={data.get('status')} valid_sources={list(data.get('prices', {}).keys())} removed={list(data.get('removed_sources', {}).keys())}")