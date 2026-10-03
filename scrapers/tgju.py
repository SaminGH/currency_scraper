import requests
from bs4 import BeautifulSoup

import logger


# ============================================================
# Source Configuration
# ============================================================

SOURCE_NAME = "tgju"

URL = "https://www.tgju.org/currency"

REQUEST_TIMEOUT = 10


# ============================================================
# Persian / Arabic numbers
# ============================================================

def convert_to_english_number(text):

    persian_numbers = "۰۱۲۳۴۵۶۷۸۹"
    arabic_numbers = "٠١٢٣٤٥٦٧٨٩"
    english_numbers = "0123456789"

    for i in range(10):

        text = text.replace(
            persian_numbers[i],
            english_numbers[i]
        )

        text = text.replace(
            arabic_numbers[i],
            english_numbers[i]
        )

    return text


# ============================================================
# Convert price to integer
# ============================================================

def clean_number(text):

    text = convert_to_english_number(text)

    text = text.replace(",", "")

    text = text.strip()

    return int(text)


# ============================================================
# Convert Rial to Toman
# ============================================================

def rial_to_toman(value):

    return value // 10


# ============================================================
# Special symbol names
# ============================================================

symbol_map = {
    "DOLLAR_RL": "USD"
}


# ============================================================
# Special currency units
# ============================================================

currency_units = {
    "JPY": 100
}


# ============================================================
# Scraper
# ============================================================

