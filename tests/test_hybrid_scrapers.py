import asyncio
import os
import sys
from unittest.mock import MagicMock, patch
import httpx
from selenium.common.exceptions import TimeoutException

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import scraper_manager
import scrapers.alanchand as alanchand
import scrapers.tgju as tgju
import scrapers.bonbast as bonbast
import scrapers.navasan as navasan


def test_function_signatures():
    assert asyncio.iscoroutinefunction(tgju.scrape), "tgju.scrape must be a coroutine function"
    assert asyncio.iscoroutinefunction(alanchand.scrape), "alanchand.scrape must be a coroutine function"
    assert not asyncio.iscoroutinefunction(bonbast.scrape), "bonbast.scrape must remain a sync function"
    assert not asyncio.iscoroutinefunction(navasan.scrape), "navasan.scrape must remain a sync function"
    assert "alanchand" in scraper_manager.ASYNC_SCRAPERS
    assert "tgju" in scraper_manager.ASYNC_SCRAPERS
    assert "bonbast" in scraper_manager.MULTIPROCESS_SCRAPERS
    assert "navasan" in scraper_manager.MULTIPROCESS_SCRAPERS


def test_tgju_exception_mapping():
    # 1. Timeout
    with patch("httpx.AsyncClient.get", side_effect=httpx.TimeoutException("mock timeout")):
        res = asyncio.run(tgju.scrape())
        assert res["status"] == "failed"
        assert res["errors"]["_scraper"]["type"] == "timeout"

    # 2. ConnectError
    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("mock connect error")):
        res = asyncio.run(tgju.scrape())
        assert res["status"] == "failed"
        assert res["errors"]["_scraper"]["type"] == "connection_error"

    # 3. HTTPStatusError 502
    mock_resp_500 = MagicMock()
    mock_resp_500.status_code = 502
    err_500 = httpx.HTTPStatusError("502 Bad Gateway", request=MagicMock(), response=mock_resp_500)
    with patch("httpx.AsyncClient.get", side_effect=err_500):
        res = asyncio.run(tgju.scrape())
        assert res["status"] == "failed"
        assert res["errors"]["_scraper"]["type"] == "http_5xx"

    # 4. HTTPStatusError 404
    mock_resp_404 = MagicMock()
    mock_resp_404.status_code = 404
    err_404 = httpx.HTTPStatusError("404 Not Found", request=MagicMock(), response=mock_resp_404)
    with patch("httpx.AsyncClient.get", side_effect=err_404):
        res = asyncio.run(tgju.scrape())
        assert res["status"] == "failed"
        assert res["errors"]["_scraper"]["type"] == "http_4xx"

    # 5. RequestError
    with patch("httpx.AsyncClient.get", side_effect=httpx.RequestError("mock general request error")):
        res = asyncio.run(tgju.scrape())
        assert res["status"] == "failed"
        assert res["errors"]["_scraper"]["type"] == "network_error"


def test_alanchand_exception_mapping():
    # 1. Timeout
    with patch("httpx.AsyncClient.get", side_effect=httpx.TimeoutException("mock timeout")):
        res = asyncio.run(alanchand.scrape())
        assert res["status"] == "failed"
        assert res["errors"]["_scraper"]["type"] == "timeout"

    # 2. ConnectError
    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("mock connect error")):
        res = asyncio.run(alanchand.scrape())
        assert res["status"] == "failed"
        assert res["errors"]["_scraper"]["type"] == "connection_error"

    # 3. HTTPStatusError 503
    mock_resp_503 = MagicMock()
    mock_resp_503.status_code = 503
    err_503 = httpx.HTTPStatusError("503 Service Unavailable", request=MagicMock(), response=mock_resp_503)
    with patch("httpx.AsyncClient.get", side_effect=err_503):
        res = asyncio.run(alanchand.scrape())
        assert res["status"] == "failed"
        assert res["errors"]["_scraper"]["type"] == "http_5xx"

    # 4. HTTPStatusError 403
    mock_resp_403 = MagicMock()
    mock_resp_403.status_code = 403
    err_403 = httpx.HTTPStatusError("403 Forbidden", request=MagicMock(), response=mock_resp_403)
    with patch("httpx.AsyncClient.get", side_effect=err_403):
        res = asyncio.run(alanchand.scrape())
        assert res["status"] == "failed"
        assert res["errors"]["_scraper"]["type"] == "http_4xx"

    # 5. RequestError
    with patch("httpx.AsyncClient.get", side_effect=httpx.RequestError("mock network error")):
        res = asyncio.run(alanchand.scrape())
        assert res["status"] == "failed"
        assert res["errors"]["_scraper"]["type"] == "network_error"


