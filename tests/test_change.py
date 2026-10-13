from datetime import date, datetime, timedelta
import unittest
from unittest.mock import MagicMock, patch

import change


class TestChangeHelpers(unittest.TestCase):
    def test_extract_price(self):
        self.assertEqual(change._extract_price(100), 100.0)
        self.assertEqual(change._extract_price(100.5), 100.5)
        self.assertEqual(change._extract_price({"price": 200.0}), 200.0)
        self.assertEqual(change._extract_price({"price": "60,000"}), 60000.0)
        self.assertEqual(change._extract_price("۶۰,۰۰۰"), 60000.0)  # Persian digits
        self.assertEqual(change._extract_price("٦٠,٠٠٠"), 60000.0)  # Arabic digits
        self.assertIsNone(change._extract_price(None))
        self.assertIsNone(change._extract_price({"price": None}))
        self.assertIsNone(change._extract_price("invalid_number"))
        # Booleans must NOT be converted to 1.0 or 0.0
        self.assertIsNone(change._extract_price(True))
        self.assertIsNone(change._extract_price(False))
        self.assertIsNone(change._extract_price({"price": True}))
        # NaNs, Infs, non-positive numbers
        self.assertIsNone(change._extract_price(float("nan")))
        self.assertIsNone(change._extract_price(float("inf")))
        self.assertIsNone(change._extract_price(-50.0))
        self.assertIsNone(change._extract_price(0.0))

    def test_format_pct_value(self):
        self.assertEqual(change._format_pct_value(0.0), "0.00%")
        self.assertEqual(change._format_pct_value(-0.0), "0.00%")
        self.assertEqual(change._format_pct_value(0.00001), "0.00%")
        self.assertEqual(change._format_pct_value(0.5), "+0.50%")
        self.assertEqual(change._format_pct_value(-1.25), "-1.25%")
        self.assertEqual(change._format_pct_value("+2.3%"), "+2.30%")
        self.assertEqual(change._format_pct_value("-0.45%"), "-0.45%")
        self.assertIsNone(change._format_pct_value(None))
        self.assertIsNone(change._format_pct_value("bad_pct"))
        # Booleans and NaNs
        self.assertIsNone(change._format_pct_value(True))
        self.assertIsNone(change._format_pct_value(False))
        self.assertIsNone(change._format_pct_value(float("nan")))
        self.assertIsNone(change._format_pct_value(float("inf")))

    def test_format_change_pct(self):
        # Normal positive
        diff, pct = change._format_change_pct(105.0, 100.0)
        self.assertEqual(diff, 5.0)
        self.assertEqual(pct, "+5.00%")

        # Normal negative
        diff, pct = change._format_change_pct(95.0, 100.0)
        self.assertEqual(diff, -5.0)
        self.assertEqual(pct, "-5.00%")

        # Zero change
        diff, pct = change._format_change_pct(100.0, 100.0)
        self.assertEqual(diff, 0.0)
        self.assertEqual(pct, "0.00%")

        # Zero previous price (division by zero)
        diff, pct = change._format_change_pct(100.0, 0.0)
        self.assertIsNone(diff)
        self.assertIsNone(pct)

        # None inputs
        diff, pct = change._format_change_pct(None, 100.0)
        self.assertIsNone(diff)
        self.assertIsNone(pct)

        # Booleans, NaNs, and negative inputs
        diff, pct = change._format_change_pct(True, 100.0)
        self.assertIsNone(diff)
        diff, pct = change._format_change_pct(-10.0, 100.0)
        self.assertIsNone(diff)
        diff, pct = change._format_change_pct(float("nan"), 100.0)
        self.assertIsNone(diff)


