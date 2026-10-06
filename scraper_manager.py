import asyncio
import multiprocessing
import queue
from dataclasses import dataclass
import time

import logs.logger as logger

import scrapers.alanchand as alanchand
import scrapers.navasan as navasan
import scrapers.bonbast as bonbast
import scrapers.tgju as tgju


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

ASYNC_SCRAPERS = {
    "alanchand": alanchand.scrape,
    "tgju": tgju.scrape,
}

MULTIPROCESS_SCRAPERS = {
    "bonbast": bonbast.scrape,
    "navasan": navasan.scrape,
}

SCRAPERS = {
    "alanchand": alanchand.scrape,
    "navasan":  navasan.scrape,
    "bonbast": bonbast.scrape,
    "tgju": tgju.scrape,
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
                "message": message,
            }
        },
    }


def _format_result(source, result):
    if isinstance(result, ScraperExecutionResult):
        return {
            "source": result.source,
            "status": result.status,
            "prices": result.prices,
            "errors": result.errors,
        }
    elif isinstance(result, dict):
        return {
            "source": result.get("source", source),
            "status": result.get("status", "failed"),
            "prices": result.get("prices", {}) if isinstance(result.get("prices"), dict) else {},
            "errors": result.get("errors", {}) if isinstance(result.get("errors"), dict) else {},
        }
    return _build_failed_result(
        source=source,
        error_type="invalid_worker_result",
        message="worker returned invalid result",
    )


# ============================================================
# اجرای همگام یک Scraper (برای Multiprocessing)
# ============================================================

def _run_sync_scraper(source, scraper):
    """
    اجرای یک scraper همگام با Retry و Failure Isolation.
    """

    attempts = 0

    while attempts <= MAX_RETRIES:

        attempts += 1

        logger.log_event(
            level="INFO",
            event="scraper_started",
            component="scraper_manager",
            source=source,
            attempt=attempts,
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
                    reason="retryable_error",
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
                attempts=attempts,
            )

            return ScraperExecutionResult(
                source=source,
                status=status,
                prices=prices,
                errors=errors,
                attempts=attempts,
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
                reason=str(error),
            )

            return ScraperExecutionResult(
                source=source,
                status="failed",
                prices={},
                errors={
                    "_scraper": {
                        "type": "manager_exception",
                        "message": str(error),
                    }
                },
                attempts=attempts,
            )

    return ScraperExecutionResult(
        source=source,
        status="failed",
        prices={},
        errors={
            "_scraper": {
                "type": "retry_exhausted",
                "message": "maximum retry attempts reached",
            }
        },
        attempts=attempts,
    )


# حفظ سازگاری نام قبلی تابع
_run_scraper = _run_sync_scraper


# ============================================================
# Worker Process برای Multiprocessing
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

        result = _run_sync_scraper(
            source,
            scraper,
        )

        result_queue.put(
            (
                source,
                result,
            )
        )

    except Exception as error:

        logger.log_event(
            level="ERROR",
            event="scraper_worker_failed",
            component="scraper_manager",
            source=source,
            error_type=type(error).__name__,
            reason=str(error),
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
                            "message": str(error),
                        }
                    },
                    attempts=0,
                ),
            )
        )


# ============================================================
# مانیتورینگ غیرمسدودکننده Process در Asyncio
# ============================================================

async def _run_mp_source(source, scraper, run_id, snapshot_id):
    """
    اجرای یک scraper چندپردازشی با Queue اختصاصی و نظارت غیرمسدودکننده.
    """

    result_queue = multiprocessing.Queue()
    process = None

    try:

        process = multiprocessing.Process(
            target=_scraper_worker,
            args=(
                source,
                scraper,
                result_queue,
                run_id,
                snapshot_id,
            ),
            name=f"scraper-{source}",
        )

        start_time = time.monotonic()
        process.start()

        while True:

            # ------------------------------------------------
            # دریافت نتیجه در صورت آماده بودن
            # ------------------------------------------------

            try:

                _, result = result_queue.get_nowait()

                process.join(timeout=0.5)

                return _format_result(source, result)

            except queue.Empty:

                pass

            # ------------------------------------------------
            # بررسی خاتمه غیرمنتظره Process
            # ------------------------------------------------

            if not process.is_alive():

                process.join(timeout=0.2)

                try:

                    _, result = result_queue.get(timeout=0.5)

                    return _format_result(source, result)

                except queue.Empty:

                    return _build_failed_result(
                        source=source,
                        error_type="process_exited_without_result",
                        message="scraper process exited without returning a result",
                    )

            # ------------------------------------------------
            # بررسی Timeout
            # ------------------------------------------------

            elapsed = time.monotonic() - start_time

            if elapsed >= SOURCE_TIMEOUT:

                logger.log_event(
                    level="ERROR",
                    event="scraper_timeout",
                    component="scraper_manager",
                    source=source,
                    timeout=SOURCE_TIMEOUT,
                )

                if process.is_alive():

                    process.terminate()

                    process.join(timeout=1)

                    if process.is_alive():

                        logger.log_event(
                            level="ERROR",
                            event="scraper_process_terminate_failed",
                            component="scraper_manager",
                            source=source,
                        )

                return _build_failed_result(
                    source=source,
                    error_type="timeout",
                    message=f"scraper exceeded {SOURCE_TIMEOUT} seconds",
                )

            await asyncio.sleep(PROCESS_POLL_INTERVAL)

    except Exception as error:

        logger.log_event(
            level="ERROR",
            event="scraper_exception",
            component="scraper_manager",
            source=source,
            attempt=0,
            error_type=type(error).__name__,
            reason=str(error),
        )

        return _build_failed_result(
            source=source,
            error_type="manager_exception",
            message=str(error),
        )

    finally:

        if process is not None and process.is_alive():

            process.terminate()

            process.join(timeout=1)

        try:

            result_queue.close()
            result_queue.join_thread()

        except Exception:

            pass


