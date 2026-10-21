import json
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
import urllib.request
import urllib.error

import server


class TestServerHealthEndpoint(unittest.TestCase):
    """
    Test suite verifying HTTP health check and server response telemetry
    as mandated by DOCKER_DEPLOYMENT_STANDARDS-V1.0.0.
    """

    @classmethod
    def setUpClass(cls):
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
            self.assertIn("scheduler", data)

    def test_root_endpoint_returns_200(self):
        url = f"http://127.0.0.1:{self.test_port}/"
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


if __name__ == "__main__":
    unittest.main()