class TestDailyChangeCalculation(unittest.TestCase):
    def setUp(self):
        change.clear_daily_change_cache()

    def tearDown(self):
        change.clear_daily_change_cache()

    def test_calculate_daily_change_first_snapshot_of_today(self):
        """First snapshot of today calculates against yesterday's snapshot and caches result."""
        ref_time = datetime(2026, 10, 13, 1, 0, 0)
        yesterday_time = datetime(2026, 10, 12, 0, 5, 0)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mock DB queries:
        # 1. Started_at of snapshot_id (if queried) -> (ref_time,)
        # 2. Check today's earlier snapshot -> None (first snapshot of today!)
        # 3. Check yesterday's baseline snapshot -> (10, yesterday_time)
        # 4. _get_snapshot_rates for yesterday -> [('USD', 50000.0), ('EUR', 60000.0)]
        # 5. Currencies active -> [('USD',), ('EUR',)]
        def mock_fetchone():
            return None  # No earlier completed snapshot today

        mock_cursor.fetchone.side_effect = [
            None,  # Today's completed snapshot check -> None
            (10, yesterday_time),  # Yesterday's baseline snapshot check
        ]
        mock_cursor.fetchall.side_effect = [
            [("USD", 50000.0), ("EUR", 60000.0)],  # published_rates for snapshot 10 (yesterday)
            [],  # aggregated_rates for snapshot 10 (supplementary)
            [("USD",), ("EUR",)],  # active currencies
        ]

        current_rates = {
            "USD": {"price": 55000.0},
            "EUR": {"price": 57000.0},
        }

        res = change.calculate_daily_change(
            snapshot_id=20,
            current_rates=current_rates,
            connection=mock_conn,
            ref_time=ref_time,
        )

        # USD: (55000 - 50000)/50000 = +10.00%
        self.assertEqual(res["USD"]["price_change"], 5000.0)
        self.assertEqual(res["USD"]["change_24h"], "+10.00%")
        # EUR: (57000 - 60000)/60000 = -5.00%
        self.assertEqual(res["EUR"]["price_change"], -3000.0)
        self.assertEqual(res["EUR"]["change_24h"], "-5.00%")

        # Verify cached in-memory
        self.assertIn(ref_time.date(), change._DAILY_CHANGE_CACHE)

        # Second call on same date should hit cache immediately without running queries
        mock_cursor.reset_mock()
        res2 = change.calculate_daily_change(
            snapshot_id=21,
            current_rates=current_rates,
            connection=mock_conn,
            ref_time=ref_time,
        )
        self.assertEqual(res2["USD"]["change_24h"], "+10.00%")
        mock_cursor.execute.assert_not_called()

    def test_calculate_daily_change_midday_restart_db_fallback(self):
        """If restarted mid-day and cache is empty, restore daily change from today's first snapshot in DB."""
        ref_time = datetime(2026, 10, 13, 14, 30, 0)
        today_first_snap_time = datetime(2026, 10, 13, 0, 2, 0)
        yesterday_snap_time = datetime(2026, 10, 12, 0, 1, 0)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            (50, today_first_snap_time),  # Today's first completed snapshot exists! (id 50)
            (40, yesterday_snap_time),    # Yesterday baseline snapshot (id 40)
        ]
        mock_cursor.fetchall.side_effect = [
            [("USD", 50000.0)],  # yesterday snapshot 40 published_rates
            [],                  # yesterday snapshot 40 aggregated_rates
            [("USD", 55000.0, 10.0)],  # snapshot 50 published_rates: price=55000, change_24h=10.0%
            [("USD", 55000.0)],  # snapshot 50 _get_snapshot_rates (published)
            [],                  # snapshot 50 _get_snapshot_rates (aggregated)
            [("USD",)],          # active currencies
        ]

        current_rates = {"USD": {"price": 58000.0}}

        res = change.calculate_daily_change(
            snapshot_id=99,
            current_rates=current_rates,
            connection=mock_conn,
            ref_time=ref_time,
        )

        # Restored fixed daily change from snapshot 50
        self.assertEqual(res["USD"]["change_24h"], "+10.00%")
        self.assertEqual(res["USD"]["price_change"], 5000.0)

        # And cached for subsequent calls
        self.assertIn(ref_time.date(), change._DAILY_CHANGE_CACHE)

    def test_calculate_daily_change_midday_restart_partial_published_and_aggregated(self):
        """Mid-day restart recovers published rates for USD, and falls back to aggregated_rates for EUR."""
        ref_time = datetime(2026, 10, 13, 14, 30, 0)
        today_first_snap_time = datetime(2026, 10, 13, 0, 2, 0)
        yesterday_snap_time = datetime(2026, 10, 12, 0, 1, 0)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            (50, today_first_snap_time),  # Today's first completed snapshot exists!
            (40, yesterday_snap_time),    # Yesterday baseline snapshot
        ]
        mock_cursor.fetchall.side_effect = [
            # Yesterday snapshot 40: USD in published, EUR in aggregated
            [("USD", 50000.0)],
            [("EUR", 50000.0)],
            # Snapshot 50: USD in published (10.0%), EUR not published
            [("USD", 55000.0, 10.0)],
            # Snapshot 50 _get_snapshot_rates: USD published, EUR in aggregated (60000.0)
            [("USD", 55000.0)],
            [("EUR", 60000.0)],
            # Active currencies
            [("USD",), ("EUR",)],
        ]

        res = change.calculate_daily_change(
            snapshot_id=99,
            current_rates={"USD": {"price": 58000.0}, "EUR": {"price": 62000.0}},
            connection=mock_conn,
            ref_time=ref_time,
        )

        # USD from published
        self.assertEqual(res["USD"]["change_24h"], "+10.00%")
        self.assertEqual(res["USD"]["price_change"], 5000.0)
        # EUR from aggregated vs yesterday: (60000 - 50000)/50000 = +20.00%
        self.assertEqual(res["EUR"]["change_24h"], "+20.00%")
        self.assertEqual(res["EUR"]["price_change"], 10000.0)

    def test_calculate_daily_change_missing_yesterday_fallback_to_prior(self):
        """If yesterday snapshot is missing, fallback to latest completed prior snapshot."""
        ref_time = datetime(2026, 10, 13, 0, 1, 0)
        prior_time = datetime(2026, 10, 10, 23, 0, 0)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            None,  # No snapshot earlier today
            None,  # No snapshot yesterday
            (5, prior_time),  # Prior snapshot found!
        ]
        mock_cursor.fetchall.side_effect = [
            [("USD", 48000.0)],  # published rates for snapshot 5
            [],                  # aggregated rates for snapshot 5
            [("USD",)],          # active currencies
        ]

        res = change.calculate_daily_change(
            snapshot_id=20,
            current_rates={"USD": {"price": 50400.0}},
            connection=mock_conn,
            ref_time=ref_time,
        )

        # (50400 - 48000)/48000 = +5.00%
        self.assertEqual(res["USD"]["change_24h"], "+5.00%")
        self.assertEqual(res["USD"]["price_change"], 2400.0)

    def test_calculate_daily_change_missing_all_baselines_caches_result(self):
        """If no prior snapshot exists at all, daily change is None and IS cached in memory."""
        ref_time = datetime(2026, 10, 13, 0, 1, 0)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            None,  # No snapshot earlier today
            None,  # No snapshot yesterday
            None,  # No prior snapshot
        ]
        mock_cursor.fetchall.side_effect = [
            [("USD",)],  # active currencies
        ]

        res = change.calculate_daily_change(
            snapshot_id=1,
            current_rates={"USD": {"price": 50000.0}},
            connection=mock_conn,
            ref_time=ref_time,
        )

        self.assertIsNone(res["USD"]["change_24h"])
        self.assertIsNone(res["USD"]["price_change"])

        # Crucial requirement: must be cached in memory so subsequent snapshots do not spam queries/warnings
        self.assertIn(ref_time.date(), change._DAILY_CHANGE_CACHE)

        # Snapshot 2 calls calculate_daily_change
        mock_cursor.reset_mock()
        res2 = change.calculate_daily_change(
            snapshot_id=2,
            current_rates={"USD": {"price": 50100.0}},
            connection=mock_conn,
            ref_time=ref_time,
        )
        self.assertIsNone(res2["USD"]["change_24h"])
        mock_cursor.execute.assert_not_called()

    def test_calculate_daily_change_fast_path_registers_new_currency(self):
        """When a new currency appears mid-day that wasn't in cache, fast path registers it."""
        ref_date = date(2026, 10, 13)
        change._DAILY_CHANGE_CACHE[ref_date] = {
            "USD": {"price_change": 500.0, "change_24h": "+1.00%"}
        }

        res = change.calculate_daily_change(
            snapshot_id=10,
            current_rates={"USD": 50500.0, "TRY": 1500.0},
            ref_time=datetime(2026, 10, 13, 12, 0, 0),
        )
        self.assertEqual(res["USD"]["change_24h"], "+1.00%")
        self.assertIsNone(res["TRY"]["change_24h"])
        # In-memory cache is also updated for TRY
        self.assertIn("TRY", change._DAILY_CHANGE_CACHE[ref_date])

    def test_calculate_daily_change_midnight_rollover(self):
        """Midnight rollover invalidates prior day's cache key and triggers new calculation."""
        day1_time = datetime(2026, 10, 13, 23, 59, 0)
        day2_time = datetime(2026, 10, 14, 0, 1, 0)

        # Pre-fill Day 1 cache
        change._DAILY_CHANGE_CACHE[day1_time.date()] = {
            "USD": {"price_change": 100.0, "change_24h": "+0.50%"}
        }

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Day 2 calculation: first snapshot of Oct 14
        mock_cursor.fetchone.side_effect = [
            None,  # No snapshot earlier on Oct 14
            (100, datetime(2026, 10, 13, 0, 1, 0)),  # Oct 13 baseline snapshot
        ]
        mock_cursor.fetchall.side_effect = [
            [("USD", 50000.0)],  # published rates for snapshot 100
            [],                  # aggregated rates for snapshot 100
            [("USD",)],          # active currencies
        ]

        res_day2 = change.calculate_daily_change(
            snapshot_id=200,
            current_rates={"USD": 55000.0},
            connection=mock_conn,
            ref_time=day2_time,
        )

        self.assertEqual(res_day2["USD"]["change_24h"], "+10.00%")
        self.assertIn(day1_time.date(), change._DAILY_CHANGE_CACHE)
        self.assertIn(day2_time.date(), change._DAILY_CHANGE_CACHE)


