import tempfile
import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import DEFAULT_UNIVERSE, Settings, Thresholds
from app.discord import DiscordNotifier
from app.models import Candle, Severity, StockSnapshot
from app.profiles import build_profile
from app.rules import evaluate
from app.state import AlertState

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

    def test_selected_bank_names_in_default_universe(self):
        self.assertTrue({"JPM", "BAC"}.issubset(DEFAULT_UNIVERSE))
        self.assertTrue({"C", "GS", "MS", "SCHW", "AXP"}.isdisjoint(DEFAULT_UNIVERSE))

    def test_global_notification_interval(self):
        stamp = datetime(2026, 9, 22, 10, 0, tzinfo=TZ)
        state = AlertState("/path/that/does/not/exist")
        interval = Settings().min_alert_interval_seconds
        self.assertEqual(interval, 300)
        self.assertTrue(state.notification_ready(stamp, interval))
        state.sent["COIN"] = {"sent_at": stamp.timestamp(), "severity": "HIGH"}
        self.assertFalse(state.notification_ready(stamp + timedelta(seconds=299), interval))
        self.assertTrue(state.notification_ready(stamp + timedelta(seconds=300), interval))

    def test_high_volume_without_movement_is_rejected(self):
        stamp = datetime(2026, 9, 18, 10, 0, 30, tzinfo=TZ)
        snapshot = StockSnapshot("COIN", 300.02, 5_000_000, stamp, 300, 300, 300.05, 299.95)
        alert = evaluate(snapshot, self.profile, 1_000_000, 0.01, Thresholds(min_5m_dollar_volume=1))
        self.assertIsNone(alert)

    def test_discord_payload_is_tight(self):
        stamp = datetime(2026, 9, 18, 9, 34, 59, tzinfo=TZ)
        normal = self.profile.expected_cumulative(4, 59 / 60)
        snapshot = StockSnapshot("COIN", 307, int(normal * 3), stamp, 300, 299, 308, 299)
        alert = evaluate(snapshot, self.profile, 1_500_000, 1.0, Thresholds(min_5m_dollar_volume=1))
        payload = DiscordNotifier("").payload(alert)
        names = {item["name"] for item in payload["embeds"][0]["fields"]}
        self.assertEqual(names, {"Price", "Time-of-Day RVOL", "ATR Progress"})


if __name__ == "__main__":
    unittest.main()