def test_async_scraper_timeout_and_cancellation():
    async def hanging_scraper():
        try:
            await asyncio.sleep(10)
            return {"source": "test_hang", "status": "complete", "prices": {}, "errors": {}}
        except asyncio.CancelledError:
            hanging_scraper.cancelled = True
            raise

    hanging_scraper.cancelled = False

    with patch.object(scraper_manager, "SOURCE_TIMEOUT", 0.2):
        res = asyncio.run(scraper_manager._run_async_source("test_hang", hanging_scraper))
        assert res["status"] == "failed"
        assert res["errors"]["_scraper"]["type"] == "timeout"
        assert hanging_scraper.cancelled, "Hanging coroutine must have received CancelledError"


def test_async_scraper_retry_behavior():
    call_count = 0

    async def flaky_scraper():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return {
                "source": "flaky",
                "status": "failed",
                "prices": {},
                "errors": {"_scraper": {"type": "timeout", "message": "temporary timeout"}},
            }
        return {
            "source": "flaky",
            "status": "complete",
            "prices": {"USD": {"price": 100000}},
            "errors": {},
        }

    with patch.object(scraper_manager, "RETRY_DELAY", 0.01):
        res = asyncio.run(scraper_manager._run_async_source("flaky", flaky_scraper))
        assert res["status"] == "complete"
        assert call_count == 3
        assert "USD" in res["prices"]


def test_client_cleanup_on_completion():
    client_closed = False

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            nonlocal client_closed
            client_closed = True
            return False

        async def get(self, url):
            mock_resp = MagicMock()
            mock_resp.text = "<html><body></body></html>"
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

    with patch("httpx.AsyncClient", MockAsyncClient):
        asyncio.run(tgju.scrape())
        assert client_closed, "tgju: httpx.AsyncClient must be closed cleanly via __aexit__"

    client_closed = False
    with patch("httpx.AsyncClient", MockAsyncClient):
        asyncio.run(alanchand.scrape())
        assert client_closed, "alanchand: httpx.AsyncClient must be closed cleanly via __aexit__"


def test_outer_cancellation_cancels_inner_task():
    inner_running = False

    async def slow_scraper():
        nonlocal inner_running
        inner_running = True
        try:
            await asyncio.sleep(5)
        finally:
            inner_running = False

    async def cancel_runner():
        task = asyncio.create_task(scraper_manager._run_async_source("test_cancel", slow_scraper))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(cancel_runner())
    assert not inner_running, "Inner task must be cancelled and not leaked when outer coroutine is cancelled"


def test_client_follow_redirects_configured():
    client_kwargs = {}

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            nonlocal client_kwargs
            client_kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

        async def get(self, url):
            mock_resp = MagicMock()
            mock_resp.text = "<html><body></body></html>"
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

    with patch("httpx.AsyncClient", MockAsyncClient):
        asyncio.run(tgju.scrape())
        assert client_kwargs.get("follow_redirects") is True, "tgju AsyncClient must have follow_redirects=True"

    client_kwargs = {}
    with patch("httpx.AsyncClient", MockAsyncClient):
        asyncio.run(alanchand.scrape())
        assert client_kwargs.get("follow_redirects") is True, "alanchand AsyncClient must have follow_redirects=True"


def test_scrapers_dict_dispatch_override():
    mock_called = False

    async def mock_tgju():
        nonlocal mock_called
        mock_called = True
        return {
            "source": "tgju",
            "status": "complete",
            "prices": {"USD": {"price": 12345}},
            "errors": {},
        }

    with patch.dict(scraper_manager.SCRAPERS, {"tgju": mock_tgju}, clear=True), \
         patch.dict(scraper_manager.ASYNC_SCRAPERS, {"tgju": mock_tgju}, clear=True), \
         patch.dict(scraper_manager.MULTIPROCESS_SCRAPERS, {}, clear=True):
        res = asyncio.run(scraper_manager._run_all_async())
        assert mock_called, "Overriding SCRAPERS['tgju'] must be respected by _run_all_async"
        assert res["tgju"]["prices"]["USD"]["price"] == 12345


