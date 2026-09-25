import json
import os
from collections import defaultdict, deque
from datetime import datetime

from .config import Thresholds
from .models import MovementFeatures, StockSnapshot, VolumeAlert, VolumeProfile


class RollingStockState:
    def __init__(self, max_age_seconds: int = 25_200):
        self.max_age_seconds = max_age_seconds
        self.snapshots = defaultdict(deque)

    def record(self, snapshot: StockSnapshot) -> None:
        queue = self.snapshots[snapshot.symbol]
        if queue and queue[-1].timestamp.date() != snapshot.timestamp.date():
            queue.clear()
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
        if not eligible:
            return None
        baseline = eligible[-1]
        age = snapshot.timestamp.timestamp() - baseline.timestamp.timestamp()
        return baseline if age <= seconds + 120 else None

    def features(self, snapshot: StockSnapshot, profile: VolumeProfile) -> MovementFeatures:
        history = list(self.snapshots.get(snapshot.symbol, ()))
        if history and history[-1].timestamp == snapshot.timestamp:
            history[-1] = snapshot
        else:
            history.append(snapshot)
        history = [item for item in history if item.timestamp.date() == snapshot.timestamp.date()]
        change_5m = window_change(history, 300)
        change_10m = window_change(history, 600)
        change_15m = window_change(history, 900)
        direction = sign(change_5m if change_5m not in (None, 0) else change_10m)
        bars, share = directional_path(history, direction, 600)
        if share is None:
            bars, share = directional_path(history, direction, 300)
        vwap, prior_vwap, prior_price = observed_vwap(history)
        aligned = bool(vwap is not None and direction and direction * (snapshot.price - vwap) > 0)
        crossed = bool(aligned and prior_vwap is not None and prior_price is not None and direction * (prior_price - prior_vwap) <= 0)
        return MovementFeatures(
            window_volume(history, 300), change_5m, change_10m, change_15m,
            atr_displacement(snapshot.price, change_5m, profile.atr14),
            atr_displacement(snapshot.price, change_10m, profile.atr14),
            atr_displacement(snapshot.price, change_15m, profile.atr14),
            path_efficiency(history, 300), path_efficiency(history, 600),
            bars, share, vwap, aligned, crossed,
            new_extreme_age(history, snapshot, direction),
            fresh_level_break(history, snapshot, direction),
        )


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


