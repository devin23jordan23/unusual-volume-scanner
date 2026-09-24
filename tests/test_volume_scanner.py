import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from app.config import DEFAULT_UNIVERSE, Settings, Thresholds
from app.discord import DiscordNotifier
from app.models import Candle, MovementFeatures, Severity, StockSnapshot
from app.profiles import build_profile
from app.rules import evaluate, evaluate_lanes
from app.scanner import VolumeScanner
from app.state import AlertState, CandidateBook, RollingStockState

from app.schwab import SchwabClient

TZ = ZoneInfo("America/New_York")


def historical_candles(days=20):
    output = []
    start = date(2026, 8, 3)
    for day_offset in range(days):
        day = start + timedelta(days=day_offset)
        if day.weekday() >= 5:
            continue
        price = 300 + day_offset
        for minute in range(20):
            stamp = datetime(day.year, day.month, day.day, 9, 30, tzinfo=TZ) + timedelta(minutes=minute)
            output.append(Candle(stamp, price, price + 0.3, price - 0.2, price + 0.1, 100_000 if minute < 5 else 20_000))
            price += 0.1
    return output


class VolumeScannerTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 9, 18)
        self.profile = build_profile("COIN", historical_candles(), 10, self.today)

    def test_profile_accounts_for_heavy_open(self):
        first_five = self.profile.expected_window(4)
        later_five = self.profile.expected_window(14)
        self.assertGreater(first_five, later_five * 4)

    def test_true_time_of_day_rvol(self):
        stamp = datetime(2026, 9, 18, 9, 34, 59, tzinfo=TZ)
        normal = self.profile.expected_cumulative(4, 59 / 60)
        snapshot = StockSnapshot("COIN", 307, int(normal * 3), stamp, 300, 299, 308, 299)
        alert = evaluate(snapshot, self.profile, int(self.profile.expected_window(4) * 3), 1.0, Thresholds(min_5m_dollar_volume=1))
        self.assertIsNotNone(alert)
        self.assertAlmostEqual(alert.tod_rvol, 3.0, places=1)
        self.assertEqual(alert.setup, "OPENING DRIVE")

    def test_high_priced_opening_drive_is_not_filtered_out(self):
        stamp = datetime(2026, 9, 22, 9, 34, 59, tzinfo=TZ)
        normal = self.profile.expected_cumulative(4, 59 / 60)
        snapshot = StockSnapshot("SNDK", 1_800, int(normal * 3), stamp, 1_750, 1_740, 1_805, 1_750)
        alert = evaluate(snapshot, self.profile, int(self.profile.expected_window(4) * 3), 1.0, Thresholds(min_5m_dollar_volume=1))
        self.assertIsNotNone(alert)
        self.assertEqual(alert.setup, "OPENING DRIVE")

    def test_skhy_is_in_default_universe(self):
        self.assertIn("SKHY", DEFAULT_UNIVERSE)

    def test_both_google_share_classes_are_in_default_universe(self):
        self.assertTrue({"GOOG", "GOOGL"}.issubset(DEFAULT_UNIVERSE))

    def test_selected_bank_names_in_default_universe(self):
        self.assertTrue({"JPM", "BAC"}.issubset(DEFAULT_UNIVERSE))
        self.assertTrue({"C", "GS", "MS", "SCHW", "AXP"}.isdisjoint(DEFAULT_UNIVERSE))

    def test_global_notification_interval_is_disabled(self):
        stamp = datetime(2026, 9, 22, 10, 0, tzinfo=TZ)
        state = AlertState("/path/that/does/not/exist")
        interval = Settings().min_alert_interval_seconds
        self.assertEqual(interval, 0)
        self.assertTrue(state.notification_ready(stamp, interval))
        state.sent["COIN"] = {"sent_at": stamp.timestamp(), "severity": "HIGH"}
        self.assertTrue(state.notification_ready(stamp, interval))

    def test_alert_batch_is_unlimited_by_default(self):
        self.assertEqual(Settings().max_alerts_per_scan, 0)

    def test_unauthorized_worker_does_not_replace_newer_tokens(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True):
            client = SchwabClient(Settings(data_dir=directory))
            client.save_tokens({"access_token": "new", "refresh_token": "refresh", "expires_in": 1800})
            client.refresh_tokens = Mock()
            client.refresh_after_unauthorized("old")
            client.refresh_tokens.assert_not_called()

    def test_broker_token_is_cached_and_refreshes_after_unauthorized(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.side_effect = [
            {"access_token": "broker-one", "expires_in": 240},
            {"access_token": "broker-two", "expires_in": 240},
        ]
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {
            "SCHWAB_TOKEN_BROKER_URL": "https://broker.test/schwab-token",
            "SCHWAB_TOKEN_BROKER_KEY": "shared-secret",
        }, clear=True), patch("app.schwab.requests.get", return_value=response) as get:
            client = SchwabClient(Settings(data_dir=directory))
            self.assertEqual(client.access_token(), "broker-one")
            self.assertEqual(client.access_token(), "broker-one")
            client.invalidate_broker_token("broker-one")
            self.assertEqual(client.access_token(), "broker-two")
            self.assertEqual(get.call_count, 2)

    def test_high_volume_without_movement_is_rejected(self):
        stamp = datetime(2026, 9, 18, 10, 0, 30, tzinfo=TZ)
        snapshot = StockSnapshot("COIN", 300.02, 5_000_000, stamp, 300, 300, 300.05, 299.95)
        alert = evaluate(snapshot, self.profile, 1_000_000, 0.01, Thresholds(min_5m_dollar_volume=1))
        self.assertIsNone(alert)

    def test_stale_high_rvol_move_is_rejected_after_open(self):
        stamp = datetime(2026, 9, 18, 11, 0, 30, tzinfo=TZ)
        snapshot = StockSnapshot("SHOP", 330, 9_000_000, stamp, 300, 299, 331, 299)
        alert = evaluate(snapshot, self.profile, 1_000_000, 0.02, Thresholds(min_5m_dollar_volume=1))
        self.assertIsNone(alert)

    def test_small_late_day_drift_is_rejected_even_when_speed_is_relative_high(self):
        profile = replace(
            self.profile,
            atr14=6.32,
            minute_volume=tuple([20_000] * 390),
            move_5m_pct=tuple([0.10] * 390),
        )
        stamp = datetime(2026, 9, 18, 15, 44, 0, tzinfo=TZ)
        snapshot = StockSnapshot("SHOP", 149.04, 9_000_000, stamp, 144.55, 143, 150, 143)
        alert = evaluate(snapshot, profile, 1_000_000, 0.45, Thresholds(min_5m_dollar_volume=1))
        self.assertIsNone(alert)

    def test_meaningful_local_atr_move_can_qualify_after_open(self):
        profile = replace(
            self.profile,
            atr14=6.32,
            minute_volume=tuple([20_000] * 390),
            move_5m_pct=tuple([0.10] * 390),
        )
        stamp = datetime(2026, 9, 18, 15, 55, 0, tzinfo=TZ)
        snapshot = StockSnapshot("SHOP", 147.39, 9_000_000, stamp, 144.55, 143, 150, 143)
        alert = evaluate(snapshot, profile, 1_000_000, -0.70, Thresholds(min_5m_dollar_volume=1))
        self.assertIsNotNone(alert)

    def test_same_ticker_realert_requires_price_displacement(self):
        stamp = datetime(2026, 9, 18, 10, 0, 0, tzinfo=TZ)
        snapshot = StockSnapshot("SHOP", 149, 9_000_000, stamp, 145, 143, 150, 143)
        profile = replace(
            self.profile,
            atr14=1.0,
            minute_volume=tuple([20_000] * 390),
            move_5m_pct=tuple([0.10] * 390),
        )
        alert = evaluate(snapshot, profile, 1_000_000, 1.0, Thresholds(min_5m_dollar_volume=1))
        self.assertIsNotNone(alert)
        with tempfile.TemporaryDirectory() as directory:
            state = AlertState(f"{directory}/alerts.json")
            state.mark(alert)
            nearby = replace(alert, snapshot=replace(snapshot, price=149.75, timestamp=stamp + timedelta(minutes=20)))
            displaced = replace(alert, snapshot=replace(snapshot, price=150.55, timestamp=stamp + timedelta(minutes=20)))
            self.assertFalse(state.should_send(nearby, 600, 1.0))
            self.assertTrue(state.should_send(displaced, 600, 1.0))

    def test_fresh_fast_move_qualifies_after_open(self):
        stamp = datetime(2026, 9, 18, 9, 44, 30, tzinfo=TZ)
        snapshot = StockSnapshot("COIN", 307, 5_000_000, stamp, 300, 299, 308, 299)
        alert = evaluate(snapshot, self.profile, 1_000_000, 1.0, Thresholds(min_5m_dollar_volume=1))
        self.assertIsNotNone(alert)

    def test_discord_payload_is_tight(self):
        stamp = datetime(2026, 9, 18, 9, 34, 59, tzinfo=TZ)
        normal = self.profile.expected_cumulative(4, 59 / 60)
        snapshot = StockSnapshot("COIN", 307, int(normal * 3), stamp, 300, 299, 308, 299)
        alert = evaluate(snapshot, self.profile, 1_500_000, 1.0, Thresholds(min_5m_dollar_volume=1))
        payload = DiscordNotifier("").payload(alert)
        names = {item["name"] for item in payload["embeds"][0]["fields"]}
        self.assertEqual(names, {"Price", "Time-of-Day RVOL", "ATR Progress"})

    def test_directional_expansion_does_not_require_high_local_rvol(self):
        stamp = datetime(2026, 9, 23, 9, 57, tzinfo=TZ)
        snapshot = StockSnapshot("MRNA", 190.62, 2_000_000, stamp, 183.405, 182, 191.88, 182.6)
        profile = replace(self.profile, atr14=11.35, minute_volume=tuple([30_000] * 390))
        features = MovementFeatures(
            150_000, 0.23, 1.04, 2.79, 0.04, 0.18, 0.47,
            0.72, 0.78, 4, 0.75, 186.0, True, False, 60, True,
        )
        alerts = evaluate_lanes(snapshot, profile, features, Thresholds(min_5m_dollar_volume=1))
        directional = [item for item in alerts if item.lane == "DIRECTIONAL_EXPANSION"]
        self.assertEqual(len(directional), 1)
        self.assertTrue(directional[0].confirmation_ready)

    def test_opening_directional_expansion_does_not_require_rvol(self):
        stamp = datetime(2026, 9, 24, 9, 37, 59, tzinfo=TZ)
        snapshot = StockSnapshot("INTC", 123.13, 1_000_000, stamp, 120.61, 122.60, 123.20, 119.55)
        profile = replace(self.profile, atr14=6.70, minute_volume=tuple([150_000] * 390))
        features = MovementFeatures(
            500_000, 1.55, None, None, 0.28, None, None,
            0.90, None, 4, 0.80, 121.5, True, False, 30, True,
        )

        alerts = evaluate_lanes(snapshot, profile, features, Thresholds(min_5m_dollar_volume=1))

        directional = [item for item in alerts if item.lane == "DIRECTIONAL_EXPANSION"]
        self.assertEqual(len(directional), 1)
        self.assertTrue(directional[0].confirmation_ready)

    def test_opening_directional_bars_use_available_five_minute_path(self):
        profile = replace(self.profile, atr14=6.70)
        rolling = RollingStockState()
        start = datetime(2026, 9, 24, 9, 30, 59, tzinfo=TZ)
        prices = [120.16, 121.14, 121.25, 121.50, 121.80]
        for offset, price in enumerate(prices):
            rolling.record(StockSnapshot(
                "INTC", price, 1_000_000 + offset * 100_000,
                start + timedelta(minutes=offset), 120.61, 122.60, price, 119.55,
            ))
        snapshot = StockSnapshot(
            "INTC", 122.17, 1_500_000, start + timedelta(minutes=5),
            120.61, 122.60, 122.20, 119.55,
        )

        features = rolling.features(snapshot, profile)

        self.assertGreaterEqual(features.directional_bars, 3)
        self.assertGreaterEqual(features.directional_share or 0, 0.75)

    def test_directional_chop_is_rejected(self):
        stamp = datetime(2026, 9, 23, 11, 30, tzinfo=TZ)
        snapshot = StockSnapshot("SHOP", 149.04, 9_000_000, stamp, 144.55, 143, 150, 143)
        features = MovementFeatures(
            1_000_000, 0.7, 1.1, 1.4, 0.16, 0.25, 0.32,
            0.25, 0.30, 1, 0.50, 148.5, True, False, 4_000, False,
        )
        alerts = evaluate_lanes(snapshot, replace(self.profile, atr14=6.32), features, Thresholds(min_5m_dollar_volume=1))
        self.assertFalse([item for item in alerts if item.lane == "DIRECTIONAL_EXPANSION"])

    def test_candidate_confirms_once_and_does_not_repeat(self):
        stamp = datetime(2026, 9, 23, 9, 44, tzinfo=TZ)
        snapshot = StockSnapshot("META", 761, 2_000_000, stamp, 747, 740, 762, 739)
        alert = evaluate(snapshot, replace(self.profile, atr14=10), 500_000, 1.0, Thresholds(min_5m_dollar_volume=1))
        alert = replace(alert, lane="DIRECTIONAL_EXPANSION", score=90, confirmation_ready=True)
        features = MovementFeatures(500_000, 1, 2, 3, .2, .3, .4, .8, .8, 4, .8, 755, True, True, 30, True)
        with tempfile.TemporaryDirectory() as directory:
            book = CandidateBook(f"{directory}/candidates.json")
            thresholds = Thresholds(candidate_confirm_seconds=120)
            self.assertEqual(book.observe(snapshot, [alert], features, 10, thresholds), [])
            middle_snapshot = replace(snapshot, timestamp=stamp + timedelta(seconds=60), price=762)
            middle_alert = replace(alert, snapshot=middle_snapshot)
            self.assertEqual(book.observe(middle_snapshot, [middle_alert], features, 10, thresholds), [])
            later_snapshot = replace(snapshot, timestamp=stamp + timedelta(seconds=120), price=763)
            later_alert = replace(alert, snapshot=later_snapshot)
            ready = book.observe(later_snapshot, [later_alert], features, 10, thresholds)
            self.assertEqual(len(ready), 1)
            book.mark_alerted(ready[0])
            self.assertEqual(book.observe(replace(later_snapshot, timestamp=stamp + timedelta(seconds=180)), [later_alert], features, 10, thresholds), [])

    def test_active_candidate_realerts_after_consolidation_breakout(self):
        stamp = datetime(2026, 9, 24, 9, 33, tzinfo=TZ)
        profile = replace(
            self.profile,
            atr14=15.6,
            minute_volume=tuple([20_000] * 390),
            move_5m_pct=tuple([0.10] * 390),
        )
        snapshot = StockSnapshot("NBIS", 240, 5_000_000, stamp, 230, 226, 240, 229)
        alert = evaluate(snapshot, profile, 1_000_000, 2.0, Thresholds(min_5m_dollar_volume=1))
        self.assertIsNotNone(alert)
        alert = replace(alert, lane="DIRECTIONAL_EXPANSION", score=100, confirmation_ready=True)
        moving = MovementFeatures(1_000_000, 2, 3, 4, .3, .4, .5, .8, .8, 4, .8, 238, True, True, 30, True)
        pullback = replace(moving, move_5m_atr=.10, fresh_level_break=False)
        thresholds = Thresholds(candidate_confirm_seconds=0, consolidation_retrace_atr=.15, rearm_break_atr=.10)

        with tempfile.TemporaryDirectory() as directory:
            book = CandidateBook(f"{directory}/candidates.json")
            book.observe(snapshot, [alert], moving, profile.atr14, thresholds)
            ready = book.observe(replace(snapshot, timestamp=stamp + timedelta(seconds=30)), [alert], moving, profile.atr14, thresholds)
            book.mark_alerted(ready[0])
            book.observe(replace(snapshot, price=242, timestamp=stamp + timedelta(minutes=1)), [], moving, profile.atr14, thresholds)
            book.observe(replace(snapshot, price=238.5, timestamp=stamp + timedelta(minutes=2)), [], pullback, profile.atr14, thresholds)
            breakout_snapshot = replace(snapshot, price=244, timestamp=stamp + timedelta(minutes=3))
            breakout_alert = replace(alert, snapshot=breakout_snapshot)

            breakout = book.observe(breakout_snapshot, [breakout_alert], moving, profile.atr14, thresholds)

            self.assertEqual(len(breakout), 1)
            self.assertEqual(breakout[0].snapshot.price, 244)

    def test_elevated_tod_rvol_bootstraps_transitioning_mover(self):
        scanner = VolumeScanner.__new__(VolumeScanner)
        scanner.settings = Settings()
        scanner.client = Mock()
        scanner.rolling = RollingStockState()
        scanner.bootstrapped = set()
        stamp = datetime(2026, 9, 18, 10, 12, 30, tzinfo=TZ)
        profile = replace(
            self.profile,
            atr14=27.0,
            minute_volume=tuple([100_000] * 390),
        )
        snapshot = StockSnapshot(
            "META", 750, 9_000_000, stamp, 747.6, 736.6, 764, 739,
        )
        scanner.client.price_history.return_value = [
            Candle(stamp - timedelta(minutes=15), 751, 752, 750, 751, 200_000),
            Candle(stamp - timedelta(minutes=14), 751, 752, 749, 750, 180_000),
        ]

        scanner.bootstrap_mover(snapshot, profile)

        scanner.client.price_history.assert_called_once_with("META", calendar_days=2)
        self.assertIn("META", scanner.bootstrapped)
        self.assertEqual(len(scanner.rolling.snapshots["META"]), 2)

    def test_inactive_symbol_can_be_reconsidered_for_bootstrap(self):
        scanner = VolumeScanner.__new__(VolumeScanner)
        scanner.settings = Settings()
        scanner.client = Mock()
        scanner.rolling = RollingStockState()
        scanner.bootstrapped = set()
        stamp = datetime(2026, 9, 18, 10, 12, 30, tzinfo=TZ)
        profile = replace(self.profile, atr14=27.0, minute_volume=tuple([100_000] * 390))
        quiet = StockSnapshot("META", 748, 1_000_000, stamp, 747.6, 736.6, 750, 746)
        active = replace(quiet, price=741, volume=9_000_000, timestamp=stamp + timedelta(seconds=30), low_price=740)
        scanner.client.price_history.return_value = [
            Candle(stamp - timedelta(minutes=15), 751, 752, 750, 751, 200_000),
        ]

        scanner.bootstrap_mover(quiet, profile)
        scanner.bootstrap_mover(active, profile)

        scanner.client.price_history.assert_called_once_with("META", calendar_days=2)
        self.assertIn("META", scanner.bootstrapped)


if __name__ == "__main__":
    unittest.main()
