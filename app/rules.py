from dataclasses import replace

from .config import Thresholds
from .models import MovementFeatures, Severity, StockSnapshot, VolumeAlert, VolumeProfile
from .profiles import minute_index


def evaluate(
    snapshot: StockSnapshot,
    profile: VolumeProfile,
    volume_5m: int | None,
    price_change_5m_pct: float | None,
    thresholds: Thresholds,
) -> VolumeAlert | None:
    idx = minute_index(snapshot.timestamp)
    if idx is None or snapshot.price < thresholds.min_price or snapshot.price > thresholds.max_price:
        return None
    if snapshot.volume < thresholds.min_volume_today:
        return None

    fraction = max(snapshot.timestamp.second / 60, 0.10)
    expected_cumulative = profile.expected_cumulative(idx, fraction)
    if expected_cumulative <= 0:
        return None
    tod_rvol = snapshot.volume / expected_cumulative

    expected_5m = profile.expected_window(idx)
    local_rvol = volume_5m / expected_5m if volume_5m is not None and expected_5m > 0 else None
    normal_move = profile.normal_5m_move_pct(idx)
    speed_ratio = abs(price_change_5m_pct) / normal_move if price_change_5m_pct is not None and normal_move else None
    move_5m_atr = five_minute_atr_move(snapshot.price, price_change_5m_pct, profile.atr14)
    dollar_volume_5m = (volume_5m if volume_5m is not None else snapshot.volume) * snapshot.price
    atr_progress = ratio_to_atr(snapshot.price, snapshot.open_price, profile.atr14)
    day_range = None
    if snapshot.high_price is not None and snapshot.low_price is not None and profile.atr14 > 0:
        day_range = (snapshot.high_price - snapshot.low_price) / profile.atr14

    opening_volume_ok = tod_rvol >= thresholds.min_tod_rvol or (local_rvol or 0) >= thresholds.min_local_rvol
    fresh_volume_ok = (local_rvol or 0) >= thresholds.min_local_rvol
    opening_move_ok = (
        (atr_progress or 0) >= thresholds.min_atr_progress
        or (day_range or 0) >= thresholds.min_range_atr
    )
    fresh_move_ok = (
        abs(price_change_5m_pct or 0) >= thresholds.min_5m_move_pct
        and (speed_ratio or 0) >= thresholds.min_speed_ratio
        and (move_5m_atr or 0) >= thresholds.min_5m_atr_move
    )
    movement_ok = fresh_move_ok or (idx < 10 and opening_move_ok)
    volume_ok = opening_volume_ok if idx < 10 else fresh_volume_ok
    if not volume_ok or not movement_ok or dollar_volume_5m < thresholds.min_5m_dollar_volume:
        return None

    direction_value = direction(snapshot, price_change_5m_pct)
    setup = "OPENING DRIVE" if idx < 10 else "VOLUME IGNITION" if (local_rvol or 0) >= thresholds.min_local_rvol else "IN-PLAY CONTINUATION"
    reasons = [f"{tod_rvol:.2f}x time-of-day RVOL"]
    if local_rvol is not None and local_rvol >= thresholds.min_local_rvol:
        reasons.append(f"{local_rvol:.2f}x local 5m RVOL")
    if atr_progress is not None and atr_progress >= thresholds.min_atr_progress:
        reasons.append(f"{atr_progress:.2f} ATR from open")
    if speed_ratio is not None and speed_ratio >= thresholds.min_speed_ratio:
        reasons.append(f"{speed_ratio:.2f}x normal 5m price speed")
    if confirms_edge(snapshot, direction_value):
        reasons.append("pressing active side of day range")

    severity = classify(tod_rvol, local_rvol, atr_progress, speed_ratio, move_5m_atr, idx < 10, thresholds)
    return VolumeAlert(
        snapshot, severity, direction_value, setup, tuple(reasons), tod_rvol,
        local_rvol, volume_5m, dollar_volume_5m, price_change_5m_pct,
        speed_ratio, move_5m_atr, atr_progress, day_range,
    )


