"""
Unit tests for the Dedicated Deterministic Confidence Score Engine (confidence.py)
and centralized configuration (confidence_config.py).
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import confidence
import confidence_config
from confidence_config import ConfidenceConfig


class TestConfidenceEngine(unittest.TestCase):

    def setUp(self):
        # Default config reference
        self.default_cfg = confidence_config.DEFAULT_CONFIG

    def test_deterministic_identical_outputs(self):
        """Identical inputs must always produce the exact same rating output and metrics."""
        valid_prices = {"tgju": 100000.0, "bonbast": 100100.0, "navasan": 100050.0}
        total_sources = 4
        snapshot_time = "2026-10-12 14:00:00"

        res1 = confidence.calculate_confidence(valid_prices, total_sources, snapshot_time)
        res2 = confidence.calculate_confidence(valid_prices, total_sources, snapshot_time)

        self.assertEqual(res1, res2)
        self.assertEqual(res1["rating"], "HIGH")
        self.assertEqual(res1["score_reason"], "valid_sources_above_threshold_low_dispersion")

    def test_source_count_less_than_two_yields_low(self):
        """Valid source count < 2 must yield LOW rating and skip dispersion."""
        # 0 valid sources
        res_zero = confidence.calculate_confidence({}, total_sources=4)
        self.assertEqual(res_zero["rating"], "LOW")
        self.assertIsNone(res_zero["metrics"]["dispersion_pct"])
        self.assertEqual(res_zero["metrics"]["valid_sources_count"], 0)
        self.assertEqual(res_zero["metrics"]["total_sources_count"], 4)

        # 1 valid source
        res_one = confidence.calculate_confidence({"tgju": 100000.0}, total_sources=4)
        self.assertEqual(res_one["rating"], "LOW")
        self.assertIsNone(res_one["metrics"]["dispersion_pct"])
        self.assertEqual(res_one["metrics"]["valid_sources_count"], 1)
        self.assertEqual(res_one["score_reason"], "insufficient_valid_sources")

    def test_two_sources_potential_medium(self):
        """Two valid sources can at most achieve MEDIUM rating, never HIGH."""
        # Low dispersion (<= 0.5%)
        # Mean = 100050.0, Spread = 100.0 -> Dispersion = 100 / 100050 ~= 0.0009995 <= 0.005
        prices_low_disp = {"tgju": 100000.0, "bonbast": 100100.0}
        res = confidence.calculate_confidence(prices_low_disp, total_sources=4)
        self.assertEqual(res["rating"], "MEDIUM")
        self.assertEqual(res["score_reason"], "two_valid_sources_acceptable_dispersion")
        self.assertLess(res["metrics"]["dispersion_pct"], 0.005)

        # Moderate dispersion (<= 1.0%)
        # Mean = 100350.0, Spread = 700.0 -> Dispersion = 700 / 100350 ~= 0.00697 <= 0.01
        prices_mod_disp = {"tgju": 100000.0, "bonbast": 100700.0}
        res_mod = confidence.calculate_confidence(prices_mod_disp, total_sources=4)
        self.assertEqual(res_mod["rating"], "MEDIUM")
        self.assertEqual(res_mod["score_reason"], "two_valid_sources_acceptable_dispersion")

        # Excessive dispersion (> 1.0%) -> degrades to LOW
        # Mean = 105000.0, Spread = 10000.0 -> Dispersion = 0.0952 > 0.01
        prices_high_disp = {"tgju": 100000.0, "bonbast": 110000.0}
        res_high = confidence.calculate_confidence(prices_high_disp, total_sources=4)
        self.assertEqual(res_high["rating"], "LOW")
        self.assertEqual(res_high["score_reason"], "excessive_dispersion_degraded_to_low")

    def test_three_or_more_sources_high_potential_and_degradation(self):
        """Three or more valid sources have HIGH potential, degrading on dispersion."""
        # 1. Low dispersion (<= 0.5% / 0.005) -> HIGH
        # Mean = 100050.0, max = 100100.0, min = 100000.0, dispersion = 100 / 100050 ~= 0.0009995
        prices_high = {
            "tgju": 100000.0,
            "bonbast": 100100.0,
            "navasan": 100050.0,
        }
        res_high = confidence.calculate_confidence(prices_high, total_sources=3)
        self.assertEqual(res_high["rating"], "HIGH")
        self.assertEqual(res_high["score_reason"], "valid_sources_above_threshold_low_dispersion")
        self.assertLessEqual(res_high["metrics"]["dispersion_pct"], 0.005)

        # 2. Moderate dispersion (0.005 < dispersion <= 0.01) -> degrades from HIGH to MEDIUM
        # Mean = 100350.0, max = 100700.0, min = 100000.0, dispersion = 700 / 100350 ~= 0.00697
        prices_medium = {
            "tgju": 100000.0,
            "bonbast": 100700.0,
            "navasan": 100350.0,
        }
        res_med = confidence.calculate_confidence(prices_medium, total_sources=3)
        self.assertEqual(res_med["rating"], "MEDIUM")
        self.assertEqual(res_med["score_reason"], "moderate_dispersion_degraded_to_medium")
        self.assertGreater(res_med["metrics"]["dispersion_pct"], 0.005)
        self.assertLessEqual(res_med["metrics"]["dispersion_pct"], 0.01)

        # 3. Excessive dispersion (> 0.01 / 1.0%) -> degrades to LOW
        # Mean = 101000.0, max = 102000.0, min = 100000.0, dispersion = 2000 / 101000 ~= 0.0198
        prices_low = {
            "tgju": 100000.0,
            "bonbast": 102000.0,
            "navasan": 101000.0,
        }
        res_low = confidence.calculate_confidence(prices_low, total_sources=3)
        self.assertEqual(res_low["rating"], "LOW")
        self.assertEqual(res_low["score_reason"], "excessive_dispersion_degraded_to_low")

    def test_dispersion_division_by_zero_guard(self):
        """Guard against division by zero if Mean(P_valid) == 0."""
        zero_prices = {"source_a": 0.0, "source_b": 0.0, "source_c": 0.0}
        res = confidence.calculate_confidence(zero_prices, total_sources=3)
        self.assertEqual(res["rating"], "LOW")
        self.assertEqual(res["score_reason"], "mean_price_is_zero")
        self.assertIsNone(res["metrics"]["dispersion_pct"])

    def test_freshness_criteria_degradation(self):
        """Freshness criteria degrades confidence rating when data age exceeds max allowable delta."""
        base_time = datetime(2026, 10, 12, 14, 0, 0)
        # 1. Fresh timestamps (age = 60s < 3600s)
        fresh_timestamps = {
            "tgju": base_time - timedelta(seconds=60),
            "bonbast": base_time - timedelta(seconds=30),
            "navasan": base_time - timedelta(seconds=45),
        }
        prices = {"tgju": 100000.0, "bonbast": 100050.0, "navasan": 100020.0}
        res_fresh = confidence.calculate_confidence(
            valid_prices=prices,
            total_sources=3,
            snapshot_time=base_time,
            source_timestamps=fresh_timestamps,
        )
        self.assertEqual(res_fresh["rating"], "HIGH")

        # 2. Stale timestamps for HIGH potential (age = 4000s > 3600s) -> degrades to MEDIUM
        stale_timestamps = {
            "tgju": base_time - timedelta(seconds=4000),
            "bonbast": base_time - timedelta(seconds=30),
            "navasan": base_time - timedelta(seconds=45),
        }
        res_stale = confidence.calculate_confidence(
            valid_prices=prices,
            total_sources=3,
            snapshot_time=base_time,
            source_timestamps=stale_timestamps,
        )
        self.assertEqual(res_stale["rating"], "MEDIUM")
        self.assertIn("stale_data_degraded_to_medium", res_stale["score_reason"])
        self.assertGreater(res_stale["metrics"]["max_age_seconds"], 3600)

        # 3. Stale timestamps for MEDIUM potential (2 sources) -> degrades to LOW
        two_prices = {"tgju": 100000.0, "bonbast": 100050.0}
        two_stale_ts = {
            "tgju": base_time - timedelta(seconds=7200),
            "bonbast": base_time - timedelta(seconds=30),
        }
        res_two_stale = confidence.calculate_confidence(
            valid_prices=two_prices,
            total_sources=3,
            snapshot_time=base_time,
            source_timestamps=two_stale_ts,
        )
        self.assertEqual(res_two_stale["rating"], "LOW")
        self.assertIn("stale_data_degraded_to_low", res_two_stale["score_reason"])

    def test_custom_configuration_override(self):
        """Verify thresholds are customizable via ConfidenceConfig without hard-coding."""
        custom_cfg = ConfidenceConfig(
            min_valid_sources_high=4,
            min_valid_sources_medium=3,
            max_dispersion_high=0.001,
            max_dispersion_medium=0.003,
            max_age_seconds=600.0,
        )

        prices = {"s1": 100000.0, "s2": 100050.0, "s3": 100020.0}
        # With default config (min 3 sources for HIGH), this would be HIGH
        res_default = confidence.calculate_confidence(prices, total_sources=4)
        self.assertEqual(res_default["rating"], "HIGH")

        # With custom config requiring min 4 sources for HIGH, 3 sources only gets MEDIUM
        res_custom = confidence.calculate_confidence(
            prices, total_sources=4, config=custom_cfg
        )
        self.assertEqual(res_custom["rating"], "MEDIUM")

    def test_robustness_anti_crash(self):
        """Malformed or unexpected input data must not crash and safely return LOW."""
        # Non-dict prices
        res_bad = confidence.calculate_confidence("invalid_not_a_dict", total_sources=3)  # type: ignore
        self.assertEqual(res_bad["rating"], "LOW")
        self.assertIn("calculation_error", res_bad["score_reason"])

        # None prices
        res_none = confidence.calculate_confidence(None, total_sources=3)  # type: ignore
        self.assertEqual(res_none["rating"], "LOW")

        # Non-numeric prices mixed with valid prices
        mixed_prices = {"s1": 100000.0, "s2": "bad_string", "s3": None}  # type: ignore
        res_mixed = confidence.calculate_confidence(mixed_prices, total_sources=3)
        # Only 1 numeric price remains -> valid_count = 1 < 2 -> LOW
        self.assertEqual(res_mixed["rating"], "LOW")
        self.assertEqual(res_mixed["metrics"]["valid_sources_count"], 1)

    def test_timestamp_parsing_formats(self):
        """Test timestamp parsing across string ISO, standard format, and datetime objects."""
        snap_str = "2026-10-12 14:00:00"
        src_ts = {"s1": "2026-10-12T13:58:00"}
        prices = {"s1": 100000.0, "s2": 100050.0, "s3": 100020.0}

        res = confidence.calculate_confidence(
            valid_prices=prices,
            total_sources=3,
            snapshot_time=snap_str,
            source_timestamps=src_ts,
        )
        self.assertEqual(res["rating"], "HIGH")
        self.assertEqual(res["metrics"]["max_age_seconds"], 120.0)

    @patch("database.aggregated_rates.execute_values")
    @patch("database.aggregated_rates.get_currency_ids")
    def test_database_aggregated_rates_compatibility(self, mock_get_currency_ids, mock_execute_values):
        """Verify save_aggregated_rates saves string confidence rating without schema changes."""
        from database.aggregated_rates import save_aggregated_rates
        from unittest.mock import MagicMock

        mock_conn = MagicMock()
        mock_get_currency_ids.return_value = {"USD": 1}

        final_prices = {
            "USD": {
                "price": 100000.0,
                "confidence": "HIGH",
                "confidence_reason": "valid_sources_above_threshold_low_dispersion",
                "sources": ["tgju", "bonbast", "navasan"],
                "sources_total": 4,
                "sources_used": 3,
                "status": "valid",
                "publishable": True,
                "publishability_reason": "at_least_two_valid_sources",
            }
        }

        count = save_aggregated_rates(snapshot_id=1, final_prices=final_prices, connection=mock_conn)
        self.assertEqual(count, 1)

        mock_execute_values.assert_called_once()
        inserted_rows = mock_execute_values.call_args[0][2]
        self.assertEqual(len(inserted_rows), 1)
        row = inserted_rows[0]
        # (snapshot_id, currency_id, price, sources_total, sources_used, confidence, confidence_reason, ...)
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], 1)
        self.assertEqual(row[2], 100000.0)
        self.assertEqual(row[3], 4)
        self.assertEqual(row[4], 3)
        self.assertEqual(row[5], "HIGH")
        self.assertEqual(row[6], "valid_sources_above_threshold_low_dispersion")

    @patch("database.published_rates.execute_values")
    @patch("database.published_rates.get_currency_ids")
    def test_database_published_rates_compatibility(self, mock_get_currency_ids, mock_execute_values):
        """Verify save_published_rates saves string confidence rating without schema changes."""
        from database.published_rates import save_published_rates
        from unittest.mock import MagicMock

        mock_conn = MagicMock()
        mock_get_currency_ids.return_value = {"USD": 1}

        published_rates = {
            "USD": {
                "price": 100000.0,
                "change_24h": 0.5,
                "confidence": "HIGH",
                "sources": ["tgju", "bonbast", "navasan"],
                "sources_total": 4,
                "sources_used": 3,
            }
        }

        count = save_published_rates(snapshot_id=1, published_rates=published_rates, connection=mock_conn)
        self.assertEqual(count, 1)

        mock_execute_values.assert_called_once()
        inserted_rows = mock_execute_values.call_args[0][2]
        self.assertEqual(len(inserted_rows), 1)
        row = inserted_rows[0]
        # (snapshot_id, currency_id, price, change_24h, sources_total, sources_used, confidence)
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], 1)
        self.assertEqual(row[2], 100000.0)
        self.assertEqual(row[3], 0.5)
        self.assertEqual(row[4], 4)
        self.assertEqual(row[5], 3)
        self.assertEqual(row[6], "HIGH")


    @patch("confidence.logger.log_event")
    def test_detailed_logging_reasons(self, mock_log_event):
        """Verify detailed structured logging explains why each currency is HIGH, MEDIUM, or LOW."""
        # 1. HIGH rating log verification
        prices_high = {"s1": 100000.0, "s2": 100100.0, "s3": 100050.0}
        confidence.calculate_confidence(prices_high, total_sources=4, currency="USD")
        mock_log_event.assert_called()
        high_kwargs = mock_log_event.call_args[1]
        self.assertEqual(high_kwargs["event"], "confidence_evaluated")
        self.assertEqual(high_kwargs["currency"], "USD")
        self.assertEqual(high_kwargs["rating"], "HIGH")
        self.assertEqual(high_kwargs["level"], "INFO")
        self.assertIn("rated HIGH", high_kwargs["reason_detail"])
        self.assertEqual(high_kwargs["valid_sources"], 3)
        self.assertEqual(high_kwargs["total_sources"], 4)
        self.assertIsNotNone(high_kwargs["dispersion_pct"])

        # 2. MEDIUM rating due to moderate dispersion log verification
        mock_log_event.reset_mock()
        prices_med = {"s1": 100000.0, "s2": 100700.0, "s3": 100350.0}
        confidence.calculate_confidence(prices_med, total_sources=4, currency="EUR")
        med_kwargs = mock_log_event.call_args[1]
        self.assertEqual(med_kwargs["currency"], "EUR")
        self.assertEqual(med_kwargs["rating"], "MEDIUM")
        self.assertIn("degraded to MEDIUM", med_kwargs["reason_detail"])

        # 3. LOW rating due to excessive dispersion log verification
        mock_log_event.reset_mock()
        prices_low_disp = {"s1": 100000.0, "s2": 102000.0, "s3": 101000.0}
        confidence.calculate_confidence(prices_low_disp, total_sources=4, currency="GBP")
        low_disp_kwargs = mock_log_event.call_args[1]
        self.assertEqual(low_disp_kwargs["currency"], "GBP")
        self.assertEqual(low_disp_kwargs["rating"], "LOW")
        self.assertEqual(low_disp_kwargs["level"], "WARNING")
        self.assertIn("exceeds maximum allowable threshold", low_disp_kwargs["reason_detail"])

        # 4. LOW rating due to insufficient sources (< 2)
        mock_log_event.reset_mock()
        confidence.calculate_confidence({"s1": 100000.0}, total_sources=4, currency="AED")
        low_src_kwargs = mock_log_event.call_args[1]
        self.assertEqual(low_src_kwargs["currency"], "AED")
        self.assertEqual(low_src_kwargs["rating"], "LOW")
        self.assertEqual(low_src_kwargs["valid_sources"], 1)
        self.assertIn("below minimum threshold", low_src_kwargs["reason_detail"])

        # 5. Stale data degradation log verification
        mock_log_event.reset_mock()
        base_time = datetime(2026, 10, 12, 14, 0, 0)
        stale_ts = {"s1": base_time - timedelta(seconds=5000)}
        confidence.calculate_confidence(
            prices_high,
            total_sources=4,
            snapshot_time=base_time,
            source_timestamps=stale_ts,
            currency="JPY",
        )
        stale_kwargs = mock_log_event.call_args[1]
        self.assertEqual(stale_kwargs["currency"], "JPY")
        self.assertTrue(stale_kwargs["is_stale"])
        self.assertIn("Stale data", stale_kwargs["reason_detail"])


if __name__ == "__main__":
    unittest.main()