def scrape():
    """
    Scrape currency prices from TGJU.

    Returns:
        dict:
        {
            "source": "tgju",
            "status": "complete" | "partial" | "failed",
            "prices": {...},
            "errors": {...}
        }
    """

    prices = {}

    errors = {}

    status = "failed"

    # ========================================================
    # شروع Scraper
    # ========================================================

    logger.log_event(
        level="INFO",
        event="source_started",
        component=SOURCE_NAME,
        source=SOURCE_NAME
    )

    try:

        # ====================================================
        # دریافت صفحه TGJU
        # ====================================================

        response = requests.get(
            URL,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        # ====================================================
        # بررسی HTTP Error
        # ====================================================

        response.raise_for_status()

        # ====================================================
        # تبدیل HTML به BeautifulSoup
        # ====================================================

        try:

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

        except Exception as error:

            raise RuntimeError(
                f"parser_error: {error}"
            )

        # ====================================================
        # پیدا کردن تمام Currency Row ها
        # ====================================================

        rows = soup.select(
            "tr[data-market-row]"
        )

        # ====================================================
        # اگر هیچ Row پیدا نشد
        # ====================================================

        if not rows:

            errors["_scraper"] = {
                "type": "selector_error",
                "message": "no_currency_rows_found"
            }

            logger.log_event(
                level="ERROR",
                event="source_failed",
                component=SOURCE_NAME,
                source=SOURCE_NAME,
                reason="no_currency_rows_found",
                error_type="selector_error"
            )

            status = "failed"

            return {
                "source": SOURCE_NAME,
                "status": status,
                "prices": prices,
                "errors": errors
            }

        # ====================================================
        # پردازش تمام Currency ها
        # ====================================================

        for row in rows:

            nameslug = None

            try:

                # ------------------------------------------------
                # Market identifier
                # ------------------------------------------------

                nameslug = row.get(
                    "data-market-nameslug"
                )

                if not nameslug:

                    continue

                # ------------------------------------------------
                # پیدا کردن TD ها
                # ------------------------------------------------

                cells = row.find_all("td")

                if len(cells) < 1:

                    errors[
                        nameslug
                    ] = {
                        "type": "selector_error",
                        "message": "currency_cells_not_found"
                    }

                    logger.log_event(
                        level="WARNING",
                        event="currency_failed",
                        component=SOURCE_NAME,
                        source=SOURCE_NAME,
                        currency=nameslug,
                        reason="currency_cells_not_found",
                        error_type="selector_error"
                    )

                    continue

                # ------------------------------------------------
                # Live price = first TD
                # ------------------------------------------------

                live = cells[0].get_text(
                    " ",
                    strip=True
                )

                # ------------------------------------------------
                # بررسی خالی نبودن قیمت
                # ------------------------------------------------

                if not live:

                    raise ValueError(
                        "price_empty"
                    )

                # ------------------------------------------------
                # تبدیل قیمت به عدد
                # ------------------------------------------------

                try:

                    live = clean_number(
                        live
                    )

                except (ValueError, TypeError) as error:

                    errors[
                        nameslug
                    ] = {
                        "type": "parser_error",
                        "message": str(error)
                    }

                    logger.log_event(
                        level="WARNING",
                        event="currency_failed",
                        component=SOURCE_NAME,
                        source=SOURCE_NAME,
                        currency=nameslug,
                        reason=str(error),
                        error_type="parser_error"
                    )

                    continue

                # ------------------------------------------------
                # Rial → Toman
                # ------------------------------------------------

                live = rial_to_toman(
                    live
                )

                # ------------------------------------------------
                # تبدیل Market Name → Symbol
                # ------------------------------------------------

                symbol = nameslug.replace(
                    "price_",
                    ""
                ).upper()

                # ------------------------------------------------
                # Special symbol
                # ------------------------------------------------

                if symbol in symbol_map:

                    symbol = symbol_map[symbol]

                # ------------------------------------------------
                # Special currency unit
                # ------------------------------------------------

                if symbol in currency_units:

                    live = (
                        live /
                        currency_units[symbol]
                    )

                # ------------------------------------------------
                # بررسی نهایی Symbol
                # ------------------------------------------------

                if not symbol:

                    raise ValueError(
                        "currency_symbol_empty"
                    )

                # ------------------------------------------------
                # ذخیره اطلاعات
                # ------------------------------------------------

                prices[symbol] = {
                    "price": live
                }

            except ValueError as error:

                # ----------------------------------------------
                # خطای داده همین Currency
                # ----------------------------------------------

                currency_name = (
                    nameslug
                    if nameslug
                    else "unknown"
                )

                errors[currency_name] = {
                    "type": "parser_error",
                    "message": str(error)
                }

                logger.log_event(
                    level="WARNING",
                    event="currency_failed",
                    component=SOURCE_NAME,
                    source=SOURCE_NAME,
                    currency=currency_name,
                    reason=str(error),
                    error_type="parser_error"
                )

                continue

            except Exception as error:

                # ----------------------------------------------
                # خطای غیرمنتظره همین Currency
                # ----------------------------------------------

                currency_name = (
                    nameslug
                    if nameslug
                    else "unknown"
                )

                errors[currency_name] = {
                    "type": "currency_error",
                    "message": str(error)
                }

                logger.log_event(
                    level="WARNING",
                    event="currency_failed",
                    component=SOURCE_NAME,
                    source=SOURCE_NAME,
                    currency=currency_name,
                    reason=str(error),
                    error_type="currency_error"
                )

                continue

        # ====================================================
        # تعیین وضعیت نهایی Scraper
        # ====================================================

        success_count = len(prices)

        error_count = len(errors)

        if success_count > 0 and error_count == 0:

            status = "complete"

            logger.log_event(
                level="INFO",
                event="source_success",
                component=SOURCE_NAME,
                source=SOURCE_NAME,
                currencies=success_count
            )

        elif success_count > 0:

            status = "partial"

            logger.log_event(
                level="WARNING",
                event="source_partial",
                component=SOURCE_NAME,
                source=SOURCE_NAME,
                currencies=success_count,
                failed=error_count
            )

        else:

            status = "failed"

            logger.log_event(
                level="ERROR",
                event="source_failed",
                component=SOURCE_NAME,
                source=SOURCE_NAME,
                reason="no_currencies_scraped"
            )

    except requests.exceptions.Timeout as error:

        # ====================================================
        # Timeout کل Source
        # ====================================================

        status = "failed"

        errors["_scraper"] = {
            "type": "timeout",
            "message": str(error)
        }

        logger.log_event(
            level="ERROR",
            event="source_timeout",
            component=SOURCE_NAME,
            source=SOURCE_NAME,
            reason=str(error),
            error_type="timeout"
        )

    except requests.exceptions.ConnectionError as error:

        # ====================================================
        # Connection Error
        # ====================================================

        status = "failed"

        errors["_scraper"] = {
            "type": "connection_error",
            "message": str(error)
        }

        logger.log_event(
            level="ERROR",
            event="source_failed",
            component=SOURCE_NAME,
            source=SOURCE_NAME,
            reason=str(error),
            error_type="connection_error"
        )

    except requests.exceptions.HTTPError as error:

        # ====================================================
        # HTTP Error
        # ====================================================

        status = "failed"

        response = getattr(
            error,
            "response",
            None
        )

        status_code = (
            response.status_code
            if response is not None
            else None
        )

        if (
            status_code is not None
            and 500 <= status_code < 600
        ):

            error_type = "http_5xx"

        elif (
            status_code is not None
            and 400 <= status_code < 500
        ):

            error_type = "http_4xx"

        else:

            error_type = "network_error"

        errors["_scraper"] = {
            "type": error_type,
            "message": str(error)
        }

        logger.log_event(
            level="ERROR",
            event="source_failed",
            component=SOURCE_NAME,
            source=SOURCE_NAME,
            reason=str(error),
            error_type=error_type
        )

    except requests.exceptions.RequestException as error:

        # ====================================================
        # سایر Network / Request Errors
        # ====================================================

        status = "failed"

        errors["_scraper"] = {
            "type": "network_error",
            "message": str(error)
        }

        logger.log_event(
            level="ERROR",
            event="source_failed",
            component=SOURCE_NAME,
            source=SOURCE_NAME,
            reason=str(error),
            error_type="network_error"
        )

    except RuntimeError as error:

        # ====================================================
        # Parser / Structural Error
        # ====================================================

        status = "failed"

        message = str(error)

        if message.startswith("parser_error:"):

            error_type = "parser_error"

        else:

            error_type = "scraper_error"

        errors["_scraper"] = {
            "type": error_type,
            "message": message
        }

        logger.log_event(
            level="ERROR",
            event="source_failed",
            component=SOURCE_NAME,
            source=SOURCE_NAME,
            reason=message,
            error_type=error_type
        )

    except Exception as error:

        # ====================================================
        # خطای کلی Scraper
        # ====================================================

        status = "failed"

        errors["_scraper"] = {
            "type": "scraper_error",
            "message": str(error)
        }

        logger.log_event(
            level="ERROR",
            event="source_failed",
            component=SOURCE_NAME,
            source=SOURCE_NAME,
            reason=str(error),
            error_type="scraper_error"
        )

    # ========================================================
    # خروجی استاندارد Scraper
    # ========================================================

    return {
        "source": SOURCE_NAME,
        "status": status,
        "prices": prices,
        "errors": errors
    }