# ============================================================
# اجرای Scraperهای Asynchronous
# ============================================================

async def _run_async_scraper(source, scraper):
    """
    اجرای یک scraper ناهمگام با Retry و Failure Isolation.
    """

    attempts = 0

    while attempts <= MAX_RETRIES:

        attempts += 1

        logger.log_event(
            level="INFO",
            event="scraper_started",
            component="scraper_manager",
            source=source,
            attempt=attempts,
        )

        try:

            result = await scraper()

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
                    reason="retryable_error",
                )

                await asyncio.sleep(RETRY_DELAY)

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
                attempts=attempts,
            )

            return {
                "source": source,
                "status": status,
                "prices": prices,
                "errors": errors,
            }

        except Exception as error:

            logger.log_event(
                level="ERROR",
                event="scraper_exception",
                component="scraper_manager",
                source=source,
                attempt=attempts,
                error_type=type(error).__name__,
                reason=str(error),
            )

            return {
                "source": source,
                "status": "failed",
                "prices": {},
                "errors": {
                    "_scraper": {
                        "type": "manager_exception",
                        "message": str(error),
                    }
                },
            }

    return {
        "source": source,
        "status": "failed",
        "prices": {},
        "errors": {
            "_scraper": {
                "type": "retry_exhausted",
                "message": "maximum retry attempts reached",
            }
        },
    }


async def _run_async_source(source, scraper):
    """
    اجرای یک source ناهمگام با timeout سختگیرانه SOURCE_TIMEOUT و پاکسازی اتصالات.
    """

    task = asyncio.create_task(_run_async_scraper(source, scraper))

    try:

        result = await asyncio.wait_for(
            asyncio.shield(task),
            timeout=SOURCE_TIMEOUT,
        )

        return _format_result(source, result)

    except (asyncio.TimeoutError, TimeoutError):

        logger.log_event(
            level="ERROR",
            event="scraper_timeout",
            component="scraper_manager",
            source=source,
            timeout=SOURCE_TIMEOUT,
        )

        return _build_failed_result(
            source=source,
            error_type="timeout",
            message=f"scraper exceeded {SOURCE_TIMEOUT} seconds",
        )

    except Exception as error:

        logger.log_event(
            level="ERROR",
            event="scraper_exception",
            component="scraper_manager",
            source=source,
            attempt=0,
            error_type=type(error).__name__,
            reason=str(error),
        )

        return _build_failed_result(
            source=source,
            error_type="manager_exception",
            message=str(error),
        )

    finally:

        if not task.done():

            task.cancel()

            try:

                await task

            except (asyncio.CancelledError, Exception):

                pass


# ============================================================
# هماهنگ‌سازی تمام Scraperها در Asyncio
# ============================================================

async def _run_all_async():
    """
    هماهنگ‌سازی همزمان تمام scraperهای async و multiprocess با asyncio.gather.
    """

    logger.log_event(
        level="INFO",
        event="scraper_manager_started",
        component="scraper_manager",
        sources=len(SCRAPERS),
    )

    run_id = logger.get_run_id()

    snapshot_id = logger.get_snapshot_id()

    tasks = []
    sources = []

    for source in SCRAPERS:

        sources.append(source)
        scraper = SCRAPERS[source]

        if source in ASYNC_SCRAPERS or asyncio.iscoroutinefunction(scraper):

            tasks.append(
                _run_async_source(source, scraper)
            )

        else:

            tasks.append(
                _run_mp_source(
                    source,
                    scraper,
                    run_id,
                    snapshot_id,
                )
            )

    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    results = {}

    for source, res in zip(sources, raw_results):

        if isinstance(res, Exception):

            logger.log_event(
                level="ERROR",
                event="scraper_exception",
                component="scraper_manager",
                source=source,
                attempt=0,
                error_type=type(res).__name__,
                reason=str(res),
            )

            results[source] = _build_failed_result(
                source=source,
                error_type="manager_exception",
                message=str(res),
            )

        elif isinstance(res, dict):

            results[source] = res

        else:

            results[source] = _build_failed_result(
                source=source,
                error_type="invalid_worker_result",
                message="worker returned invalid result",
            )

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
        failed=failed,
    )

    return results


# ============================================================
# نقطه ورود عمومی همگام
# ============================================================

def run_all():
    """
    اجرای تمام scraperهای فعال به صورت concurrent.

    - Async scrapers (alanchand, tgju) از طریق asyncio
    - Multiprocess scrapers (bonbast, navasan) از طریق Process و Queue اختصاصی
    - نقطه ورود همگام سازگار با scraper_output و main
    """

    try:

        loop = asyncio.get_running_loop()

    except RuntimeError:

        loop = None

    if loop and loop.is_running():

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:

            future = executor.submit(lambda: asyncio.run(_run_all_async()))

            return future.result()

    else:

        return asyncio.run(_run_all_async())