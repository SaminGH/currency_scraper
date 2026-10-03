import multiprocessing
import queue
from dataclasses import dataclass
import time

import logger

import scrapers.alanchand
import scrapers.navasan
import scrapers.bonbast
import scrapers.tgju


# ============================================================
# تنظیمات
# ============================================================

MAX_WORKERS = 4

# حداکثر زمان مجاز برای هر source، شامل تمام retryها
SOURCE_TIMEOUT = 30

MAX_RETRIES = 2

RETRY_DELAY = 1

# فاصله بررسی وضعیت Processها
PROCESS_POLL_INTERVAL = 0.05


# ============================================================
# ثبت Scraperها
# ============================================================

SCRAPERS = {
    "alanchand": scrapers.alanchand.scrape,
    "navasan":  scrapers.navasan.scrape,
    "bonbast": scrapers.bonbast.scrape,
    "tgju": scrapers.tgju.scrape,
}


# ============================================================
# Retryable Errors
# ============================================================

RETRYABLE_ERROR_TYPES = {
    "timeout",
    "connection_error",
    "network_error",
    "http_5xx",
}


# ============================================================
# Result داخلی Manager
# ============================================================

@dataclass
class ScraperExecutionResult:
    source: str
    status: str
    prices: dict
    errors: dict
    attempts: int


# ============================================================
# تشخیص Retryable بودن Error
# ============================================================

def is_retryable_error(error_type):
    return error_type in RETRYABLE_ERROR_TYPES


def should_retry(result):
    """
    بررسی می‌کند آیا نتیجه فعلی ارزش Retry کردن دارد یا نه.
    """

    if not isinstance(result, dict):
        return False

    errors = result.get("errors", {})

    if not isinstance(errors, dict):
        return False

    for error in errors.values():

        if not isinstance(error, dict):
            continue

        error_type = error.get("type")

        if is_retryable_error(error_type):
            return True

    return False


# ============================================================
# اجرای یک Scraper
# ============================================================

def _run_scraper(source, scraper):
    """
    اجرای یک scraper با Retry و Failure Isolation.

    Timeout واقعی توسط Process والد در run_all()
    کنترل می‌شود.
    """

    attempts = 0

    while attempts <= MAX_RETRIES:

        attempts += 1

        logger.log_event(
            level="INFO",
            event="scraper_started",
            component="scraper_manager",
            source=source,
            attempt=attempts
        )

        try:

            result = scraper()

            # ------------------------------------------------
            # بررسی ساختار خروجی
            # ------------------------------------------------

            if not isinstance(result, dict):

                raise ValueError(
                    "scraper_result_is_not_dict"
                )

            result_source = result.get("source")

            if result_source != source:

                raise ValueError(
                    "scraper_source_mismatch"
                )

            status = result.get("status")

            prices = result.get("prices", {})

            errors = result.get("errors", {})

            if not isinstance(prices, dict):

                raise ValueError(
                    "scraper_prices_is_not_dict"
                )

            if not isinstance(errors, dict):

                raise ValueError(
                    "scraper_errors_is_not_dict"
                )

            # ------------------------------------------------
            # بررسی Retry
            # ------------------------------------------------

            if (
                status == "failed"
                and should_retry(result)
                and attempts <= MAX_RETRIES
            ):

                logger.log_event(
                    level="WARNING",
                    event="scraper_retry",
                    component="scraper_manager",
                    source=source,
                    attempt=attempts,
                    reason="retryable_error"
                )

                time.sleep(RETRY_DELAY)

                continue

            # ------------------------------------------------
            # نتیجه نهایی
            # ------------------------------------------------

            logger.log_event(
                level=(
                    "INFO"
                    if status in ("complete", "partial")
                    else "ERROR"
                ),
                event="scraper_completed",
                component="scraper_manager",
                source=source,
                status=status,
                currencies=len(prices),
                attempts=attempts
            )

            return ScraperExecutionResult(
                source=source,
                status=status,
                prices=prices,
                errors=errors,
                attempts=attempts
            )

        except Exception as error:

            # ------------------------------------------------
            # Exception غیرمنتظره
            # ------------------------------------------------

            logger.log_event(
                level="ERROR",
                event="scraper_exception",
                component="scraper_manager",
                source=source,
                attempt=attempts,
                error_type=type(error).__name__,
                reason=str(error)
            )

            # -----------------------------------------------
            # Exception غیرقابل تشخیص:
            # فعلاً Retry نمی‌کنیم
            # -----------------------------------------------

            return ScraperExecutionResult(
                source=source,
                status="failed",
                prices={},
                errors={
                    "_scraper": {
                        "type": "manager_exception",
                        "message": str(error)
                    }
                },
                attempts=attempts
            )

    # ========================================================
    # نباید به اینجا برسیم، ولی Failure Isolation حفظ شود
    # ========================================================

    return ScraperExecutionResult(
        source=source,
        status="failed",
        prices={},
        errors={
            "_scraper": {
                "type": "retry_exhausted",
                "message": "maximum retry attempts reached"
            }
        },
        attempts=attempts
    )


