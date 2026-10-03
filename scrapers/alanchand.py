import requests
from bs4 import BeautifulSoup

import logger


# ============================================================
# Source Configuration
# ============================================================

SOURCE_NAME = "alanchand"

URL = "https://alanchand.com/currencies-price"

REQUEST_TIMEOUT = 10


# ============================================================
# ارزهایی که می‌خواهیم دریافت کنیم
# ============================================================

currencies = {
    "دلار آمریکا",
    "یورو",
    "درهم",
    "لیر ترکیه",
    "پوند انگلیس",
    "یوان چین",
    "دلار کانادا",
    "دلار استرالیا",
    "روبل روسیه",
    "صد دینار عراق",
    "رینگیت مالزی",
    "لاری گرجستان",
    "منات آذربایجان",
    "صد درام ارمنستان",
    "بات تایلند",
    "ریال عمان",
    "روپیه هند",
    "روپیه پاکستان",
    "صد ین ژاپن",
    "ریال عربستان",
    "افغانی",
    "کرون سوئد",
    "فرانک سوئیس",
    "ریال قطر",
    "صد وون کره جنوبی",
    "کرون نروژ",
    "دلار نیوزلند",
    "دلار سنگاپور",
    "دلار هنگ کنگ",
    "دینار کویت",
    "کرون دانمارک",
    "دینار بحرین",
    "سامانی تاجیکستان",
    "منات ترکمنستان",
    "سوم قرقیزستان",
    "صد پوند سوریه",
    "رئال برزیل",
    "پزو آرژانتین",
}


# ============================================================
# نام فارسی ارز → Symbol
# ============================================================

currency_symbols = {
    "دلار آمریکا": "USD",
    "یورو": "EUR",
    "درهم": "AED",
    "لیر ترکیه": "TRY",
    "پوند انگلیس": "GBP",
    "یوان چین": "CNY",
    "دلار کانادا": "CAD",
    "دلار استرالیا": "AUD",
    "روبل روسیه": "RUB",
    "صد دینار عراق": "IQD",
    "رینگیت مالزی": "MYR",
    "لاری گرجستان": "GEL",
    "منات آذربایجان": "AZN",
    "صد درام ارمنستان": "AMD",
    "بات تایلند": "THB",
    "ریال عمان": "OMR",
    "روپیه هند": "INR",
    "روپیه پاکستان": "PKR",
    "صد ین ژاپن": "JPY",
    "ریال عربستان": "SAR",
    "افغانی": "AFN",
    "کرون سوئد": "SEK",
    "فرانک سوئیس": "CHF",
    "ریال قطر": "QAR",
    "صد وون کره جنوبی": "KRW",
    "کرون نروژ": "NOK",
    "دلار نیوزلند": "NZD",
    "دلار سنگاپور": "SGD",
    "دلار هنگ کنگ": "HKD",
    "دینار کویت": "KWD",
    "کرون دانمارک": "DKK",
    "دینار بحرین": "BHD",
    "سامانی تاجیکستان": "TJS",
    "منات ترکمنستان": "TMT",
    "سوم قرقیزستان": "KGS",
    "صد پوند سوریه": "SYP",
    "رئال برزیل": "BRL",
    "پزو آرژانتین": "ARS",
}


# ============================================================
# ارزهایی که سایت قیمت آن‌ها را به صورت 100 واحدی نمایش می‌دهد
# ============================================================

currency_units = {
    "IQD": 100,
    "AMD": 100,
    "JPY": 100,
    "KRW": 100,
    "SYP": 100,
}


# ============================================================
# تبدیل اعداد فارسی و عربی به انگلیسی
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

    text = text.replace(",", "")

    return text


# ============================================================
# Internal scraper exceptions
# ============================================================

class SelectorError(Exception):
    pass


# ============================================================
# Scraper
# ============================================================

