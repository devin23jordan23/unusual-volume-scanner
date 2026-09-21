import logging
import time

from .models import VolumeAlert

LOG = logging.getLogger(__name__)


class DiscordNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, alert: VolumeAlert) -> bool:
        if not self.webhook_url:
            LOG.info("Discord webhook missing; alert skipped: %s", alert.snapshot.symbol)
            return False
        import requests

        for attempt in range(3):
            try:
                response = requests.post(self.webhook_url, json=self.payload(alert), timeout=10)
                response.raise_for_status()
                return True
            except Exception as exc:
                LOG.warning("Discord send failed attempt %s: %s", attempt + 1, exc)
                time.sleep(2 ** attempt)
        return False

    def payload(self, alert: VolumeAlert) -> dict:
        snapshot = alert.snapshot
        bullish = alert.direction == "BULLISH"
        color = 0xF1C40F if alert.severity.value == "EXTREME" else (0x2ECC71 if bullish else 0xE74C3C)
        fields = [
            field("Price", f"${snapshot.price:.2f}"),
            field("Time-of-Day RVOL", f"{alert.tod_rvol:.2f}x"),
            field("Local 5m RVOL", number(alert.local_rvol, "x")),
            field("Volume Today", f"{snapshot.volume:,}"),
            field("5m Dollar Volume", f"${alert.dollar_volume_5m:,.0f}"),
            field("Move from Open", percent(snapshot.change_from_open_pct)),
            field("ATR Progress", number(alert.atr_progress, " ATR")),
            field("5m Move", percent(alert.price_change_5m_pct)),
            field("5m Price Speed", number(alert.speed_ratio, "x")),
            {"name": "Why", "value": "; ".join(alert.reasons[:5]), "inline": False},
        ]
        return {
            "username": "Unusual Volume Scanner",
            "embeds": [{
                "title": f"{snapshot.symbol} - {alert.direction} {alert.setup}",
                "description": alert.severity.value,
                "color": color,
                "fields": fields,
                "footer": {"text": "Market-data alert only. Not a trade recommendation."},
                "timestamp": snapshot.timestamp.isoformat(),
            }],
        }


def field(name: str, value: str) -> dict:
    return {"name": name, "value": value, "inline": True}


def number(value: float | None, suffix: str) -> str:
    return "n/a" if value is None else f"{value:.2f}{suffix}"


def percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"
