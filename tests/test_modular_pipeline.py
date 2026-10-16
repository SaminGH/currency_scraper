import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import ANY, MagicMock, patch

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import confidence
import database.snapshot as snapshot_module
import main
import price_aggregator
import scraper_output
import validator


class TestModularPipeline(unittest.TestCase):

    def test_clean_imports_no_side_effects(self):
        """Verify that importing modules produces no side-effects."""
        self.assertTrue(callable(confidence.calculate_confidence))
        self.assertTrue(callable(scraper_output.get_scraper_output))
        self.assertTrue(callable(validator.validate_prices))
        self.assertTrue(callable(price_aggregator.aggregate_prices))
        self.assertTrue(callable(main.run_pipeline))
        self.assertTrue(callable(main.main))

    def test_scraper_output_assembly(self):
        """Test get_scraper_output with mock scraper manager results."""
        mock_results = {
            "source_a": {
                "status": "complete",
                "prices": {
                    "USD": {"price": 100000.0},
                    "EUR": {"price": 110000.0},
                },
                "errors": {}
            },
            "source_b": {
                "status": "complete",
                "prices": {
                    "USD": {"price": 100500.0},
                    "EUR": {"price": 110500.0},
                },
                "errors": {}
            },
            "source_c": {
                "status": "partial",
                "prices": {
                    "USD": {"price": 100200.0},
                },
                "errors": {"EUR": "fetch_failed"}
            },
            "source_failing": {
                "status": "failed",
                "prices": "invalid_not_a_dict",
                "errors": {}
            }
        }

        raw_prices, source_status = scraper_output.get_scraper_output(mock_results)

        # Check source_status structure
        self.assertIn("source_a", source_status)
        self.assertEqual(source_status["source_a"]["status"], "success")
        self.assertEqual(source_status["source_a"]["currencies_received"], 2)
        self.assertIsNone(source_status["source_a"]["failure_reason"])

        self.assertIn("source_failing", source_status)
        self.assertEqual(source_status["source_failing"]["status"], "failed")
        self.assertEqual(source_status["source_failing"]["failure_reason"], "prices_is_not_dict")

        # Check raw_prices structure
        self.assertIn("USD", raw_prices)
        self.assertIn("EUR", raw_prices)
        self.assertEqual(raw_prices["USD"]["prices"], {
            "source_a": 100000.0,
            "source_b": 100500.0,
            "source_c": 100200.0,
        })
        self.assertEqual(raw_prices["USD"]["source"], "3/4")
        self.assertEqual(raw_prices["EUR"]["prices"], {
            "source_a": 110000.0,
            "source_b": 110500.0,
        })
        self.assertEqual(raw_prices["EUR"]["source"], "2/4")

    def test_scraper_output_edge_cases(self):
        """Test get_scraper_output with edge cases like missing price key or invalid data dict."""
        mock_results = {
            "src_invalid_curr": {
                "status": "complete",
                "prices": {
                    "USD": "not_a_dict",
                    "EUR": {"no_price_key": 123},
                    "GBP": {"price": 120000.0}
                }
            }
        }
        raw_prices, source_status = scraper_output.get_scraper_output(mock_results)
        self.assertIn("src_invalid_curr", source_status)
        self.assertIn("GBP", raw_prices)
        self.assertEqual(raw_prices["GBP"]["prices"], {"src_invalid_curr": 120000.0})
        # USD and EUR should have empty prices dictionary ('0/1')
        self.assertIn("USD", raw_prices)
        self.assertEqual(raw_prices["USD"]["prices"], {})
        self.assertEqual(raw_prices["USD"]["source"], "0/4")
        self.assertIn("EUR", raw_prices)
        self.assertEqual(raw_prices["EUR"]["prices"], {})
        self.assertEqual(raw_prices["EUR"]["source"], "0/4")

    def test_scraper_output_error_fallback(self):
        """Test get_scraper_output fallback on fatal error."""
        with patch("scraper_manager.run_all", side_effect=RuntimeError("Scraper crash")):
            raw_prices, source_status = scraper_output.get_scraper_output()
            self.assertEqual(raw_prices, {})
            self.assertEqual(source_status, {})

    def test_validator_cases(self):
        """Test validate_prices across 0, 1, 2, and 3+ sources with outlier detection."""
        # Test non-dict input
        bad_result = validator.validate_prices("not_a_dict")
        self.assertEqual(bad_result, {})

        # Test empty input
        empty_result = validator.validate_prices({})
        self.assertEqual(empty_result, {})

        test_input = {
            "ZERO": {
                "prices": {},
                "source": "0/3"
            },
            "ONE": {
                "prices": {"source_a": 50000.0},
                "source": "1/3"
            },
            "TWO": {
                "prices": {"source_a": 50000.0, "source_b": 50100.0},
                "source": "2/3"
            },
            "THREE_NORMAL": {
                "prices": {
                    "source_a": 100000.0,
                    "source_b": 100200.0,
                    "source_c": 100100.0,
                },
                "source": "3/3"
            },
            "THREE_OUTLIER": {
                "prices": {
                    "source_a": 100000.0,
                    "source_b": 100200.0,
                    "source_c": 150000.0,  # >1% deviation from median
                },
                "source": "3/3"
            }
        }

        validated = validator.validate_prices(test_input)

        # ZERO
        self.assertEqual(validated["ZERO"]["status"], "not_publishable")
        self.assertEqual(validated["ZERO"]["prices"], {})
        self.assertNotIn("confidence", validated["ZERO"])
        self.assertEqual(validated["ZERO"]["removed_sources"], {})

        # ONE
        self.assertEqual(validated["ONE"]["status"], "not_publishable")
        self.assertNotIn("confidence", validated["ONE"])
        self.assertEqual(validated["ONE"]["removed_sources"], {})

        # TWO
        self.assertEqual(validated["TWO"]["status"], "valid")
        self.assertNotIn("confidence", validated["TWO"])
        self.assertEqual(len(validated["TWO"]["prices"]), 2)
        self.assertEqual(validated["TWO"]["removed_sources"], {})

        # THREE_NORMAL
        self.assertEqual(validated["THREE_NORMAL"]["status"], "valid")
        self.assertNotIn("confidence", validated["THREE_NORMAL"])
        self.assertEqual(len(validated["THREE_NORMAL"]["prices"]), 3)
        self.assertEqual(validated["THREE_NORMAL"]["removed_sources"], {})

        # THREE_OUTLIER
        self.assertEqual(validated["THREE_OUTLIER"]["status"], "outlier_removed")
        self.assertNotIn("confidence", validated["THREE_OUTLIER"])
        self.assertIn("source_c", validated["THREE_OUTLIER"]["removed_sources"])
        self.assertNotIn("source_c", validated["THREE_OUTLIER"]["prices"])
        self.assertIn("source_a", validated["THREE_OUTLIER"]["prices"])
        self.assertIn("source_b", validated["THREE_OUTLIER"]["prices"])

    def test_validator_edge_cases(self):
        """Test validator handling of bad source formats, non-numeric prices, zero median."""
        test_input = {
            "BAD_DATA_FORMAT": "not_a_dict",
            "MISSING_PRICES": {"source": "1/2"},
            "PRICES_NOT_DICT": {"prices": [1, 2, 3], "source": "1/2"},
            "BAD_SOURCE_INFO": {"prices": {"s1": 10.0}, "source": 12345},
            "INVALID_SOURCE_SLASH": {"prices": {"s1": 10.0}, "source": "invalid_no_slash"},
            "NON_NUMERIC_PRICES": {
                "prices": {"s1": "string_price", "s2": 10.0, "s3": 20.0},
                "source": "3/3"
            },
            "ZERO_MEDIAN": {
                "prices": {"s1": 0.0, "s2": 0.0, "s3": 0.0},
                "source": "3/3"
            }
        }
        validated = validator.validate_prices(test_input)
        # All of these invalid currencies should be safely skipped without crashing
        self.assertEqual(len(validated), 0)

    def test_price_aggregator(self):
        """Test aggregate_prices with valid and invalid inputs."""
        # Test non-dict input
        bad_result = price_aggregator.aggregate_prices("not_a_dict")
        self.assertEqual(bad_result, {})

        validated_input = {
            "ONE_SRC": {
                "prices": {"source_a": 100.0},
                "source": "1/3",
                "status": "not_publishable",
                "removed_sources": {}
            },
            "TWO_SRC": {
                "prices": {"source_a": 100.0, "source_b": 100.1},
                "source": "2/3",
                "status": "valid",
                "removed_sources": {}
            }
        }

        aggregated = price_aggregator.aggregate_prices(validated_input)

        # ONE_SRC: < 2 sources -> publishable: False, confidence: LOW
        self.assertIn("ONE_SRC", aggregated)
        self.assertEqual(aggregated["ONE_SRC"]["price"], 100.0)
        self.assertFalse(aggregated["ONE_SRC"]["publishable"])
        self.assertEqual(aggregated["ONE_SRC"]["publishability_reason"], "fewer_than_two_valid_sources")
        self.assertEqual(aggregated["ONE_SRC"]["sources_used"], 1)
        self.assertEqual(aggregated["ONE_SRC"]["confidence"], "LOW")

        # TWO_SRC: >= 2 sources -> publishable: True, confidence: MEDIUM
        self.assertIn("TWO_SRC", aggregated)
        self.assertEqual(aggregated["TWO_SRC"]["price"], 100.05)
        self.assertTrue(aggregated["TWO_SRC"]["publishable"])
        self.assertEqual(aggregated["TWO_SRC"]["publishability_reason"], "at_least_two_valid_sources")
        self.assertEqual(aggregated["TWO_SRC"]["sources_used"], 2)
        self.assertEqual(aggregated["TWO_SRC"]["confidence"], "MEDIUM")

    def test_price_aggregator_edge_cases(self):
        """Test price_aggregator with invalid currencies and malformed entries."""
        validated_input = {
            "NOT_DICT": "hello",
            "EMPTY_PRICES": {"prices": {}, "source": "0/3"},
            "PRICES_NOT_DICT": {"prices": "none", "source": "1/3"},
            "MALFORMED_SOURCE": {
                "prices": {"s1": 50.0, "s2": 52.0},
                "source": "malformed",
                "status": "valid"
            }
        }
        aggregated = price_aggregator.aggregate_prices(validated_input)
        self.assertIn("MALFORMED_SOURCE", aggregated)
        # Should fallback sources_total to len(source_prices) = 2
        self.assertEqual(aggregated["MALFORMED_SOURCE"]["sources_total"], 2)
        self.assertEqual(aggregated["MALFORMED_SOURCE"]["price"], 51.0)
        self.assertTrue(aggregated["MALFORMED_SOURCE"]["publishable"])

    def test_end_to_end_data_flow(self):
        """Test full sequence from get_scraper_output to aggregate_prices."""
        mock_results = {
            "alanchand": {
                "status": "complete",
                "prices": {"USD": {"price": 90000.0}},
            },
            "tgju": {
                "status": "complete",
                "prices": {"USD": {"price": 90200.0}},
            },
            "bonbast": {
                "status": "complete",
                "prices": {"USD": {"price": 90100.0}},
            }
        }

        # Step 1: get_scraper_output
        raw_prices, source_status = scraper_output.get_scraper_output(mock_results)
        self.assertIn("USD", raw_prices)

        # Step 2: validate_prices
        validated_prices = validator.validate_prices(raw_prices)
        self.assertEqual(validated_prices["USD"]["status"], "valid")

        # Step 3: aggregate_prices
        final_prices = price_aggregator.aggregate_prices(validated_prices)
        self.assertIn("USD", final_prices)
        self.assertEqual(final_prices["USD"]["price"], 90100.0)
        self.assertTrue(final_prices["USD"]["publishable"])
        self.assertEqual(final_prices["USD"]["sources_used"], 3)

    @patch("main.database")
    @patch("main.scraper_output.get_scraper_output")
    @patch("main.validator.validate_prices")
    @patch("main.price_aggregator.aggregate_prices")
    @patch("main.change.calculate_change_24h")
    def test_main_run_pipeline_success(
        self,
        mock_calc_change,
        mock_aggregate,
        mock_validate,
        mock_get_scraper,
        mock_database,
    ):
        """Verify main.run_pipeline invokes stages in sequence, separates DB connections, and publishes snapshot."""
        mock_conn = MagicMock()
        mock_database.get_connection.return_value = mock_conn
        mock_database.create_snapshot.return_value = "snap_123"
        mock_database.publish_snapshot.return_value = {
            "snapshot_id": "snap_123",
            "published_rates": 1,
            "status": "published",
        }

        mock_get_scraper.return_value = (
            {"USD": {"prices": {"src_a": 100.0}, "source": "1/1"}},
            {"src_a": {"status": "success", "currencies_received": 1, "failure_reason": None}},
        )
        mock_validate.return_value = {
            "USD": {"prices": {"src_a": 100.0}, "source": "1/1", "status": "valid", "removed_sources": {}}
        }
        mock_aggregate.return_value = {
            "USD": {
                "price": 100.0,
                "confidence": "LOW",
                "publishable": True,
                "sources": ["src_a"],
                "sources_total": 1,
                "sources_used": 1,
                "status": "valid",
            }
        }
        mock_calc_change.return_value = {"USD": {"change_24h": 0.5}}

        res = main.run_pipeline()

        self.assertEqual(res["snapshot_id"], "snap_123")
        mock_get_scraper.assert_called_once()
        mock_validate.assert_called_once()
        mock_aggregate.assert_called_once()
        mock_calc_change.assert_called_once()
        mock_database.publish_snapshot.assert_called_once()
        # Connection acquired once in Phase 1 and once in Phase 3
        self.assertEqual(mock_database.get_connection.call_count, 2)
        # Connection closed after Phase 1 and in finally after Phase 3
        self.assertEqual(mock_database.close_connection.call_count, 2)

    @patch("main.database")
    @patch("main.scraper_output.get_scraper_output")
    def test_main_run_pipeline_failure(self, mock_get_scraper, mock_database):
        """Verify main.run_pipeline calls fail_snapshot with a fresh connection and closes connection on exception."""
        mock_conn = MagicMock()
        mock_database.get_connection.return_value = mock_conn
        mock_database.create_snapshot.return_value = "snap_fail"
        mock_get_scraper.side_effect = RuntimeError("Fatal scraper manager crash")

        with self.assertRaises(RuntimeError):
            main.run_pipeline()

        mock_database.fail_snapshot.assert_called_once_with(
            snapshot_id="snap_fail",
            run_id=ANY,
            connection=mock_conn,
        )
        self.assertEqual(mock_database.get_connection.call_count, 2)
        self.assertEqual(mock_database.close_connection.call_count, 2)

    @patch("main.database")
    @patch("main.scraper_output.get_scraper_output")
    def test_main_run_pipeline_skipped_when_snapshot_is_none(self, mock_get_scraper, mock_database):
        """Verify main.run_pipeline skips execution when create_snapshot returns None (run in progress)."""
        mock_conn = MagicMock()
        mock_database.get_connection.return_value = mock_conn
        mock_database.create_snapshot.return_value = None

        res = main.run_pipeline()

        self.assertEqual(res, {})
        mock_get_scraper.assert_not_called()
        self.assertEqual(mock_database.get_connection.call_count, 1)
        self.assertEqual(mock_database.close_connection.call_count, 1)

    @patch("database.snapshot.complete_snapshot")
    def test_create_snapshot_no_running(self, mock_complete):
        """Test create_snapshot inserts new snapshot when no snapshot is currently running."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [None, ("new_snap_1",)]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        snap_id = snapshot_module.create_snapshot(run_id="run_1", connection=mock_conn)

        self.assertEqual(snap_id, "new_snap_1")
        mock_complete.assert_not_called()
        self.assertEqual(mock_conn.commit.call_count, 1)

    @patch("database.snapshot.complete_snapshot")
    def test_create_snapshot_recent_running_skips(self, mock_complete):
        """Test create_snapshot returns None when a snapshot is running within 180s."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        recent_time = datetime.now() - timedelta(seconds=60)
        mock_cursor.fetchone.return_value = ("old_snap_active", recent_time)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        snap_id = snapshot_module.create_snapshot(run_id="run_2", connection=mock_conn)

        self.assertIsNone(snap_id)
        mock_complete.assert_not_called()
        # No insert should have happened
        mock_cursor.execute.assert_called_once()

    @patch("database.snapshot.complete_snapshot")
    def test_create_snapshot_stale_running_recovers(self, mock_complete):
        """Test create_snapshot marks stale snapshot (>= 180s) as failed and creates new snapshot."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        stale_time = datetime.now() - timedelta(seconds=200)
        mock_cursor.fetchone.side_effect = [("old_snap_stale", stale_time), ("new_snap_2",)]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        snap_id = snapshot_module.create_snapshot(run_id="run_3", connection=mock_conn)

        self.assertEqual(snap_id, "new_snap_2")
        mock_complete.assert_called_once_with("old_snap_stale", run_id="unknown", status="failed", connection=mock_conn)
        self.assertEqual(mock_conn.commit.call_count, 2)

    @patch("database.snapshot.complete_snapshot")
    def test_create_snapshot_timezone_aware_stale_recovers(self, mock_complete):
        """Test create_snapshot correctly computes elapsed time with timezone-aware datetime."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        stale_time_utc = datetime.now(timezone.utc) - timedelta(seconds=300)
        mock_cursor.fetchone.side_effect = [("old_snap_tz", stale_time_utc), ("new_snap_tz",)]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        snap_id = snapshot_module.create_snapshot(run_id="run_tz", connection=mock_conn)

        self.assertEqual(snap_id, "new_snap_tz")
        mock_complete.assert_called_once_with("old_snap_tz", run_id="unknown", status="failed", connection=mock_conn)

    @patch("database.snapshot.complete_snapshot")
    def test_create_snapshot_timezone_aware_recent_skips(self, mock_complete):
        """Test create_snapshot returns None when a timezone-aware snapshot is running within 180s."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        recent_time_utc = datetime.now(timezone.utc) - timedelta(seconds=60)
        mock_cursor.fetchone.return_value = ("old_snap_tz_active", recent_time_utc)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        snap_id = snapshot_module.create_snapshot(run_id="run_tz_active", connection=mock_conn)

        self.assertIsNone(snap_id)
        mock_complete.assert_not_called()

    @patch("database.snapshot.complete_snapshot")
    def test_create_snapshot_iso_string_recent_and_stale(self, mock_complete):
        """Test create_snapshot parses ISO string timestamps correctly for recent and stale checks."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        # 1. Recent ISO string (< 180s)
        recent_str = (datetime.now(timezone.utc) - timedelta(seconds=45)).isoformat()
        mock_cursor.fetchone.return_value = ("old_snap_str", recent_str)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        res_recent = snapshot_module.create_snapshot(run_id="run_str_1", connection=mock_conn)
        self.assertIsNone(res_recent)
        mock_complete.assert_not_called()

        # 2. Stale ISO string (>= 180s)
        stale_str = (datetime.now(timezone.utc) - timedelta(seconds=250)).isoformat()
        mock_cursor.fetchone.side_effect = [("old_snap_str_stale", stale_str), ("new_snap_str",)]
        res_stale = snapshot_module.create_snapshot(run_id="run_str_2", connection=mock_conn)
        self.assertEqual(res_stale, "new_snap_str")
        mock_complete.assert_called_once_with("old_snap_str_stale", run_id="unknown", status="failed", connection=mock_conn)

    @patch("database.snapshot.complete_snapshot")
    def test_create_snapshot_clock_skew_and_future_timestamp(self, mock_complete):
        """Test create_snapshot handles slight clock skew (skip) and extreme future timestamps (recover)."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Slight DB clock skew: started_at is 5s ahead of app clock (-5s elapsed) -> treated as running (< 180s)
        future_skew = datetime.now(timezone.utc) + timedelta(seconds=5)
        mock_cursor.fetchone.return_value = ("old_snap_skew", future_skew)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        res_skew = snapshot_module.create_snapshot(run_id="run_skew", connection=mock_conn)
        self.assertIsNone(res_skew)
        mock_complete.assert_not_called()

        # Extreme future / timezone corrupt timestamp: started_at is 1 hour in the future (-3600s elapsed) -> recovers
        extreme_future = datetime.now(timezone.utc) + timedelta(hours=1)
        mock_cursor.fetchone.side_effect = [("old_snap_corrupt", extreme_future), ("new_snap_recovered",)]

        res_corrupt = snapshot_module.create_snapshot(run_id="run_corrupt", connection=mock_conn)
        self.assertEqual(res_corrupt, "new_snap_recovered")
        mock_complete.assert_called_once_with("old_snap_corrupt", run_id="unknown", status="failed", connection=mock_conn)

    def test_snapshot_input_validation(self):
        """Test input validation for create_snapshot and complete_snapshot."""
        mock_conn = MagicMock()

        # create_snapshot requires run_id
        with self.assertRaises(ValueError):
            snapshot_module.create_snapshot(run_id="", connection=mock_conn)
        with self.assertRaises(ValueError):
            snapshot_module.create_snapshot(run_id=None, connection=mock_conn)

        # complete_snapshot requires snapshot_id
        with self.assertRaises(ValueError):
            snapshot_module.complete_snapshot(snapshot_id="", run_id="run_1", connection=mock_conn)
        with self.assertRaises(ValueError):
            snapshot_module.complete_snapshot(snapshot_id=None, run_id="run_1", connection=mock_conn)

        # complete_snapshot requires valid status
        with self.assertRaises(ValueError):
            snapshot_module.complete_snapshot(snapshot_id="snap_1", run_id="run_1", status="invalid_status", connection=mock_conn)

    @patch("main.database")
    @patch("main.scraper_output.get_scraper_output")
    @patch("main.validator.validate_prices")
    @patch("main.price_aggregator.aggregate_prices")
    @patch("main.change.calculate_change_24h")
    def test_main_run_pipeline_with_external_connection(
        self,
        mock_calc_change,
        mock_aggregate,
        mock_validate,
        mock_get_scraper,
        mock_database,
    ):
        """Verify main.run_pipeline preserves caller-owned connection without calling get/close_connection."""
        ext_conn = MagicMock()
        mock_database.create_snapshot.return_value = "snap_ext"
        mock_database.publish_snapshot.return_value = {"snapshot_id": "snap_ext", "published_rates": 1}
        mock_get_scraper.return_value = ({}, {})
        mock_validate.return_value = {}
        mock_aggregate.return_value = {}
        mock_calc_change.return_value = {}

        res = main.run_pipeline(connection=ext_conn)

        self.assertEqual(res["snapshot_id"], "snap_ext")
        # Since caller provided the connection, main should not acquire or close connections
        mock_database.get_connection.assert_not_called()
        mock_database.close_connection.assert_not_called()
        mock_database.create_snapshot.assert_called_once_with(ANY, connection=ext_conn)
        mock_calc_change.assert_called_once_with(snapshot_id="snap_ext", current_rates={}, connection=ext_conn)
        mock_database.publish_snapshot.assert_called_once()
        self.assertEqual(mock_database.publish_snapshot.call_args[1]["connection"], ext_conn)

    @patch("main.database")
    @patch("main.scraper_output.get_scraper_output")
    @patch("main.validator.validate_prices")
    @patch("main.price_aggregator.aggregate_prices")
    @patch("main.change.calculate_change_24h")
    def test_main_run_pipeline_phase3_failure(
        self,
        mock_calc_change,
        mock_aggregate,
        mock_validate,
        mock_get_scraper,
        mock_database,
    ):
        """Verify main.run_pipeline fails snapshot and closes connection when Phase 3 raises an exception."""
        mock_conn = MagicMock()
        mock_conn.closed = 0
        mock_database.get_connection.return_value = mock_conn
        mock_database.create_snapshot.return_value = "snap_phase3_fail"
        mock_get_scraper.return_value = ({}, {})
        mock_validate.return_value = {}
        mock_aggregate.return_value = {}
        mock_calc_change.side_effect = RuntimeError("Phase 3 DB calculation failed")

        with self.assertRaises(RuntimeError):
            main.run_pipeline()

        mock_database.fail_snapshot.assert_called_once_with(
            snapshot_id="snap_phase3_fail",
            run_id=ANY,
            connection=mock_conn,
        )
        self.assertEqual(mock_database.get_connection.call_count, 2)
        self.assertEqual(mock_database.close_connection.call_count, 2)


if __name__ == "__main__":
    unittest.main()