class CandidateBook:
    def __init__(self, path: str):
        self.path = path
        self.records: dict[str, dict] = {}
        self.dirty = False
        if os.path.exists(path):
            try:
                with open(path, "r") as handle:
                    self.records = json.load(handle)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                self.records = {}

    def observe(self, snapshot: StockSnapshot, proposals: list[VolumeAlert], features: MovementFeatures,
                atr: float, thresholds: Thresholds) -> list[VolumeAlert]:
        symbol = snapshot.symbol
        now = snapshot.timestamp.timestamp()
        record = self.records.get(symbol)
        if record and record.get("day") != snapshot.timestamp.date().isoformat():
            self.records.pop(symbol, None)
            self.dirty = True
            record = None
        best = max(proposals, key=lambda item: item.score, default=None)
        if record is None:
            if best:
                self._arm(best)
                return [best] if mature_directional(best, thresholds) else []
            return []
        if record.get("status") == "ARMED":
            armed_at = float(record.get("armed_at", 0))
            if now - armed_at > thresholds.candidate_expiry_seconds:
                self.records.pop(symbol, None)
                self.dirty = True
                if best:
                    self._arm(best)
                    return [best] if mature_directional(best, thresholds) else []
                return []
            if not best:
                return []
            if best.direction != record.get("direction"):
                self._arm(best)
                return []
            if now - float(record.get("last_seen_at", armed_at)) > 90:
                self._arm(best)
                return []
            record.update({"last_seen_at": now, "lane": best.lane, "last_price": snapshot.price})
            self.dirty = True
            confirmed = now - armed_at >= thresholds.candidate_confirm_seconds and best.confirmation_ready
            return [best] if confirmed or mature_directional(best, thresholds) else []

        direction = 1 if record.get("direction") == "BULLISH" else -1
        prior_extreme = float(record.get("active_extreme", snapshot.price))
        record["last_price"] = snapshot.price
        record["active_extreme"] = max(prior_extreme, snapshot.price) if direction > 0 else min(prior_extreme, snapshot.price)
        self.dirty = True
        opposite = best if best and best.direction != record.get("direction") else None
        if opposite and atr > 0 and direction * (prior_extreme - snapshot.price) / atr >= thresholds.reversal_rearm_atr:
            self._arm(opposite)
            return []
        retrace_atr = direction * (prior_extreme - snapshot.price) / atr if atr > 0 else 0
        quiet = features.move_5m_atr is not None and features.move_5m_atr < thresholds.min_directional_5m_atr * 0.5
        if retrace_atr >= thresholds.consolidation_retrace_atr or quiet:
            if not record.get("consolidated_at"):
                record["consolidated_at"] = now
                record["rearm_level"] = prior_extreme
        same = best if best and best.direction == record.get("direction") else None
        rearm_level = float(record.get("rearm_level", prior_extreme))
        break_atr = direction * (snapshot.price - rearm_level) / atr if atr > 0 else 0
        strong_fresh_break = bool(
            same and same.confirmation_ready and features.fresh_level_break
            and break_atr >= thresholds.rearm_break_atr * 0.4
        )
        if record.get("consolidated_at") and same and (
            break_atr >= thresholds.rearm_break_atr or strong_fresh_break
        ):
            self._arm(same)
            return [same] if same.confirmation_ready else []
        return []

    def mark_alerted(self, alert: VolumeAlert) -> None:
        record = self.records.get(alert.snapshot.symbol)
        if record and record.get("status") == "ARMED":
            record.update({"status": "ACTIVE", "alerted_at": alert.snapshot.timestamp.timestamp(),
                           "active_extreme": alert.snapshot.price, "last_price": alert.snapshot.price,
                           "consolidated_at": None})
            self.dirty = True

    def save(self) -> None:
        if not self.dirty:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temporary = f"{self.path}.{os.getpid()}.tmp"
        with open(temporary, "w") as handle:
            json.dump(self.records, handle, indent=2, sort_keys=True)
        os.replace(temporary, self.path)
        self.dirty = False

    def _arm(self, alert: VolumeAlert) -> None:
        timestamp = alert.snapshot.timestamp.timestamp()
        self.records[alert.snapshot.symbol] = {
            "day": alert.snapshot.timestamp.date().isoformat(), "status": "ARMED",
            "direction": alert.direction, "lane": alert.lane, "armed_at": timestamp,
            "last_seen_at": timestamp, "arm_price": alert.snapshot.price, "last_price": alert.snapshot.price,
        }
        self.dirty = True


def severity_rank(value: str) -> int:
    return {"WATCH": 1, "IN PLAY": 2, "HIGH": 3, "EXTREME": 4}.get(value, 0)


def mature_directional(alert: VolumeAlert, thresholds: Thresholds) -> bool:
    return bool(
        alert.lane == "DIRECTIONAL_EXPANSION"
        and alert.confirmation_ready
        and alert.directional_bars >= max(6, thresholds.min_directional_bars * 2)
    )


def window_change(history: list[StockSnapshot], seconds: int) -> float | None:
    baseline = window_baseline(history, seconds)
    if baseline is None or baseline.price <= 0:
        return None
    return (history[-1].price - baseline.price) / baseline.price * 100


def window_volume(history: list[StockSnapshot], seconds: int) -> int | None:
    baseline = window_baseline(history, seconds)
    return None if baseline is None else max(history[-1].volume - baseline.volume, 0)


