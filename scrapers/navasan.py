from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from pathlib import Path

import logs.logger as logger


# ============================================================
# تنظیمات
# ============================================================

SOURCE_NAME = "navasan"

BASE_DIR = Path(__file__).resolve().parent.parent
SERVICE_FILE = BASE_DIR / "environment" / "chromedriver-win64" / "chromedriver.exe"

service = Service(executable_path=str(SERVICE_FILE))

URL = "https://www.navasan.net/"


# ============================================================
# ارزهایی که می‌خواهیم دریافت کنیم
# ============================================================

currencies = [
    "usd",
    "eur",
    "gbp",
    "cad",
    "aud",
    "aed",
    "jpy",
    "try",
    "nzd",
    "sgd",
    "chf",
    "pkr",
    "azn",
    "nok",
    "sek",
    "dkk",
    "kwd",
    "omr",
    "rub",
    "brl",
    "thb",
    "afn",
    "inr",
    "cny",
    "myr",
    "gel"
]


def scrape():

    # ========================================================
    # خروجی‌ها
    # ========================================================

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
            10
        )

        # ====================================================
        # صبر برای Load شدن USD
        # ====================================================

        wait.until(
            lambda d: d.find_element(
                By.CSS_SELECTOR,
                'tr[data-code="usd"] td.price'
            ).text.strip() != ""
        )

        # ====================================================
        # گرفتن قیمت تمام ارزها
        # ====================================================

        for currency in currencies:

            try:

                # ------------------------------------------------
                # Selector ارز
                # ------------------------------------------------

                selector = (
                    f'tr[data-code="{currency}"] td.price'
                )

                # ------------------------------------------------
                # صبر برای Load شدن قیمت همین ارز
                # ------------------------------------------------

                wait.until(
                    lambda d: d.find_element(
                        By.CSS_SELECTOR,
                        selector
                    ).text.strip() != ""
                )

                # ------------------------------------------------
                # دریافت قیمت
                # ------------------------------------------------

                price = driver.find_element(
                    By.CSS_SELECTOR,
                    selector
                ).text.strip()

                # ------------------------------------------------
                # بررسی خالی نبودن قیمت
                # ------------------------------------------------

                if not price:

                    raise ValueError(
                        "price_empty"
                    )

                # ------------------------------------------------
                # تبدیل قیمت به عدد
                # ------------------------------------------------

                try:

                    price = int(
                        price.replace(",", "")
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
                        reason=str(error),
                        error_type="parser_error"
                    )

                    continue

                # ------------------------------------------------
                # ذخیره قیمت
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

            except ValueError as error:

                # ----------------------------------------------
                # خطای داده همین Currency
                # ----------------------------------------------

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
                    reason=str(error),
                    error_type="parser_error"
                )

                continue

            except Exception as error:

                # ----------------------------------------------
                # خطای غیرمنتظره همین Currency
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
    # Contract خروجی استاندارد Scraper
    # ========================================================

    return {
        "source": SOURCE_NAME,
        "status": status,
        "prices": prices,
        "errors": errors
    }