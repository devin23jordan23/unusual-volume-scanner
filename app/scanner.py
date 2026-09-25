import logging
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .auth_server import start_auth_server
from .config import Settings
from .discord import DiscordNotifier
from .market_hours import is_market_open, is_premarket
from .models import StockSnapshot
from .profiles import ProfileCache, build_profile, minute_index
from .rules import evaluate_lanes
from .schwab import SchwabClient
from .state import AlertState, CandidateBook, RollingStockState, severity_rank

LOG = logging.getLogger(__name__)


class VolumeScanner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = SchwabClient(settings)
        start_auth_server(self.client)
        self.notifier = DiscordNotifier(settings.discord_webhook)
        self.profiles = ProfileCache(os.path.join(settings.data_dir, "volume_profiles.json"))
        self.rolling = RollingStockState()
        self.alerts = AlertState(os.path.join(settings.data_dir, "volume_alert_state.json"))
        self.candidates = CandidateBook(os.path.join(settings.data_dir, "volume_candidate_state.json"))
        self.bootstrapped: set[str] = set()
        self.prewarmed_on = None

    def run(self) -> None:
        LOG.info("volume scanner started universe=%s", ",".join(sorted(self.settings.universe)))
        while True:
            try:
                if is_market_open(self.settings.timezone):
                    self.run_once()
                elif is_premarket(self.settings.timezone):
                    self.prewarm_profiles()
                else:
                    LOG.info("market closed; waiting")
            except Exception:
                LOG.exception("volume scan failed")
            active_soon = is_market_open(self.settings.timezone) or is_premarket(self.settings.timezone)
            time.sleep(self.settings.poll_seconds if active_soon else min(self.settings.poll_seconds * 5, 300))

    def prewarm_profiles(self) -> None:
        today = datetime.now(ZoneInfo(self.settings.timezone)).date()
        if self.prewarmed_on == today:
            return
        self.prewarmed_on = today
        refreshed = 0
        for symbol in sorted(self.settings.universe):
            if self.profiles.fresh(symbol, today):
                continue
            profile = self.refresh_profile(symbol, today)
            if profile and self.profiles.fresh(symbol, today):
                refreshed += 1
        LOG.info("premarket profile warm-up complete refreshed=%s universe=%s", refreshed, len(self.settings.universe))

    def run_once(self) -> None:
        today = datetime.now(ZoneInfo(self.settings.timezone)).date()
        snapshots = self.client.stock_snapshots(sorted(self.settings.universe))
        candidates = []
        for snapshot in snapshots:
            profile = self.profiles.profiles.get(snapshot.symbol)
            if not profile or not self.profiles.fresh(snapshot.symbol, today):
                profile = self.refresh_profile(snapshot.symbol, today)
            if not profile:
                continue
            self.bootstrap_mover(snapshot, profile)
            features = self.rolling.features(snapshot, profile)
            proposals = evaluate_lanes(snapshot, profile, features, self.settings.thresholds)
            confirmed = self.candidates.observe(
                snapshot, proposals, features, profile.atr14, self.settings.thresholds,
            )
            self.rolling.record(snapshot)
            candidates.extend(confirmed)

        ranked = sorted(
            candidates,
            key=lambda alert: (alert.score, severity_rank(alert.severity.value), alert.tod_rvol),
            reverse=True,
        )
        if ranked:
            LOG.info(
                "qualified candidates=%s",
                ",".join(
                    f"{alert.snapshot.symbol}:{alert.lane}/{alert.score:.0f}/"
                    f"{alert.tod_rvol:.2f}x/"
                    f"{alert.price_change_5m_pct or 0:+.2f}%/"
                    f"{alert.speed_ratio or 0:.2f}speed"
                    for alert in ranked
                ),
            )
        if self.settings.max_alerts_per_scan > 0:
            ranked = ranked[:self.settings.max_alerts_per_scan]
        for alert in ranked:
            if self.notifier.send(alert):
                self.alerts.mark(alert)
                self.candidates.mark_alerted(alert)
        self.candidates.save()
        LOG.info("scan complete snapshots=%s qualified=%s sent=%s", len(snapshots), len(candidates), len(ranked))

    def bootstrap_mover(self, snapshot: StockSnapshot, profile) -> None:
        if snapshot.symbol in self.bootstrapped:
            return
        history = self.rolling.snapshots.get(snapshot.symbol)
        if history and snapshot.timestamp.timestamp() - history[0].timestamp.timestamp() >= 900:
            self.bootstrapped.add(snapshot.symbol)
            return
        if profile.atr14 <= 0 or snapshot.open_price is None:
            return
        displacement = abs(snapshot.price - snapshot.open_price) / profile.atr14
        range_atr = 0.0
        if snapshot.high_price is not None and snapshot.low_price is not None:
            range_atr = (snapshot.high_price - snapshot.low_price) / profile.atr14
        edge = snapshot.range_position
        at_edge = edge is not None and (edge >= 0.75 or edge <= 0.25)
        idx = minute_index(snapshot.timestamp)
        expected = profile.expected_cumulative(idx, max(snapshot.timestamp.second / 60, 0.10)) if idx is not None else 0
        tod_rvol = snapshot.volume / expected if expected > 0 else 0
        elevated_volume = tod_rvol >= self.settings.thresholds.min_tod_rvol
        if displacement < 0.25 and not (range_atr >= 0.50 and at_edge) and not elevated_volume:
            return
        try:
            candles = self.client.price_history(snapshot.symbol, calendar_days=2)
        except Exception as exc:
            LOG.warning("intraday bootstrap failed for %s: %s", snapshot.symbol, exc)
            return
        self.bootstrapped.add(snapshot.symbol)
        self.rolling.snapshots.pop(snapshot.symbol, None)
        cumulative = 0
        high = None
        low = None
        seeded = 0
        for candle in candles:
            if candle.timestamp.date() != snapshot.timestamp.date() or candle.timestamp >= snapshot.timestamp:
                continue
            cumulative += candle.volume
            high = candle.high if high is None else max(high, candle.high)
            low = candle.low if low is None else min(low, candle.low)
            self.rolling.record(StockSnapshot(
                snapshot.symbol, candle.close, cumulative, candle.timestamp,
                snapshot.open_price, snapshot.previous_close, high, low,
            ))
            seeded += 1
        if seeded:
            LOG.info("seeded intraday path symbol=%s bars=%s", snapshot.symbol, seeded)

    def refresh_profile(self, symbol: str, today) -> object | None:
        try:
            candles = self.client.price_history(symbol)
            profile = build_profile(symbol, candles, self.settings.profile_sessions, today)
            self.profiles.profiles[symbol] = profile
            self.profiles.save()
            LOG.info("profile refreshed symbol=%s sessions=%s as_of=%s", symbol, profile.sessions, profile.as_of)
            return profile
        except Exception as exc:
            LOG.warning("profile refresh failed for %s: %s", symbol, exc)
            return self.profiles.profiles.get(symbol)
