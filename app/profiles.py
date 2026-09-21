import json
import os
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, time
from statistics import fmean

from .models import Candle, VolumeProfile

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
    return VolumeProfile(
        symbol,
        len(selected_days),
        tuple(minute_volume),
        tuple(moves),
        atr14,
        selected_days[-1].isoformat(),
        today.isoformat(),
    )


def minute_index(timestamp: datetime) -> int | None:
    local = timestamp.timetz().replace(tzinfo=None)
    if local < time(9, 30) or local >= time(16, 0):
        return None
    return (timestamp.hour * 60 + timestamp.minute) - (9 * 60 + 30)


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
