"""
Unified Web Server & Scheduler Entrypoint.

Fully compliant with DOCKER_DEPLOYMENT_STANDARDS-V1.0.0:
- Binds to 0.0.0.0:${PORT:-10000}
- Exposes GET /health responding with HTTP 200 and structured JSON status
- Emits structured logs to stdout/stderr
- Runs the pipeline scheduler periodically in a controlled background thread
- Handles SIGTERM and SIGINT for graceful container shutdown
"""

import json
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import urlparse

import logs.logger as logger

try:
    import main
except Exception as exc:
    main = None
    logger.log_event(
        level="WARNING",
        event="main_import_deferred",
        component="server",
        error=str(exc),
    )


# ==============================================================================
# Configuration & Global State
# ==============================================================================

try:
    PORT = int(os.environ.get("PORT", "10000"))
except (ValueError, TypeError):
    PORT = 10000

HOST = "0.0.0.0"

try:
    INTERVAL_SECONDS = float(os.environ.get("PIPELINE_INTERVAL_SECONDS", "60"))
except (ValueError, TypeError):
    INTERVAL_SECONDS = 60.0

pipeline_state: Dict[str, Any] = {
    "status": "healthy",
    "service": "currency-pipeline",
    "boot_time": datetime.now(timezone.utc).isoformat(),
    "start_timestamp": time.time(),
    "database": {
        "configured": False,
    },
    "scheduler": {
        "status": "starting",
        "interval_seconds": INTERVAL_SECONDS,
        "iteration": 0,
        "is_running_pipeline": False,
        "last_run": {
            "started_at": None,
            "completed_at": None,
            "duration_seconds": None,
            "snapshot_id": None,
            "status": None,
            "published_rates": 0,
            "error": None,
        },
    },
}

_state_lock = threading.Lock()


def is_health_route(raw_path: str) -> bool:
    """
    Check if a raw request path matches health check endpoints (/ or /health).
    Safely ignores query parameters, fragments, and trailing slashes.
    """
    clean_path = urlparse(raw_path).path
    return clean_path.startswith("/") and clean_path.rstrip("/") in ("", "/health")


def get_telemetry_payload() -> Dict[str, Any]:
    """
    Construct structured health telemetry payload without introducing database queries.
    Marks status as degraded if DATABASE_URL is not configured, or if the scheduler
    is stopped/failed, or if the most recent pipeline execution encountered an error.
    """
    with _state_lock:
        uptime = round(time.time() - pipeline_state["start_timestamp"], 1)
        db_configured = bool(os.getenv("DATABASE_URL"))
        pipeline_state["database"]["configured"] = db_configured

        scheduler_status = pipeline_state["scheduler"]["status"]
        last_run_status = pipeline_state["scheduler"]["last_run"].get("status")
        last_run_error = pipeline_state["scheduler"]["last_run"].get("error")

        if not db_configured:
            overall_status = "degraded"
        elif scheduler_status in ("stopped", "failed"):
            overall_status = "degraded"
        elif last_run_status == "failed" or last_run_error is not None:
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        pipeline_state["status"] = overall_status

        return {
            "status": overall_status,
            "service": pipeline_state["service"],
            "uptime_seconds": uptime,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database": pipeline_state["database"],
            "scheduler": pipeline_state["scheduler"],
        }


# ==============================================================================
# HTTP Health Check Handler
# ==============================================================================

class HealthRequestHandler(BaseHTTPRequestHandler):
    """
    Lightweight HTTP Request Handler providing GET /health endpoint.
    Designed with zero external dependencies to minimize container footprint.
    """

    def do_GET(self):
        if is_health_route(self.path):
            payload = get_telemetry_payload()
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(body)

        else:
            err_body = json.dumps({"error": "Not Found", "path": self.path}).encode("utf-8")
            self.send_response(404)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(err_body)))
            self.end_headers()
            self.wfile.write(err_body)

    def do_HEAD(self):
        """Handle HTTP HEAD probes gracefully without returning a response body."""
        if is_health_route(self.path):
            payload = get_telemetry_payload()
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()

        else:
            err_body = json.dumps({"error": "Not Found", "path": self.path}).encode("utf-8")
            self.send_response(404)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(err_body)))
            self.end_headers()

    def log_message(self, format, *args):
        """
        Suppress noisy per-request access logs for periodic health probes,
        or log them through the standard logger if desired.
        """
        # Render and container orchestrators ping /health frequently;
        # suppressing default stderr access lines keeps container logs clean.
        pass


# ==============================================================================
# Pipeline Scheduler Worker Thread
# ==============================================================================