class TestDailyHighLowCalculation(unittest.TestCase):
    def test_calculate_daily_high_low_with_today_history(self):
        """High and Low are evaluated from today 00:00:00 up to current snapshot, merged with current rates."""
        ref_time = datetime(2026, 10, 13, 15, 0, 0)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mock DB query for MAX and MIN from published_rates today
        mock_cursor.fetchall.side_effect = [
            [("USD", 62000.0, 59000.0), ("EUR", 65000.0, 64000.0)],  # published rates extremes
            [("USD",), ("EUR",)],  # active currencies
        ]

        current_rates = {
            "USD": {"price": 63000.0},  # New today's high!
            "EUR": {"price": 63500.0},  # New today's low!
        }

        res = change.calculate_daily_high_low(
            snapshot_id=30,
            current_rates=current_rates,
            connection=mock_conn,
            ref_time=ref_time,
        )

        # USD: db was (62000, 59000), current is 63000 -> high=63000, low=59000
        self.assertEqual(res["USD"]["high_24h"], 63000.0)
        self.assertEqual(res["USD"]["low_24h"], 59000.0)

        # EUR: db was (65000, 64000), current is 63500 -> high=65000, low=63500
        self.assertEqual(res["EUR"]["high_24h"], 65000.0)
        self.assertEqual(res["EUR"]["low_24h"], 63500.0)

    def test_calculate_daily_high_low_first_snapshot_of_today(self):
        """On today's first snapshot with no prior published rates today, high and low equal current price."""
        ref_time = datetime(2026, 10, 13, 0, 1, 0)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchall.side_effect = [
            [],  # No published rates yet today
            [("USD",)],  # active currencies
        ]

        current_rates = {"USD": {"price": 60000.0}}

        res = change.calculate_daily_high_low(
            snapshot_id=1,
            current_rates=current_rates,
            connection=mock_conn,
            ref_time=ref_time,
        )

        self.assertEqual(res["USD"]["high_24h"], 60000.0)
        self.assertEqual(res["USD"]["low_24h"], 60000.0)

    def test_calculate_daily_high_low_filters_invalid_prices(self):
        """High and Low calculation filters out 0, negative, and NaN/inf candidate prices."""
        ref_time = datetime(2026, 10, 13, 10, 0, 0)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # DB has invalid prices: max=-100, min=0
        mock_cursor.fetchall.side_effect = [
            [("USD", -100.0, 0.0)],
            [("USD",)],  # active currencies
        ]

        current_rates = {"USD": {"price": 60000.0}}

        res = change.calculate_daily_high_low(
            snapshot_id=5,
            current_rates=current_rates,
            connection=mock_conn,
            ref_time=ref_time,
        )

        # Only the valid 60000.0 current price is used
        self.assertEqual(res["USD"]["high_24h"], 60000.0)
        self.assertEqual(res["USD"]["low_24h"], 60000.0)