def _mock_sync_worker():
    return {
        "source": "mock_sync",
        "status": "complete",
        "prices": {},
        "errors": {},
    }


def test_run_all_in_running_event_loop():
    async def mock_async():
        return {
            "source": "mock_src",
            "status": "complete",
            "prices": {},
            "errors": {},
        }

    test_scrapers = {
        "mock_src": mock_async,
        "mock_sync": _mock_sync_worker,
    }

    async def runner():
        with patch.dict(scraper_manager.SCRAPERS, test_scrapers, clear=True), \
             patch.dict(scraper_manager.ASYNC_SCRAPERS, {"mock_src": mock_async}, clear=True), \
             patch.dict(scraper_manager.MULTIPROCESS_SCRAPERS, {"mock_sync": _mock_sync_worker}, clear=True):
            return scraper_manager.run_all()

    res = asyncio.run(runner())
    assert "mock_src" in res
    assert res["mock_src"]["status"] == "complete"
    assert "mock_sync" in res
    assert res["mock_sync"]["status"] == "complete"


def test_mp_source_process_spawn_failure():
    with patch("multiprocessing.Process.start", side_effect=OSError("Process limit exceeded")):
        res = asyncio.run(scraper_manager._run_mp_source("fail_spawn", MagicMock(), "run1", "snap1"))
        assert res["status"] == "failed"
        assert res["errors"]["_scraper"]["type"] == "manager_exception"


def _get_service_path(svc):
    return getattr(svc, "executable_path", getattr(svc, "path", None))


def test_bonbast_dynamic_service():
    with patch.dict(os.environ, {}, clear=True):
        svc = bonbast.get_service()
        assert svc is not None

    with patch.dict(os.environ, {"CHROMEDRIVER_PATH": "/opt/custom/chromedriver"}):
        svc = bonbast.get_service()
        assert _get_service_path(svc) == "/opt/custom/chromedriver"

    with patch.dict(os.environ, {"CHROMEDRIVER_PATH": " '\" /opt/custom/chromedriver \"' "}):
        svc = bonbast.get_service()
        assert _get_service_path(svc) == "/opt/custom/chromedriver"

    with patch.dict(os.environ, {"CHROMEDRIVER_PATH": "   "}):
        svc = bonbast.get_service()
        assert _get_service_path(svc) != "   "


def test_navasan_dynamic_service():
    with patch.dict(os.environ, {}, clear=True):
        svc = navasan.get_service()
        assert svc is not None

    with patch.dict(os.environ, {"CHROMEDRIVER_PATH": "/usr/bin/chromedriver"}):
        svc = navasan.get_service()
        assert _get_service_path(svc) == "/usr/bin/chromedriver"

    with patch.dict(os.environ, {"CHROMEDRIVER_PATH": " '\" /usr/bin/chromedriver \"' "}):
        svc = navasan.get_service()
        assert _get_service_path(svc) == "/usr/bin/chromedriver"

    with patch.dict(os.environ, {"CHROMEDRIVER_PATH": "   "}):
        svc = navasan.get_service()
        assert _get_service_path(svc) != "   "


def test_headless_chrome_options():
    required_flags = {
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--blink-settings=imagesEnabled=false",
    }

    # Verify bonbast options
    with patch("selenium.webdriver.Chrome") as mock_chrome:
        mock_driver = MagicMock()
        mock_driver.page_source = "<html></html>"
        mock_chrome.return_value = mock_driver
        with patch.object(bonbast, "currencies", []):
            bonbast.scrape()
        assert mock_chrome.called
        options = mock_chrome.call_args[1]["options"]
        for flag in required_flags:
            assert flag in options.arguments, f"bonbast missing flag: {flag}"

    # Verify navasan options
    with patch("selenium.webdriver.Chrome") as mock_chrome:
        mock_driver = MagicMock()
        mock_driver.page_source = "<html></html>"
        mock_chrome.return_value = mock_driver
        with patch.object(navasan, "currencies", []):
            navasan.scrape()
        assert mock_chrome.called
        options = mock_chrome.call_args[1]["options"]
        for flag in required_flags:
            assert flag in options.arguments, f"navasan missing flag: {flag}"