def window_baseline(history: list[StockSnapshot], seconds: int) -> StockSnapshot | None:
    if len(history) < 2:
        return None
    target = history[-1].timestamp.timestamp() - seconds
    eligible = [item for item in history[:-1] if item.timestamp.timestamp() <= target]
    if not eligible:
        return None
    baseline = eligible[-1]
    age = history[-1].timestamp.timestamp() - baseline.timestamp.timestamp()
    return baseline if age <= seconds + 120 else None


def window_points(history: list[StockSnapshot], seconds: int) -> list[StockSnapshot]:
    baseline = window_baseline(history, seconds)
    if baseline is None:
        return []
    return [baseline] + [item for item in history if item.timestamp > baseline.timestamp]


def path_efficiency(history: list[StockSnapshot], seconds: int) -> float | None:
    points = window_points(history, seconds)
    if len(points) < 3:
        return None
    path = sum(abs(right.price - left.price) for left, right in zip(points, points[1:]))
    return abs(points[-1].price - points[0].price) / path if path > 0 else 0.0


def directional_path(history: list[StockSnapshot], direction: int, seconds: int) -> tuple[int, float | None]:
    by_minute: dict[datetime, StockSnapshot] = {}
    for item in window_points(history, seconds):
        by_minute[item.timestamp.replace(second=0, microsecond=0)] = item
    closes = [item.price for _, item in sorted(by_minute.items())]
    moves = [right - left for left, right in zip(closes, closes[1:]) if right != left]
    if not moves or direction == 0:
        return 0, None
    aligned = [direction * move > 0 for move in moves]
    consecutive = 0
    for value in reversed(aligned):
        if not value:
            break
        consecutive += 1
    return consecutive, sum(aligned) / len(aligned)


def observed_vwap(history: list[StockSnapshot]) -> tuple[float | None, float | None, float | None]:
    weighted = 0.0
    volume = 0
    checkpoints: list[tuple[datetime, float, float]] = []
    for previous, current in zip(history, history[1:]):
        increment = current.volume - previous.volume
        if increment <= 0:
            continue
        weighted += current.price * increment
        volume += increment
        checkpoints.append((current.timestamp, weighted / volume, current.price))
    if len(checkpoints) < 3:
        return None, None, None
    cutoff = history[-1].timestamp.timestamp() - 120
    earlier = [item for item in checkpoints if item[0].timestamp() <= cutoff]
    prior = earlier[-1] if earlier else None
    return checkpoints[-1][1], prior[1] if prior else None, prior[2] if prior else None


def new_extreme_age(history: list[StockSnapshot], snapshot: StockSnapshot, direction: int) -> float | None:
    target = snapshot.high_price if direction > 0 else snapshot.low_price
    if target is None or direction == 0:
        return None
    tolerance = max(0.01, abs(target) * 0.00001)
    matches = [item for item in history if (
        (item.high_price if direction > 0 else item.low_price) is not None
        and abs((item.high_price if direction > 0 else item.low_price) - target) <= tolerance
    )]
    return snapshot.timestamp.timestamp() - matches[0].timestamp.timestamp() if matches else None


def fresh_level_break(history: list[StockSnapshot], snapshot: StockSnapshot, direction: int) -> bool:
    cutoff = snapshot.timestamp.timestamp() - 60
    prior = [item.price for item in history[:-1] if item.timestamp.timestamp() <= cutoff]
    if not prior or direction == 0:
        return False
    buffer = max(0.01, snapshot.price * 0.0002)
    return snapshot.price >= max(prior) + buffer if direction > 0 else snapshot.price <= min(prior) - buffer


def atr_displacement(price: float, change_pct: float | None, atr: float) -> float | None:
    if change_pct is None or atr <= 0 or change_pct <= -100:
        return None
    baseline = price / (1 + change_pct / 100)
    return abs(price - baseline) / atr


def sign(value: float | None) -> int:
    return 0 if value in (None, 0) else (1 if value > 0 else -1)