class TestDailyChangeAndRangeIntegration(unittest.TestCase):
    def setUp(self):
        change.clear_daily_change_cache()

    def tearDown(self):
        change.clear_daily_change_cache()

    @patch("change.calculate_daily_high_low")
    @patch("change.calculate_daily_change")
    def test_calculate_daily_change_and_range_combined(self, mock_calc_change, mock_calc_hl):
        mock_calc_change.return_value = {
            "USD": {"price_change": 500.0, "change_24h": "+0.01%"},
        }
        mock_calc_hl.return_value = {
            "USD": {"high_24h": 60500.0, "low_24h": 59800.0},
        }

        mock_conn = MagicMock()
        res = change.calculate_daily_change_and_range(
            snapshot_id=10,
            current_rates={"USD": {"price": 60200.0}},
            connection=mock_conn,
        )

        self.assertIn("USD", res)
        self.assertEqual(res["USD"]["price_change"], 500.0)
        self.assertEqual(res["USD"]["change_24h"], "+0.01%")
        self.assertEqual(res["USD"]["high_24h"], 60500.0)
        self.assertEqual(res["USD"]["low_24h"], 59800.0)

    @patch("change.calculate_daily_change_and_range")
    def test_calculate_change_24h_alias(self, mock_coord):
        mock_coord.return_value = {"USD": {"change_24h": "+1.00%"}}
        res = change.calculate_change_24h(snapshot_id=5, current_rates={})
        mock_coord.assert_called_once_with(
            snapshot_id=5,
            current_rates={},
            connection=None,
        )
        self.assertEqual(res, {"USD": {"change_24h": "+1.00%"}})


if __name__ == "__main__":
    unittest.main()
