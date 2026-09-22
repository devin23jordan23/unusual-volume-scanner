import logging
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .auth_server import start_auth_server
from .config import Settings
from .discord import DiscordNotifier
from .market_hours import is_market_open
from .profiles import ProfileCache, build_profile
from .rules import evaluate
from .schwab import SchwabClient
from .state import AlertState, RollingStockState, severity_rank

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

    def run(self) -> None:
        LOG.info("volume scanner started universe=%s", ",".join(sorted(self.settings.universe)))
        while True:
            try:
                if is_market_open(self.settings.timezone):
                    self.run_once()
                else:
                    LOG.info("market closed; waiting")
            except Exception:
                LOG.exception("volume scan failed")
            time.sleep(self.settings.poll_seconds if is_market_open(self.settings.timezone) else min(self.settings.poll_seconds * 5, 300))

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
            volume_5m, price_5m = self.rolling.metrics(snapshot)
            self.rolling.record(snapshot)
            alert = evaluate(snapshot, profile, volume_5m, price_5m, self.settings.thresholds)
            if alert and self.alerts.should_send(
                alert,
                self.settings.thresholds.cooldown_seconds,
                self.settings.thresholds.realert_min_price_change_pct,
            ):
                candidates.append(alert)

        ranked = sorted(
            candidates,
            key=lambda alert: (severity_rank(alert.severity.value), alert.tod_rvol, alert.local_rvol or 0),
            reverse=True,
        )
        if ranked:
            LOG.info(
                "qualified candidates=%s",
                ",".join(
                    f"{alert.snapshot.symbol}:{alert.tod_rvol:.2f}x/"
                    f"{alert.price_change_5m_pct or 0:+.2f}%/"
                    f"{alert.speed_ratio or 0:.2f}speed"
                    for alert in ranked
                ),
            )
        ranked = ranked[:self.settings.max_alerts_per_scan]
        if ranked and not self.alerts.notification_ready(
            ranked[0].snapshot.timestamp,
            self.settings.min_alert_interval_seconds,
        ):
            LOG.info("alert throttled symbol=%s", ranked[0].snapshot.symbol)
            ranked = []
        for alert in ranked:
            if self.notifier.send(alert):
                self.alerts.mark(alert)
        LOG.info("scan complete snapshots=%s qualified=%s sent=%s", len(snapshots), len(candidates), len(ranked))

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
