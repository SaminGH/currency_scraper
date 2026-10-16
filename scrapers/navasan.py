from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
import os
from bs4 import BeautifulSoup

import logs.logger as logger


# ============================================================
# تنظیمات
# ============================================================

SOURCE_NAME = "navasan"


def get_service():
    """
    Instantiate ChromeDriver Service dynamically.
    Relies on system PATH (e.g. /usr/bin/chromedriver on Linux),
    or uses CHROMEDRIVER_PATH environment variable if specified.
    """
    chromedriver_path = os.environ.get("CHROMEDRIVER_PATH", "").strip().strip("\"'").strip()
    if chromedriver_path:
        return Service(executable_path=chromedriver_path)
    return Service()


service = get_service()

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

        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--blink-settings=imagesEnabled=false")

        chrome_bin = os.environ.get("CHROME_BIN", "").strip().strip("\"'").strip() or os.environ.get("CHROME_PATH", "").strip().strip("\"'").strip()
        if chrome_bin:
            chrome_options.binary_location = chrome_bin

        driver = webdriver.Chrome(
            service=get_service(),
            options=chrome_options
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
        # گرفتن page source و بستن driver
        # ====================================================

        page_source = driver.page_source
        try:
            driver.quit()
        except Exception:
            pass
        finally:
            driver = None

        # ====================================================
        # پارس HTML با BeautifulSoup
        # ====================================================

        soup = BeautifulSoup(page_source, "html.parser")

        for currency in currencies:

            try:

                # ------------------------------------------------
                # استخراج قیمت با CSS Selector
                # ------------------------------------------------

                price_el = soup.select_one(f'tr[data-code="{currency}"] td.price')

                if price_el is None:
                    raise ValueError("price_element_not_found")

                price = price_el.get_text(strip=True)

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
            try:
                driver.quit()
            except Exception:
                pass
            driver = None

    # ========================================================
    # Contract خروجی استاندارد Scraper
    # ========================================================

    return {
        "source": SOURCE_NAME,
        "status": status,
        "prices": prices,
        "errors": errors
    }