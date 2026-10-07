import json
import os
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, time
from statistics import fmean

from .models import Candle, StockSnapshot, VolumeProfile

SESSION_MINUTES = 390


def build_profile(symbol: str, candles: list[Candle], sessions: int, today: date | None = None) -> VolumeProfile:
    today = today or datetime.now(candles[0].timestamp.tzinfo).date()
    grouped: dict[date, dict[int, Candle]] = defaultdict(dict)
    for candle in candles:
        day = candle.timestamp.date()
        idx = minute_index(candle.timestamp)
        if day < today and idx is not None:
            grouped[day][idx] = candle
    selected_days = sorted(grouped)[-sessions:]
    if not selected_days:
        raise ValueError(f"no completed regular sessions for {symbol}")

    minute_volume = []
    moves = []
    for idx in range(SESSION_MINUTES):
        volumes = [grouped[day][idx].volume for day in selected_days if idx in grouped[day]]
        minute_volume.append(fmean(volumes) if volumes else 0.0)
        move_samples = []
        for day in selected_days:
            current = grouped[day].get(idx)
            baseline = grouped[day].get(idx - 5)
            if current and baseline and baseline.close > 0:
                move_samples.append(abs(current.close - baseline.close) / baseline.close * 100)
        moves.append(fmean(move_samples) if move_samples else 0.0)

    daily = []
    for day in selected_days:
        bars = [grouped[day][idx] for idx in sorted(grouped[day])]
        if bars:
            daily.append((max(b.high for b in bars), min(b.low for b in bars), bars[-1].close))
    true_ranges = []
    for idx, (high, low, _) in enumerate(daily):
        previous_close = daily[idx - 1][2] if idx else None
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)) if previous_close else high - low)
    atr_sample = true_ranges[-14:]
    atr14 = fmean(atr_sample) if atr_sample else 0.0
    previous = daily[-1]
    five_day = daily[-5:]
    twenty_day = daily[-20:]
    return VolumeProfile(
        symbol,
        len(selected_days),
        tuple(minute_volume),
        tuple(moves),
        atr14,
        selected_days[-1].isoformat(),
        today.isoformat(),
        previous[0],
        previous[1],
        max(item[0] for item in five_day),
        min(item[1] for item in five_day),
        max(item[0] for item in twenty_day),
        min(item[1] for item in twenty_day),
    )


def minute_index(timestamp: datetime) -> int | None:
    local = timestamp.timetz().replace(tzinfo=None)
    if local < time(9, 30) or local >= time(16, 0):
        return None
    return (timestamp.hour * 60 + timestamp.minute) - (9 * 60 + 30)


def build_intraday_fallback_profile(snapshot: StockSnapshot) -> VolumeProfile:
    idx = minute_index(snapshot.timestamp) or 0
    fraction = max(snapshot.timestamp.second / 60, 0.10)
    elapsed_minutes = max(idx + fraction, 0.10)
    average_minute_volume = max(snapshot.volume / elapsed_minutes, 1.0)
    day_range = 0.0
    if snapshot.high_price is not None and snapshot.low_price is not None:
        day_range = max(snapshot.high_price - snapshot.low_price, 0.0)
    atr_proxy = max(snapshot.price * 0.03, day_range, 0.01)
    normal_move = max(0.35, atr_proxy / snapshot.price * 100 * 0.15)
    today = snapshot.timestamp.date().isoformat()
    return VolumeProfile(
        snapshot.symbol,
        0,
        tuple([average_minute_volume] * SESSION_MINUTES),
        tuple([normal_move] * SESSION_MINUTES),
        atr_proxy,
        "intraday-fallback",
        today,
    )


class ProfileCache:
    def __init__(self, path: str):
        self.path = path
        self.profiles: dict[str, VolumeProfile] = {}
        self.load()

    def load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r") as handle:
                raw = json.load(handle)
            for symbol, item in raw.items():
                item["minute_volume"] = tuple(item["minute_volume"])
                item["move_5m_pct"] = tuple(item["move_5m_pct"])
                self.profiles[symbol] = VolumeProfile(**item)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.profiles = {}

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as handle:
            json.dump({symbol: asdict(profile) for symbol, profile in self.profiles.items()}, handle)

    def fresh(self, symbol: str, today: date) -> bool:
        profile = self.profiles.get(symbol)
        return bool(profile and profile.generated_on == today.isoformat())
