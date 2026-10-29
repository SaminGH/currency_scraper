import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock

# Mock psycopg2 and dotenv if missing so tests run cleanly without external dependencies
try:
    import psycopg2  # noqa: F401
except ImportError:
    psycopg2_mock = MagicMock()
    sys.modules["psycopg2"] = psycopg2_mock
    sys.modules["psycopg2.extras"] = MagicMock()

try:
    import dotenv  # noqa: F401
except ImportError:
    dotenv_mock = MagicMock()
    dotenv_mock.load_dotenv = MagicMock()
    sys.modules["dotenv"] = dotenv_mock

try:
    import psutil  # noqa: F401
except ImportError:
    psutil_mock = MagicMock()
    sys.modules["psutil"] = psutil_mock

try:
    import main  # noqa: F401
except Exception:
    main_mock = MagicMock()
    main_mock.run_pipeline = MagicMock(return_value={"status": "complete", "snapshot_id": 1, "published_rates": 10})
    sys.modules["main"] = main_mock

import server


class TestServerHealthEndpoint(unittest.TestCase):
    """
    Test suite verifying HTTP health check and server response telemetry
    as mandated by DOCKER_DEPLOYMENT_STANDARDS-V1.0.0.
    """

    @classmethod
    def setUpClass(cls):
        # Save original DATABASE_URL and set mock value for test isolation
        cls.orig_db_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "postgresql://mock_user:mock_pass@localhost:5432/mock_db"

        # Bind to port 10001 for test isolation
        cls.test_port = 10001
        cls.server = ThreadingHTTPServer(("127.0.0.1", cls.test_port), server.HealthRequestHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=2)
        if cls.orig_db_url is not None:
            os.environ["DATABASE_URL"] = cls.orig_db_url
        else:
            os.environ.pop("DATABASE_URL", None)

    def test_health_endpoint_returns_200(self):
        url = f"http://127.0.0.1:{self.test_port}/health"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get_content_type(), "application/json")
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("status"), "healthy")
            self.assertEqual(data.get("service"), "currency-pipeline")
            self.assertIn("uptime_seconds", data)
            self.assertIn("database", data)
            self.assertTrue(data["database"].get("configured"))
            self.assertIn("scheduler", data)

    def test_root_endpoint_returns_200(self):
        url = f"http://127.0.0.1:{self.test_port}/"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("status"), "healthy")

    def test_health_trailing_slash_returns_200(self):
        url = f"http://127.0.0.1:{self.test_port}/health/"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("status"), "healthy")

    def test_health_with_query_params_returns_200(self):
        url = f"http://127.0.0.1:{self.test_port}/health?check=1"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("status"), "healthy")

    def test_root_with_query_params_returns_200(self):
        url = f"http://127.0.0.1:{self.test_port}/?utm_source=chatgpt.com"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("status"), "healthy")

    def test_health_trailing_slash_with_query_params_returns_200(self):
        url = f"http://127.0.0.1:{self.test_port}/health/?check=1"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("status"), "healthy")

    def test_unknown_path_returns_404(self):
        url = f"http://127.0.0.1:{self.test_port}/nonexistent"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(url)
        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        ctx.exception.close()
        self.assertEqual(body.get("error"), "Not Found")
        self.assertEqual(body.get("path"), "/nonexistent")

    def test_unknown_path_with_query_params_returns_404(self):
        url = f"http://127.0.0.1:{self.test_port}/nonexistent?foo=bar"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(url)
        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        ctx.exception.close()
        self.assertEqual(body.get("error"), "Not Found")
        self.assertEqual(body.get("path"), "/nonexistent?foo=bar")

    def test_database_unconfigured_reports_degraded_status(self):
        saved_db_url = os.environ.pop("DATABASE_URL", None)
        try:
            url = f"http://127.0.0.1:{self.test_port}/health"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data.get("status"), "degraded")
                self.assertFalse(data.get("database", {}).get("configured"))
        finally:
            if saved_db_url is not None:
                os.environ["DATABASE_URL"] = saved_db_url

    def test_head_health_endpoint_returns_200_without_body(self):
        url = f"http://127.0.0.1:{self.test_port}/health"
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get_content_type(), "application/json")
            content_length = resp.headers.get("Content-Length")
            self.assertIsNotNone(content_length)
            self.assertGreater(int(content_length), 0)
            body = resp.read()
            self.assertEqual(body, b"")

    def test_head_root_endpoint_returns_200_without_body(self):
        url = f"http://127.0.0.1:{self.test_port}/"
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.read(), b"")

    def test_head_unknown_path_returns_404_without_body(self):
        url = f"http://127.0.0.1:{self.test_port}/nonexistent"
        req = urllib.request.Request(url, method="HEAD")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 404)
        self.assertEqual(ctx.exception.read(), b"")
        ctx.exception.close()

    def test_multiple_trailing_slashes_returns_200(self):
        url = f"http://127.0.0.1:{self.test_port}/health///"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("status"), "healthy")

    def test_content_length_header_matches_body_size(self):
        url = f"http://127.0.0.1:{self.test_port}/health"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            raw_body = resp.read()
            self.assertEqual(int(resp.headers.get("Content-Length")), len(raw_body))

    def test_pipeline_last_run_failure_reports_degraded_status(self):
        with server._state_lock:
            orig_status = server.pipeline_state["scheduler"]["last_run"]["status"]
            orig_error = server.pipeline_state["scheduler"]["last_run"]["error"]
            server.pipeline_state["scheduler"]["last_run"]["status"] = "failed"
            server.pipeline_state["scheduler"]["last_run"]["error"] = "database connection timeout"

        try:
            url = f"http://127.0.0.1:{self.test_port}/health"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data.get("status"), "degraded")
                self.assertEqual(data["scheduler"]["last_run"]["status"], "failed")
                self.assertEqual(data["scheduler"]["last_run"]["error"], "database connection timeout")
        finally:
            with server._state_lock:
                server.pipeline_state["scheduler"]["last_run"]["status"] = orig_status
                server.pipeline_state["scheduler"]["last_run"]["error"] = orig_error

    def test_scheduler_stopped_reports_degraded_status(self):
        with server._state_lock:
            orig_status = server.pipeline_state["scheduler"]["status"]
            server.pipeline_state["scheduler"]["status"] = "stopped"

        try:
            url = f"http://127.0.0.1:{self.test_port}/health"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data.get("status"), "degraded")
        finally:
            with server._state_lock:
                server.pipeline_state["scheduler"]["status"] = orig_status


if __name__ == "__main__":
    unittest.main()