def scheduler_worker(interval_seconds: float, stop_event: threading.Event):
    """
    Background worker periodically running main.run_pipeline().
    Tracks status, iteration count, and execution duration.
    """
    logger.log_event(
        level="INFO",
        event="scheduler_started",
        component="scheduler",
        interval_seconds=interval_seconds,
    )

    with _state_lock:
        pipeline_state["scheduler"]["status"] = "running"
        pipeline_state["scheduler"]["interval_seconds"] = interval_seconds

    iteration = 1

    try:
        while not stop_event.is_set():
            start_time = time.monotonic()
            started_at = datetime.now(timezone.utc).isoformat()

            with _state_lock:
                pipeline_state["scheduler"]["iteration"] = iteration
                pipeline_state["scheduler"]["is_running_pipeline"] = True
                pipeline_state["scheduler"]["last_run"]["started_at"] = started_at
                pipeline_state["scheduler"]["last_run"]["error"] = None

            logger.log_event(
                level="INFO",
                event="pipeline_iteration_started",
                component="scheduler",
                iteration=iteration,
            )

            try:
                active_main = main
                if active_main is None:
                    try:
                        import main as imported_main
                        active_main = imported_main
                    except Exception as import_err:
                        raise RuntimeError(f"Pipeline entrypoint 'main' unavailable: {import_err}") from import_err

                result = active_main.run_pipeline()
                elapsed = time.monotonic() - start_time
                completed_at = datetime.now(timezone.utc).isoformat()

                with _state_lock:
                    pipeline_state["scheduler"]["is_running_pipeline"] = False
                    pipeline_state["scheduler"]["last_run"]["completed_at"] = completed_at
                    pipeline_state["scheduler"]["last_run"]["duration_seconds"] = round(elapsed, 2)

                    if result:
                        pipeline_state["scheduler"]["last_run"]["status"] = result.get("status", "complete")
                        pipeline_state["scheduler"]["last_run"]["snapshot_id"] = result.get("snapshot_id")
                        pipeline_state["scheduler"]["last_run"]["published_rates"] = result.get("published_rates", 0)
                    else:
                        pipeline_state["scheduler"]["last_run"]["status"] = "skipped"

                logger.log_event(
                    level="INFO",
                    event="pipeline_iteration_completed",
                    component="scheduler",
                    iteration=iteration,
                    duration_seconds=round(elapsed, 2),
                    status=result.get("status") if result else "skipped",
                )

            except Exception as exc:
                elapsed = time.monotonic() - start_time
                completed_at = datetime.now(timezone.utc).isoformat()

                with _state_lock:
                    pipeline_state["scheduler"]["is_running_pipeline"] = False
                    pipeline_state["scheduler"]["last_run"]["completed_at"] = completed_at
                    pipeline_state["scheduler"]["last_run"]["duration_seconds"] = round(elapsed, 2)
                    pipeline_state["scheduler"]["last_run"]["status"] = "failed"
                    pipeline_state["scheduler"]["last_run"]["error"] = str(exc)

                logger.log_event(
                    level="ERROR",
                    event="pipeline_iteration_failed",
                    component="scheduler",
                    iteration=iteration,
                    duration_seconds=round(elapsed, 2),
                    error=str(exc),
                )

            # Sleep for remaining interval duration, responding to stop_event promptly
            sleep_needed = max(0.0, interval_seconds - elapsed)
            if sleep_needed > 0:
                stop_event.wait(timeout=sleep_needed)

            iteration += 1

    except Exception as fatal_exc:
        with _state_lock:
            pipeline_state["scheduler"]["status"] = "failed"
            pipeline_state["scheduler"]["is_running_pipeline"] = False
            pipeline_state["scheduler"]["last_run"]["error"] = str(fatal_exc)
        logger.log_event(
            level="CRITICAL",
            event="scheduler_fatal_crash",
            component="scheduler",
            error=str(fatal_exc),
        )
    finally:
        with _state_lock:
            if pipeline_state["scheduler"]["status"] != "failed":
                pipeline_state["scheduler"]["status"] = "stopped"
            pipeline_state["scheduler"]["is_running_pipeline"] = False

        logger.log_event(
            level="INFO",
            event="scheduler_stopped",
            component="scheduler",
        )


# ==============================================================================
# Main Server Runner
# ==============================================================================

def run_server():
    """
    Initialize HTTP server and start scheduler background thread.
    """
    logger.start_run()
    logger.log_event(
        level="INFO",
        event="server_boot",
        component="server",
        host=HOST,
        port=PORT,
        interval_seconds=INTERVAL_SECONDS,
    )

    # Initialize ThreadingHTTPServer bound to 0.0.0.0:PORT
    httpd = ThreadingHTTPServer((HOST, PORT), HealthRequestHandler)

    stop_event = threading.Event()
    worker_thread = threading.Thread(
        target=scheduler_worker,
        args=(INTERVAL_SECONDS, stop_event),
        name="CurrencySchedulerWorker",
        daemon=True,
    )

    def handle_shutdown(signum, frame):
        sig_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"
        logger.log_event(
            level="INFO",
            event="shutdown_signal_received",
            component="server",
            signal=sig_name,
        )
        stop_event.set()
        # Shutdown server in a thread to unblock serve_forever
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    # Register OS termination signals
    try:
        signal.signal(signal.SIGINT, handle_shutdown)
        signal.signal(signal.SIGTERM, handle_shutdown)
    except (ValueError, AttributeError):
        pass

    worker_thread.start()

    logger.log_event(
        level="INFO",
        event="server_listening",
        component="server",
        url=f"http://{HOST}:{PORT}/health",
    )

    try:
        httpd.serve_forever()
    except Exception as exc:
        logger.log_event(
            level="ERROR",
            event="server_crashed",
            component="server",
            error=str(exc),
        )
    finally:
        stop_event.set()
        worker_thread.join(timeout=3)
        httpd.server_close()
        logger.log_event(
            level="INFO",
            event="server_shutdown_complete",
            component="server",
        )


if __name__ == "__main__":
    run_server()
