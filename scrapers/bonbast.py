from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from bs4 import BeautifulSoup
import os
import logs.logger as logger


# ============================================================
# Source Configuration
# ============================================================

SOURCE_NAME = "bonbast"

URL = "https://bonbast.com"

REQUEST_TIMEOUT = 10


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

            sell_id = currency + "1"

            buy_id = currency + "2"

            try:

                sell_el = soup.find(id=sell_id)
                buy_el = soup.find(id=buy_id)

                if sell_el is None or buy_el is None:
                    raise ValueError("buy_or_sell_element_not_found")

                sell = sell_el.get_text(strip=True)
                buy = buy_el.get_text(strip=True)

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
            try:
                driver.quit()
            except Exception:
                pass
            driver = None

    # ========================================================
    # خروجی استاندارد Scraper
    # ========================================================

    return {
        "source": SOURCE_NAME,
        "status": status,
        "prices": prices,
        "errors": errors
    }