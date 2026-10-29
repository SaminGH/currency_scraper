"""
Unit tests for structured event logger and log_config.

Covers:
- JSON file destination
- Database destination (with mock)
- Both destinations simultaneously
- Fallback to file when DB fails (enabled vs disabled)
- Multiprocessing safety and PID boundary handling
- Backward compatibility with legacy logger API
- Strict failure isolation (never crashes the caller)
"""

import json
import multiprocessing
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

# Ensure currency_scraper root is on sys.path
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_CURRENT_DIR, ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import logs.log_config as log_config
import logs.logger as logger


def _mp_test_worker(worker_id, test_dir, file_name):
    # Configure worker logging in spawned child process
    log_config.configure(destination="json", log_dir=test_dir, file_name=file_name)
    logger.set_run_id(f"worker-run-{worker_id}")
    logger.set_snapshot_id(worker_id)
    logger.log_event("INFO", f"worker_{worker_id}_done", "worker", worker_num=worker_id)


class TestLogger(unittest.TestCase):

    def setUp(self):
        # Create a clean temporary directory for test log files
        self.test_dir = tempfile.mkdtemp(prefix="test_logger_")
        self.test_log_file = "test_pipeline.jsonl"

        # Reset logger state and close any cached DB connections
        logger.close_db_logging_connection()
        logger.set_run_id(None)
        logger.set_snapshot_id(None)
        logger._verified_tables.clear()

        # Configure logger to write to test_dir
        log_config.configure(
            destination="json",
            log_dir=self.test_dir,
            file_name=self.test_log_file,
            table_name="public.pipeline_logs",
            fallback=True,
            database_url="postgresql://user:pass@localhost:5432/testdb",
        )

    def tearDown(self):
        # Clean up database connection and temporary directory
        logger.close_db_logging_connection()
        log_config.reset_to_defaults()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def _read_json_logs(self):
        log_path = os.path.join(self.test_dir, self.test_log_file)
        if not os.path.exists(log_path):
            return []
        entries = []
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    # ============================================================
    # 1. Backward Compatibility Tests
    # ============================================================

    def test_start_run_and_get_run_id(self):
        """Verify start_run creates a valid timestamped run_id and clears snapshot_id."""
        logger.set_snapshot_id(999)
        run_id = logger.start_run()
        self.assertIsNotNone(run_id)
        self.assertEqual(logger.get_run_id(), run_id)
        self.assertIsNone(logger.get_snapshot_id())
        self.assertRegex(run_id, r"^\d{8}-\d{6}-[0-9a-f]{4}$")

    def test_set_and_get_snapshot_id(self):
        """Verify set_snapshot_id and get_snapshot_id work as expected."""
        logger.set_snapshot_id(42)
        self.assertEqual(logger.get_snapshot_id(), 42)

    def test_set_run_id(self):
        """Verify set_run_id correctly overrides the run_id."""
        logger.set_run_id("custom-run-123")
        self.assertEqual(logger.get_run_id(), "custom-run-123")

    def test_log_event_dict_unpacking(self):
        """Verify log_event accepts unpacked dictionaries like **log_kwargs."""
        log_kwargs = {
            "level": "INFO",
            "event": "confidence_scored",
            "component": "confidence",
            "currency": "USD",
            "rating": "HIGH",
        }
        logger.log_event(**log_kwargs)

        logs = self._read_json_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["level"], "INFO")
        self.assertEqual(logs[0]["event"], "confidence_scored")
        self.assertEqual(logs[0]["component"], "confidence")
        self.assertEqual(logs[0]["currency"], "USD")
        self.assertEqual(logs[0]["rating"], "HIGH")

    def test_module_level_constants_backward_compatibility(self):
        """Verify logger.LOG_DIR and logger.LOG_FILE are exposed."""
        self.assertTrue(hasattr(logger, "LOG_DIR"))
        self.assertTrue(hasattr(logger, "LOG_FILE"))

    # ============================================================
    # 2. JSON File Destination
    # ============================================================

    def test_json_destination_writes_to_file_only(self):
        """When LOG_DESTINATION='json', events are written only to file."""
        log_config.configure(destination="json")
        logger.start_run()
        run_id = logger.get_run_id()
        logger.set_snapshot_id(101)

        with patch.object(logger, "_log_to_db") as mock_db:
            logger.log_event("INFO", "test_event", "test_comp", detail="json_only")
            mock_db.assert_not_called()

        logs = self._read_json_logs()
        self.assertEqual(len(logs), 1)
        entry = logs[0]
        self.assertEqual(entry["run_id"], run_id)
        self.assertEqual(entry["snapshot_id"], 101)
        self.assertEqual(entry["level"], "INFO")
        self.assertEqual(entry["event"], "test_event")
        self.assertEqual(entry["component"], "test_comp")
        self.assertEqual(entry["detail"], "json_only")
        self.assertIn("timestamp", entry)

    # ============================================================
    # 3. Database Destination (Mocked)
    # ============================================================

    def test_db_destination_writes_to_database_only(self):
        """When LOG_DESTINATION='db', events are inserted into DB and not file."""
        log_config.configure(destination="db")
        logger.set_run_id("run-db-1")
        logger.set_snapshot_id(202)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.closed = 0

        with patch.object(logger, "_get_db_connection", return_value=mock_conn):
            logger.log_event("WARNING", "rate_spike", "validator", currency="EUR", diff=1.5)

        # File must not be written when DB succeeds
        logs = self._read_json_logs()
        self.assertEqual(len(logs), 0)

        # Cursor execute must have been called
        self.assertTrue(mock_cursor.execute.called)
        # Check the insert call
        calls = [c for c in mock_cursor.execute.call_args_list if "INSERT INTO" in str(c[0][0])]
        self.assertEqual(len(calls), 1)
        query, params = calls[0][0]

        self.assertIn("INSERT INTO public.pipeline_logs", query)
        self.assertIn("%s::jsonb", query)

        timestamp, run_id, snap_id, level, event, component, extra_data = params
        self.assertEqual(run_id, "run-db-1")
        self.assertEqual(snap_id, 202)
        self.assertEqual(level, "WARNING")
        self.assertEqual(event, "rate_spike")
        self.assertEqual(component, "validator")

        extra_parsed = json.loads(extra_data)
        self.assertEqual(extra_parsed, {"currency": "EUR", "diff": 1.5})

    def test_db_destination_idempotent_table_creation(self):
        """Verify CREATE TABLE IF NOT EXISTS is invoked on first DB write."""
        log_config.configure(destination="db")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.closed = 0

        with patch.object(logger, "_get_db_connection", return_value=mock_conn):
            logger.log_event("INFO", "init_event", "system")

        # Verify CREATE TABLE was called
        create_table_calls = [
            c for c in mock_cursor.execute.call_args_list if "CREATE TABLE IF NOT EXISTS" in str(c[0][0])
        ]
        self.assertEqual(len(create_table_calls), 1)
        self.assertIn("public.pipeline_logs", str(create_table_calls[0][0][0]))

    # ============================================================
    # 4. Both Destinations
    # ============================================================

    def test_both_destinations_write_simultaneously(self):
        """When LOG_DESTINATION='both', events go to both file and DB."""
        log_config.configure(destination="both")
        logger.set_run_id("run-both-1")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.closed = 0

        with patch.object(logger, "_get_db_connection", return_value=mock_conn):
            logger.log_event("INFO", "dual_write", "main", note="written_everywhere")

        # Check JSON file
        logs = self._read_json_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["event"], "dual_write")
        self.assertEqual(logs[0]["note"], "written_everywhere")

        # Check DB execution
        self.assertTrue(mock_cursor.execute.called)
        calls = [c for c in mock_cursor.execute.call_args_list if "INSERT INTO" in str(c[0][0])]
        self.assertEqual(len(calls), 1)

    # ============================================================
    # 5. Fallback to File when DB Fails
    # ============================================================

    def test_fallback_to_file_when_db_connection_fails(self):
        """When DB fails and fallback is True, event is saved to file."""
        log_config.configure(destination="db", fallback=True)
        logger.set_run_id("run-fallback-1")

        # Simulate DB connection failing
        with patch.object(logger, "_get_db_connection", return_value=None):
            logger.log_event("ERROR", "db_offline", "database", reason="timeout")

        # Event should be safely written to file
        logs = self._read_json_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["event"], "db_offline")
        self.assertEqual(logs[0]["reason"], "timeout")

    def test_no_fallback_to_file_when_fallback_disabled(self):
        """When DB fails and fallback is False, event is NOT saved to file."""
        log_config.configure(destination="db", fallback=False)

        with patch.object(logger, "_get_db_connection", return_value=None):
            logger.log_event("ERROR", "db_offline_no_fallback", "database")

        logs = self._read_json_logs()
        self.assertEqual(len(logs), 0)

    def test_fallback_to_file_when_insert_query_raises_exception(self):
        """When DB insert query raises an exception, fallback to file is triggered."""
        log_config.configure(destination="db", fallback=True)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("Postgres connection dropped")
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.closed = 0

        with patch.object(logger, "_get_db_connection", return_value=mock_conn):
            logger.log_event("ERROR", "query_failed", "database", code=500)

        logs = self._read_json_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["event"], "query_failed")
        self.assertEqual(logs[0]["code"], 500)

    # ============================================================
    # 6. Failure Isolation and Edge Cases
    # ============================================================

    def test_logger_never_crashes_on_file_write_error(self):
        """Even if file system raises an OSError, log_event does not crash."""
        log_config.configure(destination="json")

        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            # Must not raise an exception
            logger.log_event("INFO", "fs_error", "test")

    def test_non_serializable_kwargs(self):
        """Non-JSON-serializable objects (datetime, custom objects) are handled safely."""
        log_config.configure(destination="json")

        class UnserializableClass:
            def __repr__(self):
                return "<UnserializableClassInstance>"

        logger.log_event(
            "INFO",
            "complex_data",
            "test",
            obj=UnserializableClass(),
            timestamp_obj=datetime(2026, 10, 29, 12, 0, 0),
        )

        logs = self._read_json_logs()
        self.assertEqual(len(logs), 1)
        self.assertIn("<UnserializableClassInstance>", logs[0]["obj"])
        self.assertIn("2026-10-29", logs[0]["timestamp_obj"])

    def test_recursion_guard(self):
        """Recursive calls to log_event inside log_event do not cause infinite recursion."""
        log_config.configure(destination="json")

        original_log_to_file = logger._log_to_file

        def recursive_hook(log_data):
            # Attempt re-entrant call
            logger.log_event("DEBUG", "nested_event", "recursion_test")
            return original_log_to_file(log_data)

        with patch.object(logger, "_log_to_file", side_effect=recursive_hook):
            # Must complete without RecursionError
            logger.log_event("INFO", "outer_event", "recursion_test")

    # ============================================================
    # 7. Multiprocessing Safety
    # ============================================================

    def test_pid_change_discards_parent_connection(self):
        """When PID changes (worker process spawned), parent DB connection is discarded."""
        mock_parent_conn = MagicMock()
        mock_parent_conn.closed = 0
        logger._db_connection = mock_parent_conn
        logger._db_pid = 11111  # Simulate parent PID

        # In current process (PID != 11111), _get_db_connection should drop parent conn
        with patch("os.getpid", return_value=22222):
            with patch("logs.logger.psycopg2", None):
                conn = logger._get_db_connection()
                self.assertIsNone(conn)
                self.assertIsNone(logger._db_connection)
                # Ensure parent socket close was NOT called directly from child
                mock_parent_conn.close.assert_not_called()

    def test_multiprocessing_worker_logging(self):
        """Real multiprocessing.Process logging events does not deadlock or crash."""
        log_config.configure(destination="json", log_dir=self.test_dir, file_name=self.test_log_file)

        processes = []
        for i in range(3):
            p = multiprocessing.Process(
                target=_mp_test_worker,
                args=(i, self.test_dir, self.test_log_file),
            )
            processes.append(p)
            p.start()

        for p in processes:
            p.join(timeout=10)
            self.assertFalse(p.is_alive())

        logs = self._read_json_logs()
        self.assertEqual(len(logs), 3)
        events = {l["event"] for l in logs}
        self.assertEqual(events, {"worker_0_done", "worker_1_done", "worker_2_done"})


    # ============================================================
    # 8. Advanced Edge Cases & Log Config Tests
    # ============================================================

    def test_direct_log_file_assignment_override(self):
        """Verify directly assigning to logger.LOG_FILE overrides the path."""
        custom_file = os.path.join(self.test_dir, "custom_direct.jsonl")
        logger.LOG_FILE = custom_file
        try:
            logger.log_event("INFO", "direct_override_test", "test")
            self.assertTrue(os.path.exists(custom_file))
            with open(custom_file, "r", encoding="utf-8") as f:
                content = json.loads(f.readline())
                self.assertEqual(content["event"], "direct_override_test")
        finally:
            # Clean up the module attribute
            if "LOG_FILE" in logger.__dict__:
                del logger.__dict__["LOG_FILE"]

    def test_db_reconnect_retry_on_dropped_connection(self):
        """Verify DB write retries once if connection dropped on first execute."""
        log_config.configure(destination="db")

        mock_conn1 = MagicMock()
        mock_cursor1 = MagicMock()
        mock_cursor1.execute.side_effect = Exception("connection reset by peer")
        mock_conn1.cursor.return_value.__enter__.return_value = mock_cursor1
        mock_conn1.closed = 0

        mock_conn2 = MagicMock()
        mock_cursor2 = MagicMock()
        mock_conn2.cursor.return_value.__enter__.return_value = mock_cursor2
        mock_conn2.closed = 0

        with patch.object(logger, "_get_db_connection", side_effect=[mock_conn1, mock_conn2]):
            logger.log_event("INFO", "reconnect_test", "database")

        # Second connection should have executed the insert
        self.assertTrue(mock_cursor2.execute.called)
        calls = [c for c in mock_cursor2.execute.call_args_list if "INSERT INTO" in str(c[0][0])]
        self.assertEqual(len(calls), 1)

    def test_ensure_table_exists_failure_does_not_abort_logging(self):
        """Verify CREATE TABLE exception does not crash logger and insert is still attempted."""
        log_config.configure(destination="db")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        def execute_side_effect(sql, *args):
            if "CREATE TABLE" in sql:
                raise Exception("insufficient privileges for CREATE TABLE")
            return None

        mock_cursor.execute.side_effect = execute_side_effect
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.closed = 0

        with patch.object(logger, "_get_db_connection", return_value=mock_conn):
            logger.log_event("INFO", "table_check_fail_test", "database")

        # The INSERT should still have been attempted
        calls = [c for c in mock_cursor.execute.call_args_list if "INSERT INTO" in str(c[0][0])]
        self.assertEqual(len(calls), 1)

    def test_log_event_run_id_and_snapshot_id_overrides(self):
        """Verify passing run_id and snapshot_id in kwargs overrides ambient IDs."""
        log_config.configure(destination="both")
        logger.set_run_id("ambient-run")
        logger.set_snapshot_id(100)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.closed = 0

        with patch.object(logger, "_get_db_connection", return_value=mock_conn):
            logger.log_event(
                "INFO",
                "override_test",
                "test",
                run_id="explicit-run-999",
                snapshot_id="777",
                custom_attr="hello",
            )

        # Check JSON log
        logs = self._read_json_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["run_id"], "explicit-run-999")
        self.assertEqual(logs[0]["snapshot_id"], "777")
        self.assertEqual(logs[0]["custom_attr"], "hello")

        # Check DB params
        calls = [c for c in mock_cursor.execute.call_args_list if "INSERT INTO" in str(c[0][0])]
        self.assertEqual(len(calls), 1)
        params = calls[0][0][1]
        self.assertEqual(params[1], "explicit-run-999")
        self.assertEqual(params[2], 777)  # converted to int
        self.assertEqual(json.loads(params[6]), {"custom_attr": "hello"})

    def test_empty_kwargs_produces_empty_extra_data(self):
        """Verify extra_data in DB is '{}' when no kwargs are passed."""
        log_config.configure(destination="db")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.closed = 0

        with patch.object(logger, "_get_db_connection", return_value=mock_conn):
            logger.log_event("INFO", "simple_event", "main")

        calls = [c for c in mock_cursor.execute.call_args_list if "INSERT INTO" in str(c[0][0])]
        self.assertEqual(len(calls), 1)
        params = calls[0][0][1]
        self.assertEqual(params[6], "{}")

    def test_unknown_destination_falls_back_to_file(self):
        """Verify unexpected LOG_DESTINATION defaults safely to file writing."""
        log_config.configure(destination="unrecognized_destination_value")

        logger.log_event("INFO", "fallback_unknown_dest", "main")

        logs = self._read_json_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["event"], "fallback_unknown_dest")

    def test_log_config_env_overrides(self):
        """Verify log_config correctly parses environment variables on reset_to_defaults."""
        env_vars = {
            "LOG_DESTINATION": "db",
            "LOG_DIR": "/tmp/custom_env_logs",
            "LOG_FILE_NAME": "custom_env.jsonl",
            "LOG_TABLE_NAME": "custom.logs_table",
            "FALLBACK_TO_FILE_ON_DB_ERROR": "false",
            "DATABASE_URL": "postgresql://envuser:envpass@localhost:5432/envdb",
        }
        with patch.dict(os.environ, env_vars):
            log_config.reset_to_defaults()
            self.assertEqual(log_config.LOG_DESTINATION, "db")
            self.assertEqual(log_config.LOG_DIR, "/tmp/custom_env_logs")
            self.assertEqual(log_config.LOG_FILE_NAME, "custom_env.jsonl")
            self.assertEqual(log_config.LOG_TABLE_NAME, "custom.logs_table")
            self.assertFalse(log_config.FALLBACK_TO_FILE_ON_DB_ERROR)
            self.assertEqual(log_config.DATABASE_URL, "postgresql://envuser:envpass@localhost:5432/envdb")


    def test_circuit_breaker_cooldown_prevents_reconnect_loop(self):
        """Verify failed DB connection triggers cooldown and avoids blocking on subsequent calls."""
        log_config.configure(destination="db", fallback=True, reconnect_interval=10)

        mock_connect = MagicMock(side_effect=Exception("Database unreachable"))

        with patch("logs.logger.psycopg2") as mock_psycopg2:
            mock_psycopg2.connect = mock_connect

            current_time = 1000.0
            with patch("time.monotonic", side_effect=lambda: current_time):
                # 1st call: attempts connect and fails, sets cooldown
                logger.log_event("INFO", "fail_evt_1", "main")
                self.assertEqual(mock_connect.call_count, 1)

                # 2nd call: within 10s cooldown -> immediately returns None, does NOT call connect
                current_time = 1005.0
                logger.log_event("INFO", "fail_evt_2", "main")
                self.assertEqual(mock_connect.call_count, 1)

                # 3rd call: after cooldown (11 seconds elapsed) -> attempts reconnect
                current_time = 1011.0
                logger.log_event("INFO", "fail_evt_3", "main")
                self.assertEqual(mock_connect.call_count, 2)

        # All 3 events should have safely fallen back to file
        logs = self._read_json_logs()
        self.assertEqual(len(logs), 3)

    def test_direct_log_dir_assignment_override(self):
        """Verify directly assigning logger.LOG_DIR is respected by file logging."""
        custom_dir = os.path.join(self.test_dir, "custom_dir")
        os.makedirs(custom_dir, exist_ok=True)
        logger.LOG_DIR = custom_dir

        try:
            logger.log_event("INFO", "dir_override_event", "main")
            expected_file = os.path.join(custom_dir, "test_pipeline.jsonl")
            self.assertTrue(os.path.exists(expected_file))
            with open(expected_file, "r", encoding="utf-8") as f:
                content = json.loads(f.readline())
                self.assertEqual(content["event"], "dir_override_event")
        finally:
            if "LOG_DIR" in logger.__dict__:
                del logger.__dict__["LOG_DIR"]

    def test_database_url_change_triggers_reconnect(self):
        """Verify changing DATABASE_URL closes old connection and connects to new URL."""
        log_config.configure(destination="db", database_url="postgresql://user:pass@host1:5432/db1")

        mock_conn1 = MagicMock()
        mock_conn1.closed = 0
        mock_conn2 = MagicMock()
        mock_conn2.closed = 0

        with patch("logs.logger.psycopg2") as mock_psycopg2:
            mock_psycopg2.connect.side_effect = [mock_conn1, mock_conn2]

            # Connect with URL 1
            conn1 = logger._get_db_connection()
            self.assertEqual(conn1, mock_conn1)
            self.assertEqual(mock_psycopg2.connect.call_args[0][0], "postgresql://user:pass@host1:5432/db1")

            # Change to URL 2
            log_config.configure(database_url="postgresql://user:pass@host2:5432/db2")

            conn2 = logger._get_db_connection()
            self.assertEqual(conn2, mock_conn2)
            self.assertEqual(mock_psycopg2.connect.call_args[0][0], "postgresql://user:pass@host2:5432/db2")
            # Old connection should have been closed
            mock_conn1.close.assert_called_once()

    def test_whitespace_database_url_treated_as_unset(self):
        """Verify whitespace or empty DATABASE_URL is treated as unset and falls back cleanly."""
        log_config.configure(destination="db", database_url="   ", fallback=True)

        with patch("logs.logger.psycopg2") as mock_psycopg2:
            logger.log_event("INFO", "whitespace_url_event", "main")
            mock_psycopg2.connect.assert_not_called()

        logs = self._read_json_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["event"], "whitespace_url_event")

    def test_destination_aliases(self):
        """Verify destination aliases ('database', 'postgres', 'file', 'all') route correctly."""
        # 1. 'database' -> DB only
        log_config.configure(destination="database")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.closed = 0

        with patch.object(logger, "_get_db_connection", return_value=mock_conn):
            logger.log_event("INFO", "alias_db_event", "main")
        self.assertTrue(mock_cursor.execute.called)
        self.assertEqual(len(self._read_json_logs()), 0)

        # 2. 'file' -> JSON only
        log_config.configure(destination="file")
        with patch.object(logger, "_log_to_db") as mock_db:
            logger.log_event("INFO", "alias_file_event", "main")
            mock_db.assert_not_called()
        self.assertEqual(len(self._read_json_logs()), 1)

    def test_ensure_table_exists_rollback_on_error(self):
        """Verify conn.rollback is called if CREATE TABLE fails, keeping connection usable."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("insufficient privilege")
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        logger._ensure_table_exists(mock_conn, "public.pipeline_logs")
        mock_conn.rollback.assert_called_once()
        self.assertIn("public.pipeline_logs", logger._verified_tables)

    def test_orphaned_parent_conns_retained_on_pid_change(self):
        """Verify child process retains parent connection ref to prevent PQfinish destruction."""
        mock_parent_conn = MagicMock()
        mock_parent_conn.closed = 0
        logger._db_connection = mock_parent_conn
        logger._db_pid = 11111

        with patch("os.getpid", return_value=22222):
            with patch("logs.logger.psycopg2", None):
                conn = logger._get_db_connection()
                self.assertIsNone(conn)
                self.assertIn(mock_parent_conn, logger._orphaned_parent_conns)
                mock_parent_conn.close.assert_not_called()

    def test_safe_table_name_validation(self):
        """Verify invalid table name with injection attempts is rejected safely."""
        log_config.configure(destination="db", table_name="public.logs; DROP TABLE users;--", fallback=True)

        mock_conn = MagicMock()
        with patch.object(logger, "_get_db_connection", return_value=mock_conn):
            logger.log_event("INFO", "injection_test", "main")

        # Database insert must not be executed on invalid table name
        mock_conn.cursor.assert_not_called()
        # Fallback to file succeeds
        logs = self._read_json_logs()
        self.assertEqual(len(logs), 1)

    def test_none_level_event_component_defaults(self):
        """Verify None level, event, or component are sanitized to valid defaults."""
        log_config.configure(destination="both")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.closed = 0

        with patch.object(logger, "_get_db_connection", return_value=mock_conn):
            logger.log_event(level=None, event=None, component=None)

        logs = self._read_json_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["level"], "INFO")
        self.assertEqual(logs[0]["event"], "unknown")
        self.assertEqual(logs[0]["component"], "unknown")

        calls = [c for c in mock_cursor.execute.call_args_list if "INSERT INTO" in str(c[0][0])]
        self.assertEqual(len(calls), 1)
        params = calls[0][0][1]
        self.assertEqual(params[3], "INFO")
        self.assertEqual(params[4], "unknown")
        self.assertEqual(params[5], "unknown")


if __name__ == "__main__":
    unittest.main()