# ============================================================
# Worker Process
# ============================================================

def _scraper_worker(source, scraper, result_queue, run_id, snapshot_id):
    """
    Wrapper مربوط به Process.

    خود scraper هیچ اطلاعی از Queue یا Process ندارد.
    فقط result خودش را return می‌کند و این worker
    آن را داخل Queue قرار می‌دهد.
    """

    logger.set_run_id(run_id)
    logger.set_snapshot_id(snapshot_id)

    try:

        result = _run_scraper(
            source,
            scraper
        )

        result_queue.put(
            (
                source,
                result
            )
        )

    except Exception as error:

        logger.log_event(
            level="ERROR",
            event="scraper_worker_failed",
            component="scraper_manager",
            source=source,
            error_type=type(error).__name__,
            reason=str(error)
        )

        result_queue.put(
            (
                source,
                ScraperExecutionResult(
                    source=source,
                    status="failed",
                    prices={},
                    errors={
                        "_scraper": {
                            "type": "worker_exception",
                            "message": str(error)
                        }
                    },
                    attempts=0
                )
            )
        )


# ============================================================
# ساخت نتیجه Failed
# ============================================================

def _build_failed_result(source, error_type, message):
    return {
        "source": source,
        "status": "failed",
        "prices": {},
        "errors": {
            "_scraper": {
                "type": error_type,
                "message": message
            }
        }
    }


# ============================================================
# اجرای تمام Scraperها
# ============================================================

