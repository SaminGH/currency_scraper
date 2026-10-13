import unittest
from unittest.mock import ANY, MagicMock, patch

import confidence
import scraper_output
import validator
import price_aggregator
import main


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
        """Verify main.run_pipeline invokes stages in sequence and publishes snapshot."""
        mock_conn = MagicMock()
        mock_cursor_ctx = MagicMock()
        mock_cursor_ctx.fetchone.return_value = (True,)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor_ctx)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
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
        mock_database.close_connection.assert_called_once()

    @patch("main.database")
    @patch("main.scraper_output.get_scraper_output")
    def test_main_run_pipeline_failure(self, mock_get_scraper, mock_database):
        """Verify main.run_pipeline calls fail_snapshot and closes connection on exception."""
        mock_database.get_connection.return_value = "fake_conn"
        mock_database.create_snapshot.return_value = "snap_fail"
        mock_get_scraper.side_effect = RuntimeError("Fatal scraper manager crash")

        with self.assertRaises(RuntimeError):
            main.run_pipeline()

        mock_database.fail_snapshot.assert_called_once_with(
            snapshot_id="snap_fail",
            run_id=ANY,
            connection="fake_conn",
        )
        mock_database.close_connection.assert_called_once()


if __name__ == "__main__":
    unittest.main()