def test_driver_quit_called_on_exception():
    # Verify bonbast calls driver.quit() in finally block on exception
    with patch("selenium.webdriver.Chrome") as mock_chrome:
        mock_driver = MagicMock()
        mock_driver.get.side_effect = TimeoutException("Page load timed out")
        mock_chrome.return_value = mock_driver
        res = bonbast.scrape()
        assert res["status"] == "failed"
        assert mock_driver.quit.called, "bonbast: driver.quit() must be called on exception in finally block"

    # Verify navasan calls driver.quit() in finally block on exception
    with patch("selenium.webdriver.Chrome") as mock_chrome:
        mock_driver = MagicMock()
        mock_driver.get.side_effect = TimeoutException("Page load timed out")
        mock_chrome.return_value = mock_driver
        res = navasan.scrape()
        assert res["status"] == "failed"
        assert mock_driver.quit.called, "navasan: driver.quit() must be called on exception in finally block"


def test_kill_process_tree_hygiene():
    # 1. Invalid or boundary PIDs (including current process PID) should be no-ops
    scraper_manager._kill_process_tree(None)
    scraper_manager._kill_process_tree(0)
    scraper_manager._kill_process_tree(1)
    scraper_manager._kill_process_tree(-1)
    scraper_manager._kill_process_tree(True)
    scraper_manager._kill_process_tree(False)
    scraper_manager._kill_process_tree("not_an_int")
    scraper_manager._kill_process_tree(os.getpid())

    # 2. Mock process tree kill
    mock_parent = MagicMock()
    mock_child1 = MagicMock()
    mock_child2 = MagicMock()
    mock_parent.children.return_value = [mock_child1, mock_child2]

    with patch("psutil.Process", return_value=mock_parent) as mock_psutil_proc, \
         patch("psutil.wait_procs", return_value=([mock_child1, mock_child2, mock_parent], [])) as mock_wait:
        scraper_manager._kill_process_tree(12345)
        mock_psutil_proc.assert_called_once_with(12345)
        mock_child1.kill.assert_called()
        mock_child2.kill.assert_called()
        mock_parent.kill.assert_called()
        mock_wait.assert_called_once()

    # 3. AccessDenied on children lookup should still kill parent
    mock_parent_denied = MagicMock()
    import psutil
    mock_parent_denied.children.side_effect = psutil.AccessDenied()
    with patch("psutil.Process", return_value=mock_parent_denied):
        scraper_manager._kill_process_tree(12346)
        mock_parent_denied.kill.assert_called()

    # 4. Multi-pass kill when stubborn processes linger after first wait_procs
    stubborn_proc = MagicMock()
    mock_parent_stubborn = MagicMock()
    mock_parent_stubborn.children.return_value = [stubborn_proc]
    with patch("psutil.Process", return_value=mock_parent_stubborn), \
         patch("psutil.wait_procs", side_effect=[
             ([mock_parent_stubborn], [stubborn_proc]),  # first pass: stubborn_proc still alive
             ([stubborn_proc], [])  # second pass: stubborn_proc reaped
         ]) as mock_multi_wait:
        scraper_manager._kill_process_tree(12347)
        assert mock_multi_wait.call_count == 2
        stubborn_proc.kill.assert_called()


if __name__ == "__main__":
    test_function_signatures()
    test_tgju_exception_mapping()
    test_alanchand_exception_mapping()
    test_async_scraper_timeout_and_cancellation()
    test_async_scraper_retry_behavior()
    test_client_cleanup_on_completion()
    test_outer_cancellation_cancels_inner_task()
    test_client_follow_redirects_configured()
    test_scrapers_dict_dispatch_override()
    test_run_all_in_running_event_loop()
    test_mp_source_process_spawn_failure()
    test_bonbast_dynamic_service()
    test_navasan_dynamic_service()
    test_headless_chrome_options()
    test_driver_quit_called_on_exception()
    test_kill_process_tree_hygiene()
    print("ALL UNIT TESTS PASSED SUCCESSFULLY!")
