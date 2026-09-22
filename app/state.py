import json
import os
from collections import defaultdict, deque
from datetime import datetime

from .models import StockSnapshot, VolumeAlert


class RollingStockState:
    def __init__(self, max_age_seconds: int = 900):
        self.max_age_seconds = max_age_seconds
        self.snapshots = defaultdict(deque)

    def record(self, snapshot: StockSnapshot) -> None:
        queue = self.snapshots[snapshot.symbol]
        queue.append(snapshot)
        cutoff = snapshot.timestamp.timestamp() - self.max_age_seconds
        while queue and queue[0].timestamp.timestamp() < cutoff:
            queue.popleft()

    def metrics(self, snapshot: StockSnapshot, seconds: int = 300) -> tuple[int | None, float | None]:
        baseline = self._baseline(snapshot, seconds)
        if baseline is None:
            return None, None
        volume = max(snapshot.volume - baseline.volume, 0)
        price = None if baseline.price <= 0 else (snapshot.price - baseline.price) / baseline.price * 100
        return volume, price

    def _baseline(self, snapshot: StockSnapshot, seconds: int) -> StockSnapshot | None:
        queue = self.snapshots.get(snapshot.symbol)
        if not queue:
            return None
        cutoff = snapshot.timestamp.timestamp() - seconds
        eligible = [item for item in queue if item.timestamp.timestamp() <= cutoff]
        return eligible[-1] if eligible else None


class AlertState:
    def __init__(self, path: str):
        self.path = path
        self.sent: dict[str, dict] = {}
        if os.path.exists(path):
            try:
                with open(path, "r") as handle:
                    self.sent = json.load(handle)
            except (OSError, ValueError, json.JSONDecodeError):
                self.sent = {}

    def should_send(self, alert: VolumeAlert, cooldown_seconds: int, min_price_change_pct: float = 0) -> bool:
        last = self.sent.get(alert.snapshot.symbol)
        if not last:
            return True
        if severity_rank(alert.severity.value) > severity_rank(last.get("severity", "")):
            return True
        if alert.snapshot.timestamp.timestamp() - float(last.get("sent_at", 0)) < cooldown_seconds:
            return False
        last_price = float(last.get("price", 0) or 0)
        if last_price <= 0:
            return min_price_change_pct <= 0
        price_change = abs(alert.snapshot.price - last_price) / last_price * 100
        return price_change >= min_price_change_pct

    def notification_ready(self, timestamp: datetime, interval_seconds: int) -> bool:
        latest = max((float(item.get("sent_at", 0)) for item in self.sent.values()), default=0)
        return timestamp.timestamp() - latest >= interval_seconds

    def mark(self, alert: VolumeAlert) -> None:
        self.sent[alert.snapshot.symbol] = {
            "sent_at": alert.snapshot.timestamp.timestamp(),
            "severity": alert.severity.value,
            "price": alert.snapshot.price,
        }
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as handle:
            json.dump(self.sent, handle, indent=2)


def severity_rank(value: str) -> int:
    return {"WATCH": 1, "IN PLAY": 2, "HIGH": 3, "EXTREME": 4}.get(value, 0)
