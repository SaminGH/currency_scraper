import scraper_manager as scraper_manager
import logs.logger as logger


# ============================================================
# شروع Scraper Output
# ============================================================

logger.log_event(
    level="INFO",
    event="scraper_output_started",
    component="scraper_output"
)


try:

    # ========================================================
    # گرفتن خروجی تمام scraper ها از Scraper Manager
    # ========================================================

    scraper_results = scraper_manager.run_all()


    # ========================================================
    # آماده‌سازی Source ها از خروجی Manager
    # ========================================================

    sources = {}
    source_status = {}

    try:

        for source_name, result in scraper_results.items():

            try:

                # ------------------------------------------------
                # پشتیبانی از ScraperResult
                # ------------------------------------------------

                source_prices = result.get("prices", {})

                # ------------------------------------------------
                # اگر خروجی scraper معتبر نباشد
                # ------------------------------------------------

                if not isinstance(source_prices, dict):

                    logger.log_event(
                        level="WARNING",
                        event="source_data_missing",
                        component="scraper_output",
                        source=source_name,
                        reason="prices_is_not_dict"
                    )
                    source_status[source_name] = {
                        "status": "failed",
                        "currencies_received": 0,
                        "failure_reason": "prices_is_not_dict",
                    }
                    continue

                sources[source_name] = source_prices

                status = result.get("status")
                if status == "complete":
                    db_status = "success"
                elif status in ("partial", "failed"):
                    db_status = status
                else:
                    db_status = "success" if source_prices else "failed"

                errors = result.get("errors", {})
                failure_reason = None
                if db_status in ("partial", "failed"):
                    failure_reason = (
                        f"{len(errors)} currency collection errors"
                        if isinstance(errors, dict) and errors
                        else "source_failed_without_details"
                    )
                source_status[source_name] = {
                    "status": db_status,
                    "currencies_received": len(source_prices),
                    "failure_reason": failure_reason,
                }

            except Exception as error:

                source_status[source_name] = {
                    "status": "failed",
                    "currencies_received": 0,
                    "failure_reason": str(error),
                }
                logger.log_event(
                    level="WARNING",
                    event="source_data_failed",
                    component="scraper_output",
                    source=source_name,
                    reason=str(error)
                )

                continue

    except Exception as error:

        logger.log_event(
            level="WARNING",
            event="source_results_failed",
            component="scraper_output",
            reason=str(error)
        )


    # ========================================================
    # پیدا کردن تمام ارزها
    # ========================================================

    all_currencies = set()

    for source_name, source_prices in sources.items():

        try:

            # اگر خروجی scraper معتبر نباشد
            if not isinstance(source_prices, dict):

                logger.log_event(
                    level="WARNING",
                    event="source_data_missing",
                    component="scraper_output",
                    source=source_name,
                    reason="prices_is_not_dict"
                )

                continue


            all_currencies.update(
                source_prices.keys()
            )

        except Exception as error:

            logger.log_event(
                level="WARNING",
                event="source_data_failed",
                component="scraper_output",
                source=source_name,
                reason=str(error)
            )

            continue


    all_currencies = sorted(all_currencies)


    # ========================================================
    # آماده‌سازی خروجی برای Validator
    # ========================================================

    prices = {}


    for currency in all_currencies:

        try:

            currency_prices = {}


            # ------------------------------------------------
            # گرفتن Price از هر Source
            # ------------------------------------------------

            for source_name, source_prices in sources.items():

                try:

                    # اگر این Source ارز را نداشت
                    if currency not in source_prices:
                        continue


                    data = source_prices[currency]


                    # ----------------------------------------
                    # بررسی معتبر بودن data
                    # ----------------------------------------

                    if not isinstance(data, dict):

                        logger.log_event(
                            level="WARNING",
                            event="currency_data_missing",
                            component="scraper_output",
                            currency=currency,
                            source=source_name,
                            reason="currency_data_is_not_dict"
                        )

                        continue


                    # ----------------------------------------
                    # همه scraper ها باید Price داشته باشند
                    # ----------------------------------------

                    if "price" in data:

                        currency_prices[source_name] = data["price"]

                    else:

                        logger.log_event(
                            level="WARNING",
                            event="currency_data_missing",
                            component="scraper_output",
                            currency=currency,
                            source=source_name,
                            reason="price_missing"
                        )

                except Exception as error:

                    logger.log_event(
                        level="WARNING",
                        event="currency_data_failed",
                        component="scraper_output",
                        currency=currency,
                        source=source_name,
                        reason=str(error)
                    )

                    continue


            # ------------------------------------------------
            # تعداد Source های موجود
            # ------------------------------------------------

            source_count = len(currency_prices)

            total_sources = len(sources)


            # ------------------------------------------------
            # ذخیره اطلاعات ارز
            # ------------------------------------------------

            prices[currency] = {
                "prices": currency_prices,
                "source": f"{source_count}/{total_sources}"
            }


        except Exception as error:

            logger.log_event(
                level="WARNING",
                event="currency_processing_failed",
                component="scraper_output",
                currency=currency,
                reason=str(error)
            )

            continue


    # ========================================================
    # پایان موفق Scraper Output
    # ========================================================

    logger.log_event(
        level="INFO",
        event="scraper_output_completed",
        component="scraper_output",
        currencies=len(prices)
    )


except Exception as error:

    # ========================================================
    # خطای کلی Scraper Output
    # ========================================================

    prices = {}

    logger.log_event(
        level="ERROR",
        event="scraper_output_failed",
        component="scraper_output",
        reason=str(error)
    )
