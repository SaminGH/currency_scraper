from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
import logs.logger as logger
from pathlib import Path


# ============================================================
# Source Configuration
# ============================================================

SOURCE_NAME = "bonbast"

URL = "https://bonbast.com"

REQUEST_TIMEOUT = 10

BASE_DIR = Path(__file__).resolve().parent.parent
SERVICE_FILE = BASE_DIR / "environment" / "chromedriver-win64" /"chromedriver.exe"

service = Service(executable_path=str(SERVICE_FILE))


# ============================================================
# ارزهایی که می‌خواهیم دریافت کنیم
# ============================================================

currencies = [
    "usd",
    "eur",
    "gbp",
    "chf",
    "cad",
    "aud",
    "sek",
    "nok",
    "rub",
    "thb",
    "sgd",
    "hkd",
    "azn",
    "amd",
    "dkk",
    "aed",
    "jpy",
    "try",
    "cny",
    "sar",
    "inr",
    "myr",
    "afn",
    "kwd",
    "iqd",
    "bhd",
    "omr",
    "qar"
]


# ============================================================
# واحد قیمت ارزهایی که Bonbast به صورت چندتایی نمایش می‌دهد
# ============================================================

currency_units = {
    "amd": 10,
    "jpy": 10,
    "iqd": 100
}


# ============================================================
# Scraper
# ============================================================

def scrape():

    """
    Scrape currency prices from Bonbast.

    Returns:
        dict:
        {
            "source": "bonbast",
            "status": "complete" | "partial" | "failed",
            "prices": {...},
            "errors": {...}
        }
    """

    prices = {}

    errors = {}

    status = "failed"

    driver = None

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
        # ساخت Driver
        # ====================================================

        driver = webdriver.Chrome(
            service=service
        )

        driver.get(URL)

        wait = WebDriverWait(
            driver,
            REQUEST_TIMEOUT
        )

        # ====================================================
        # صبر برای Load شدن کلی سایت
        # ====================================================

        wait.until(
            lambda d: d.find_element(
                By.ID,
                "usd1"
            ).text.strip() != ""
        )

        # ====================================================
        # گرفتن قیمت تمام ارزها
        # ====================================================

        for currency in currencies:

            sell_id = currency + "1"

            buy_id = currency + "2"

            try:

                # ------------------------------------------------
                # صبر می‌کنیم Buy و Sell این ارز Load شوند
                # ------------------------------------------------

                wait.until(
                    lambda d: (
                        d.find_element(
                            By.ID,
                            sell_id
                        ).text.strip() != ""

                        and

                        d.find_element(
                            By.ID,
                            buy_id
                        ).text.strip() != ""
                    )
                )

                # ------------------------------------------------
                # دریافت Buy
                # ------------------------------------------------

                buy = driver.find_element(
                    By.ID,
                    buy_id
                ).text.strip()

                # ------------------------------------------------
                # دریافت Sell
                # ------------------------------------------------

                sell = driver.find_element(
                    By.ID,
                    sell_id
                ).text.strip()

                # ------------------------------------------------
                # بررسی خالی نبودن قیمت
                # ------------------------------------------------

                if not buy or not sell:

                    raise ValueError(
                        "buy_or_sell_price_empty"
                    )

                # ------------------------------------------------
                # تبدیل قیمت‌ها به عدد
                # ------------------------------------------------

                try:

                    buy = int(
                        buy.replace(",", "")
                    )

                    sell = int(
                        sell.replace(",", "")
                    )

                except (ValueError, TypeError) as error:

                    errors[currency.upper()] = {
                        "type": "parser_error",
                        "message": str(error)
                    }

                    logger.log_event(
                        level="WARNING",
                        event="currency_failed",
                        component=SOURCE_NAME,
                        source=SOURCE_NAME,
                        currency=currency.upper(),
                        reason="parser_error",
                        error_type="parser_error"
                    )

                    continue

                # ------------------------------------------------
                # واحد قیمت این ارز
                # ------------------------------------------------

                unit = currency_units.get(
                    currency,
                    1
                )

                # ------------------------------------------------
                # تبدیل قیمت از چند واحد به 1 واحد
                # ------------------------------------------------

                buy = buy / unit

                sell = sell / unit

                # ------------------------------------------------
                # محاسبه Price
                # ------------------------------------------------

                price = (
                    buy + sell
                ) / 2

                # ------------------------------------------------
                # ذخیره اطلاعات
                # ------------------------------------------------

                prices[currency.upper()] = {
                    "price": price
                }

            except TimeoutException as error:

                # ----------------------------------------------
                # Timeout فقط برای همین Currency
                # ----------------------------------------------

                errors[currency.upper()] = {
                    "type": "currency_timeout",
                    "message": str(error)
                }

                logger.log_event(
                    level="WARNING",
                    event="currency_failed",
                    component=SOURCE_NAME,
                    source=SOURCE_NAME,
                    currency=currency.upper(),
                    reason="timeout",
                    error_type="currency_timeout"
                )

                continue

            except Exception as error:

                # ----------------------------------------------
                # خطای فقط همین Currency
                # ----------------------------------------------

                errors[currency.upper()] = {
                    "type": "currency_error",
                    "message": str(error)
                }

                logger.log_event(
                    level="WARNING",
                    event="currency_failed",
                    component=SOURCE_NAME,
                    source=SOURCE_NAME,
                    currency=currency.upper(),
                    reason=str(error),
                    error_type="currency_error"
                )

                continue

        # ====================================================
        # تعیین وضعیت نهایی Scraper
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

    except TimeoutException as error:

        # ====================================================
        # Timeout کل Scraper
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

    finally:

        # ====================================================
        # بستن Browser در هر شرایطی
        # ====================================================

        if driver is not None:

            driver.quit()

    # ========================================================
    # خروجی استاندارد Scraper
    # ========================================================

    return {
        "source": SOURCE_NAME,
        "status": status,
        "prices": prices,
        "errors": errors
    }