def run_all():
    """
    اجرای تمام scraperهای فعال به صورت concurrent با Process.

    هر source timeout مستقل دارد.
    SOURCE_TIMEOUT شامل کل اجرای scraper و تمام retryهای آن است.
    """

    logger.log_event(
        level="INFO",
        event="scraper_manager_started",
        component="scraper_manager",
        sources=len(SCRAPERS)
    )

    results = {}
    
    run_id = logger.get_run_id()
    
    snapshot_id = logger.get_snapshot_id()
    
    result_queue = multiprocessing.Queue()

    processes = {}

    started_at = {}

    # ========================================================
    # اجرای Processها
    # ========================================================

    for source, scraper in SCRAPERS.items():

        process = multiprocessing.Process(
            target=_scraper_worker,
            args=(
                source,
                scraper,
                result_queue,
                run_id,
                snapshot_id
            ),
            name=f"scraper-{source}"
        )

        process.start()

        processes[source] = process
        started_at[source] = time.monotonic()

    # ========================================================
    # مانیتور Processها
    # ========================================================

    remaining_sources = set(processes.keys())

    while remaining_sources:

        # ----------------------------------------------------
        # دریافت تمام resultهای موجود در Queue
        # ----------------------------------------------------

        while True:

            try:

                source, result = result_queue.get_nowait()

            except queue.Empty:

                break

            except Exception as error:

                logger.log_event(
                    level="ERROR",
                    event="scraper_queue_failed",
                    component="scraper_manager",
                    error_type=type(error).__name__,
                    reason=str(error)
                )

                break

            # ------------------------------------------------
            # ثبت نتیجه
            # ------------------------------------------------

            if source in remaining_sources:

                if isinstance(result, ScraperExecutionResult):

                    results[source] = {
                        "source": result.source,
                        "status": result.status,
                        "prices": result.prices,
                        "errors": result.errors
                    }

                else:

                    results[source] = _build_failed_result(
                        source=source,
                        error_type="invalid_worker_result",
                        message="worker returned invalid result"
                    )

                remaining_sources.remove(source)

        # ----------------------------------------------------
        # بررسی Processهای تمام‌شده و Timeout
        # ----------------------------------------------------

        current_time = time.monotonic()

        for source in list(remaining_sources):

            process = processes[source]

            # ------------------------------------------------
            # Process تمام شده ولی هنوز result ثبت نشده
            # ------------------------------------------------

            if not process.is_alive():

                process.join(timeout=0)

                # یک فرصت کوتاه برای flush شدن Queue
                try:

                    source_from_queue, result = result_queue.get(
                        timeout=0.1
                    )

                    if source_from_queue == source:

                        if isinstance(
                            result,
                            ScraperExecutionResult
                        ):

                            results[source] = {
                                "source": result.source,
                                "status": result.status,
                                "prices": result.prices,
                                "errors": result.errors
                            }

                        else:

                            results[source] = _build_failed_result(
                                source=source,
                                error_type="invalid_worker_result",
                                message="worker returned invalid result"
                            )

                        remaining_sources.remove(source)

                        continue

                    # اگر نتیجه مربوط به source دیگری بود
                    if source_from_queue in remaining_sources:

                        other_result = result

                        if isinstance(
                            other_result,
                            ScraperExecutionResult
                        ):

                            results[source_from_queue] = {
                                "source": other_result.source,
                                "status": other_result.status,
                                "prices": other_result.prices,
                                "errors": other_result.errors
                            }

                        else:

                            results[source_from_queue] = _build_failed_result(
                                source=source_from_queue,
                                error_type="invalid_worker_result",
                                message="worker returned invalid result"
                            )

                        remaining_sources.remove(source_from_queue)

                except queue.Empty:

                    results[source] = _build_failed_result(
                        source=source,
                        error_type="process_exited_without_result",
                        message="scraper process exited without returning a result"
                    )

                    remaining_sources.remove(source)

                continue

            # ------------------------------------------------
            # Timeout واقعی برای همین source
            # ------------------------------------------------

            elapsed = current_time - started_at[source]

            if elapsed >= SOURCE_TIMEOUT:

                logger.log_event(
                    level="ERROR",
                    event="scraper_timeout",
                    component="scraper_manager",
                    source=source,
                    timeout=SOURCE_TIMEOUT
                )

                # ------------------------------------------------
                # terminate واقعی Process
                # ------------------------------------------------

                process.terminate()

                process.join(timeout=1)

                # ------------------------------------------------
                # اگر terminate کافی نبود
                # ------------------------------------------------

                if process.is_alive():

                    logger.log_event(
                        level="ERROR",
                        event="scraper_process_terminate_failed",
                        component="scraper_manager",
                        source=source
                    )

                results[source] = _build_failed_result(
                    source=source,
                    error_type="timeout",
                    message=(
                        f"scraper exceeded "
                        f"{SOURCE_TIMEOUT} seconds"
                    )
                )

                remaining_sources.remove(source)

        # ----------------------------------------------------
        # جلوگیری از busy loop
        # ----------------------------------------------------

        if remaining_sources:

            time.sleep(PROCESS_POLL_INTERVAL)

    # ========================================================
    # Cleanup
    # ========================================================

    for source, process in processes.items():

        if process.is_alive():

            process.terminate()

        process.join(timeout=1)

    try:

        result_queue.close()
        result_queue.join_thread()

    except Exception:

        pass

    # ========================================================
    # Manager Summary
    # ========================================================

    successful = sum(
        1
        for result in results.values()
        if result.get("status") == "complete"
    )

    partial = sum(
        1
        for result in results.values()
        if result.get("status") == "partial"
    )

    failed = sum(
        1
        for result in results.values()
        if result.get("status") == "failed"
    )

    logger.log_event(
        level=(
            "INFO"
            if failed == 0
            else "WARNING"
        ),
        event="scraper_manager_completed",
        component="scraper_manager",
        sources=len(results),
        successful=successful,
        partial=partial,
        failed=failed
    )

    return results