def scrape():

    """
    Scrape currency prices from Alanchand.

    Returns:

        {
            "source": "alanchand",
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
        # دریافت صفحه
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

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        # ====================================================
        # پیدا کردن تمام ردیف‌های جدول
        # ====================================================

        rows = soup.select(
            "table tbody tr"
        )

        # اگر selector هیچ نتیجه‌ای نداد،
        # احتمال تغییر ساختار سایت وجود دارد.
        if not rows:

            raise SelectorError(
                "currency_table_rows_not_found"
            )

        # ====================================================
        # پردازش Currency ها
        # ====================================================

        for row in rows:

            try:

                cells = row.find_all("td")

                # --------------------------------------------
                # اگر اطلاعات کافی نبود
                # --------------------------------------------

                if len(cells) < 3:
                    continue

                # --------------------------------------------
                # نام ارز
                # --------------------------------------------

                name = cells[0].get_text(
                    strip=True
                )

                # --------------------------------------------
                # اگر ارز موردنظر ما نیست
                # --------------------------------------------

                if name not in currencies:
                    continue

                # --------------------------------------------
                # پیدا کردن Symbol
                # --------------------------------------------

                symbol = currency_symbols.get(
                    name
                )

                if symbol is None:

                    raise SelectorError(
                        "currency_symbol_not_found"
                    )

                # --------------------------------------------
                # قیمت Buy / Sell
                # --------------------------------------------

                buy = cells[1].get_text(
                    strip=True
                )

                sell = cells[2].get_text(
                    strip=True
                )

                # --------------------------------------------
                # تبدیل اعداد فارسی/عربی
                # --------------------------------------------

                buy = convert_to_english_number(
                    buy
                )

                sell = convert_to_english_number(
                    sell
                )

                # --------------------------------------------
                # بررسی خالی نبودن قیمت
                # --------------------------------------------

                if not buy or not sell:

                    raise ValueError(
                        "buy_or_sell_price_empty"
                    )

                # --------------------------------------------
                # تبدیل string → number
                # --------------------------------------------

                buy = int(buy)
                sell = int(sell)

                # --------------------------------------------
                # بررسی واحد قیمت
                # --------------------------------------------

                unit = currency_units.get(
                    symbol,
                    1
                )

                # --------------------------------------------
                # تبدیل قیمت از 100 واحد → 1 واحد
                # --------------------------------------------

                buy = buy / unit
                sell = sell / unit

                # --------------------------------------------
                # محاسبه Price
                # --------------------------------------------

                price = (
                    buy + sell
                ) / 2

                # --------------------------------------------
                # ذخیره اطلاعات
                # --------------------------------------------

                prices[symbol] = {
                    "price": price
                }

            except SelectorError as error:

                # ------------------------------------------
                # خطای ساختاری فقط همین Currency
                # ------------------------------------------

                currency_name = "unknown"

                try:
                    currency_name = name
                except NameError:
                    pass

                errors[currency_name] = {
                    "type": "selector_error",
                    "message": str(error)
                }

                logger.log_event(
                    level="WARNING",
                    event="currency_failed",
                    component=SOURCE_NAME,
                    source=SOURCE_NAME,
                    currency=currency_name,
                    error_type="selector_error",
                    reason=str(error)
                )

                continue

            except (ValueError, TypeError) as error:

                # ------------------------------------------
                # خطای Parsing / Conversion
                # ------------------------------------------

                currency_name = "unknown"

                try:
                    currency_name = name
                except NameError:
                    pass

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
                    error_type="parser_error",
                    reason=str(error)
                )

                continue

            except Exception as error:

                # ------------------------------------------
                # خطای غیرمنتظره Currency
                # ------------------------------------------

                currency_name = "unknown"

                try:
                    currency_name = name
                except NameError:
                    pass

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
                    error_type="currency_error",
                    reason=str(error)
                )

                continue

        # ====================================================
        # تعیین وضعیت Scraper
        # ====================================================

        success_count = len(prices)
        error_count = len(errors)

        if success_count == len(currencies):

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

    # ========================================================
    # Timeout
    # ========================================================

    except requests.exceptions.Timeout as error:

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
            error_type="timeout",
            reason=str(error)
        )

    # ========================================================
    # Connection Error
    # ========================================================

    except requests.exceptions.ConnectionError as error:

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
            error_type="connection_error",
            reason=str(error)
        )

    # ========================================================
    # HTTP Error
    # ========================================================

    except requests.exceptions.HTTPError as error:

        status = "failed"

        status_code = None

        if error.response is not None:
            status_code = error.response.status_code

        if status_code is not None and 500 <= status_code <= 599:

            error_type = "http_5xx"

        elif status_code is not None and 400 <= status_code <= 499:

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
            error_type=error_type,
            status_code=status_code,
            reason=str(error)
        )

    # ========================================================
    # سایر Request Error ها
    # ========================================================

    except requests.exceptions.RequestException as error:

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
            error_type="network_error",
            reason=str(error)
        )

    # ========================================================
    # Selector / Structure Error
    # ========================================================

    except SelectorError as error:

        status = "failed"

        errors["_scraper"] = {
            "type": "selector_error",
            "message": str(error)
        }

        logger.log_event(
            level="ERROR",
            event="source_failed",
            component=SOURCE_NAME,
            source=SOURCE_NAME,
            error_type="selector_error",
            reason=str(error)
        )

    # ========================================================
    # خطای کلی غیرمنتظره
    # ========================================================

    except Exception as error:

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
            error_type="scraper_error",
            reason=str(error)
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