def evaluate_lanes(snapshot: StockSnapshot, profile: VolumeProfile, features: MovementFeatures,
                   thresholds: Thresholds) -> list[VolumeAlert]:
    proposals = []
    volume = evaluate(snapshot, profile, features.volume_5m, features.change_5m_pct, thresholds)
    if volume:
        idx = minute_index(snapshot.timestamp) or 0
        efficient = (features.efficiency_5m or 0) >= thresholds.min_directional_efficiency * 0.8
        persistent = features.directional_bars >= max(2, thresholds.min_directional_bars - 1)
        if idx < 10 or (efficient and persistent):
            score = volume_score(volume, features, thresholds)
            confirmation_ready = (
                confirms_edge(snapshot, volume.direction)
                and (volume.atr_progress or 0) >= thresholds.min_atr_progress
            ) if idx < 10 else efficient and persistent
            proposals.append(replace(
                volume,
                lane="VOLUME_IGNITION",
                score=score,
                confirmation_ready=confirmation_ready,
                efficiency=features.efficiency_5m,
                directional_bars=features.directional_bars,
                vwap=features.vwap,
            ))
    directional = evaluate_directional(snapshot, profile, features, thresholds)
    if directional:
        proposals.append(directional)
    return proposals


def evaluate_directional(snapshot: StockSnapshot, profile: VolumeProfile, features: MovementFeatures,
                         thresholds: Thresholds) -> VolumeAlert | None:
    idx = minute_index(snapshot.timestamp)
    if idx is None or snapshot.price < thresholds.min_price or snapshot.price > thresholds.max_price:
        return None
    direction_sign = signed_direction(features)
    if not direction_sign:
        return None
    direction_value = "BULLISH" if direction_sign > 0 else "BEARISH"
    opening = idx < 10
    opening_move_threshold = max(
        thresholds.min_directional_5m_atr * 1.5,
        thresholds.min_5m_atr_move,
    )
    horizon_ok = (
        (opening and (features.move_5m_atr or 0) >= opening_move_threshold)
        or (features.move_10m_atr or 0) >= thresholds.min_directional_10m_atr
        or (features.move_15m_atr or 0) >= thresholds.min_directional_15m_atr
    )
    efficiency = (features.efficiency_5m if opening else features.efficiency_10m) or 0
    persistent_trend = (
        not opening
        and (features.move_15m_atr or 0) >= thresholds.min_directional_15m_atr * 0.65
        and efficiency >= max(0.75, thresholds.min_directional_efficiency)
        and features.directional_bars >= max(6, thresholds.min_directional_bars * 2)
        and (features.directional_share or 0) >= 0.80
    )
    horizon_ok = horizon_ok or persistent_trend
    position = snapshot.range_position
    edge_ok = position is not None and (
        position >= thresholds.directional_edge_position if direction_sign > 0
        else position <= 1 - thresholds.directional_edge_position
    )
    fresh_edge = features.fresh_level_break or (
        features.new_extreme_age_seconds is not None
        and features.new_extreme_age_seconds <= thresholds.max_extreme_age_seconds
    )
    arm_bars = max(2, thresholds.min_directional_bars - 1)
    sustained_move = (features.move_15m_atr or 0) >= thresholds.min_directional_15m_atr
    fresh_impulse_threshold = opening_move_threshold if opening else thresholds.min_directional_5m_atr * 0.75
    fresh_impulse = (features.move_5m_atr or 0) >= fresh_impulse_threshold
    if not (
        (fresh_impulse or sustained_move or persistent_trend)
        and horizon_ok
        and efficiency >= thresholds.min_directional_efficiency * 0.85
        and features.directional_bars >= arm_bars
        and features.vwap_aligned
        and edge_ok
        and fresh_edge
    ):
        return None

    expected_cumulative = profile.expected_cumulative(idx, max(snapshot.timestamp.second / 60, 0.10))
    tod_rvol = snapshot.volume / expected_cumulative if expected_cumulative > 0 else 0
    expected_5m = profile.expected_window(idx)
    local_rvol = features.volume_5m / expected_5m if features.volume_5m is not None and expected_5m > 0 else None
    atr_progress = ratio_to_atr(snapshot.price, snapshot.open_price, profile.atr14)
    day_range = None
    if snapshot.high_price is not None and snapshot.low_price is not None and profile.atr14 > 0:
        day_range = (snapshot.high_price - snapshot.low_price) / profile.atr14
    speed = None
    normal_move = profile.normal_5m_move_pct(idx)
    if features.change_5m_pct is not None and normal_move:
        speed = abs(features.change_5m_pct) / normal_move
    score = directional_score(features, tod_rvol, local_rvol, thresholds)
    confirmation_ready = (
        ((features.move_5m_atr or 0) >= thresholds.min_directional_5m_atr or sustained_move or persistent_trend)
        and efficiency >= thresholds.min_directional_efficiency
        and features.directional_bars >= thresholds.min_directional_bars
        and (features.directional_share or 0) >= 0.65
    )
    severity = Severity.EXTREME if score >= 90 else Severity.HIGH if score >= 75 else Severity.IN_PLAY
    sustained_atr = max(features.move_10m_atr or 0, features.move_15m_atr or 0)
    reasons = (
        f"{features.move_5m_atr or 0:.2f} ATR in 5m",
        f"{sustained_atr:.2f} ATR sustained",
        f"{efficiency:.2f} directional efficiency",
        "fresh range break" if features.fresh_level_break else "pressing fresh daily extreme",
    )
    return VolumeAlert(
        snapshot, severity, direction_value, "DIRECTIONAL EXPANSION", reasons,
        tod_rvol, local_rvol, features.volume_5m,
        (features.volume_5m or 0) * snapshot.price,
        features.change_5m_pct, speed, features.move_5m_atr,
        atr_progress, day_range, "DIRECTIONAL_EXPANSION", score,
        confirmation_ready, efficiency, features.directional_bars, features.vwap,
    )


