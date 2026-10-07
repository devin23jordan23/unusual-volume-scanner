from dataclasses import replace
from datetime import date, time
from math import ceil, floor

from .models import Candle, MovementFeatures, VolumeAlert, VolumeProfile


def premarket_range(candles: list[Candle], today: date) -> tuple[float, float] | None:
    bars = [
        candle for candle in candles
        if candle.timestamp.date() == today
        and time(4, 0) <= candle.timestamp.timetz().replace(tzinfo=None) < time(9, 30)
    ]
    if not bars:
        return None
    return max(bar.high for bar in bars), min(bar.low for bar in bars)


def add_level_context(
    alert: VolumeAlert,
    profile: VolumeProfile,
    features: MovementFeatures,
    premarket: tuple[float, float] | None,
    prior_intraday_high: float | None,
    prior_intraday_low: float | None,
) -> VolumeAlert:
    direction = 1 if alert.direction == "BULLISH" else -1
    baseline = baseline_price(alert.snapshot.price, features.change_5m_pct)
    if baseline is None:
        baseline = alert.snapshot.open_price
    if baseline is None:
        return alert

    levels: list[tuple[int, int, str]] = []
    if direction > 0:
        add_cross(levels, baseline, alert.snapshot.price, profile.twenty_day_high, 1, 18, "20-Day High")
        add_cross(levels, baseline, alert.snapshot.price, profile.five_day_high, 1, 15, "5-Day High")
        add_cross(levels, baseline, alert.snapshot.price, profile.previous_day_high, 1, 20, "Previous-Day High")
        if premarket:
            add_cross(levels, baseline, alert.snapshot.price, premarket[0], 1, 20, "Premarket High")
        add_cross(levels, baseline, alert.snapshot.price, prior_intraday_high, 1, 10, "Intraday High")
    else:
        add_cross(levels, baseline, alert.snapshot.price, profile.twenty_day_low, -1, 18, "20-Day Low")
        add_cross(levels, baseline, alert.snapshot.price, profile.five_day_low, -1, 15, "5-Day Low")
        add_cross(levels, baseline, alert.snapshot.price, profile.previous_day_low, -1, 20, "Previous-Day Low")
        if premarket:
            add_cross(levels, baseline, alert.snapshot.price, premarket[1], -1, 20, "Premarket Low")
        add_cross(levels, baseline, alert.snapshot.price, prior_intraday_low, -1, 10, "Intraday Low")

    round_level = crossed_round_number(baseline, alert.snapshot.price, direction)
    if round_level is not None:
        major = is_major_round(round_level, alert.snapshot.price)
        levels.append((2 if major else 3, 6 if major else 3,
                       f"{'Major Round' if major else 'Whole-Dollar'} ${round_level:g}"))

    ranked = sorted(levels, key=lambda item: (item[0], -item[1]))
    if not ranked:
        return alert

    confluence_bonus = max(0, len(ranked) - 1) * 5
    labels = tuple(item[2] for item in ranked[:4])
    return replace(
        alert,
        reasons=alert.reasons + ("; ".join(labels),),
        score=alert.score + sum(item[1] for item in ranked) + confluence_bonus,
        crossed_levels=labels,
        level_tier=min(item[0] for item in ranked),
    )


def add_cross(
    output: list[tuple[int, int, str]],
    baseline: float,
    current: float,
    level: float | None,
    direction: int,
    boost: int,
    name: str,
) -> None:
    if level is None:
        return
    crossed = baseline < level <= current if direction > 0 else baseline > level >= current
    if crossed:
        output.append((1, boost, f"{name} ${level:.2f}"))


def baseline_price(price: float, change_pct: float | None) -> float | None:
    if change_pct is None or change_pct <= -100:
        return None
    return price / (1 + change_pct / 100)


def crossed_round_number(baseline: float, current: float, direction: int) -> float | None:
    low = ceil(min(baseline, current))
    high = floor(max(baseline, current))
    crossed = [float(level) for level in range(low, high + 1)]
    if not crossed:
        return None
    nearest_first = sorted(crossed, reverse=direction > 0)
    major = [level for level in nearest_first if is_major_round(level, current)]
    return major[0] if major else nearest_first[0]


def is_major_round(level: float, price: float) -> bool:
    increment = 25 if price >= 500 else 10 if price >= 100 else 5
    return level % increment == 0