def signed_direction(features: MovementFeatures) -> int:
    value = features.change_5m_pct
    if value in (None, 0):
        value = features.change_10m_pct
    return 0 if value in (None, 0) else (1 if value > 0 else -1)


def volume_score(alert: VolumeAlert, features: MovementFeatures, thresholds: Thresholds) -> float:
    return min(100.0, 20 * min(alert.tod_rvol / thresholds.min_tod_rvol, 2)
               + 20 * min((alert.local_rvol or 0) / thresholds.min_local_rvol, 2)
               + 25 * min((alert.move_5m_atr or 0) / thresholds.min_5m_atr_move, 2)
               + 20 * (features.efficiency_5m or 0)
               + 5 * features.directional_bars)


def directional_score(features: MovementFeatures, tod_rvol: float, local_rvol: float | None,
                      thresholds: Thresholds) -> float:
    score = 20 * min((features.move_5m_atr or 0) / thresholds.min_directional_5m_atr, 2)
    score += 20 * min((features.move_10m_atr or 0) / thresholds.min_directional_10m_atr, 2)
    score += 15 * min((features.move_15m_atr or 0) / thresholds.min_directional_15m_atr, 2)
    score += 20 * (features.efficiency_10m or 0)
    score += 10 * (features.directional_share or 0)
    score += 5 if features.vwap_crossed else 3 if features.vwap_aligned else 0
    score += 5 if features.fresh_level_break else 0
    score += 5 * min(max(tod_rvol, local_rvol or 0) / thresholds.min_tod_rvol, 2)
    return min(100.0, score)


def ratio_to_atr(price: float, anchor: float | None, atr: float) -> float | None:
    if anchor is None or atr <= 0:
        return None
    return abs(price - anchor) / atr


def five_minute_atr_move(price: float, change_pct: float | None, atr: float) -> float | None:
    if change_pct is None or atr <= 0 or change_pct <= -100:
        return None
    baseline = price / (1 + change_pct / 100)
    return abs(price - baseline) / atr


def direction(snapshot: StockSnapshot, price_change_5m_pct: float | None) -> str:
    values = [snapshot.change_from_open_pct, snapshot.change_from_close_pct, price_change_5m_pct]
    return "BULLISH" if sum(value for value in values if value is not None) >= 0 else "BEARISH"


def confirms_edge(snapshot: StockSnapshot, move_direction: str) -> bool:
    position = snapshot.range_position
    if position is None:
        return False
    return position >= 0.75 if move_direction == "BULLISH" else position <= 0.25


def classify(
    tod: float,
    local: float | None,
    atr: float | None,
    speed: float | None,
    move_5m_atr: float | None,
    opening: bool,
    thresholds: Thresholds,
) -> Severity:
    extreme_move = (atr or 0) >= 0.5 if opening else (
        (speed or 0) >= 3 and (move_5m_atr or 0) >= thresholds.min_5m_atr_move * 1.25
    )
    if tod >= thresholds.extreme_tod_rvol and extreme_move:
        return Severity.EXTREME
    high_move = (atr or 0) >= 0.3 if opening else (local or 0) >= 3 and (speed or 0) >= 2
    if tod >= thresholds.high_tod_rvol and high_move:
        return Severity.HIGH
    if tod >= thresholds.min_tod_rvol:
        return Severity.IN_PLAY
    return Severity.WATCH
