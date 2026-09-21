from .config import Thresholds
from .models import Severity, StockSnapshot, VolumeAlert, VolumeProfile
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
    dollar_volume_5m = (volume_5m if volume_5m is not None else snapshot.volume) * snapshot.price
    atr_progress = ratio_to_atr(snapshot.price, snapshot.open_price, profile.atr14)
    day_range = None
    if snapshot.high_price is not None and snapshot.low_price is not None and profile.atr14 > 0:
        day_range = (snapshot.high_price - snapshot.low_price) / profile.atr14

    volume_ok = tod_rvol >= thresholds.min_tod_rvol or (local_rvol or 0) >= thresholds.min_local_rvol
    movement_ok = (
        (atr_progress or 0) >= thresholds.min_atr_progress
        or (day_range or 0) >= thresholds.min_range_atr
        or (
            abs(price_change_5m_pct or 0) >= thresholds.min_5m_move_pct
            and (speed_ratio or 0) >= thresholds.min_speed_ratio
        )
    )
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

    severity = classify(tod_rvol, local_rvol, atr_progress, speed_ratio, thresholds)
    return VolumeAlert(
        snapshot, severity, direction_value, setup, tuple(reasons), tod_rvol,
        local_rvol, volume_5m, dollar_volume_5m, price_change_5m_pct,
        speed_ratio, atr_progress, day_range,
    )


def ratio_to_atr(price: float, anchor: float | None, atr: float) -> float | None:
    if anchor is None or atr <= 0:
        return None
    return abs(price - anchor) / atr


def direction(snapshot: StockSnapshot, price_change_5m_pct: float | None) -> str:
    values = [snapshot.change_from_open_pct, snapshot.change_from_close_pct, price_change_5m_pct]
    return "BULLISH" if sum(value for value in values if value is not None) >= 0 else "BEARISH"


def confirms_edge(snapshot: StockSnapshot, move_direction: str) -> bool:
    position = snapshot.range_position
    if position is None:
        return False
    return position >= 0.75 if move_direction == "BULLISH" else position <= 0.25


def classify(tod: float, local: float | None, atr: float | None, speed: float | None, thresholds: Thresholds) -> Severity:
    if tod >= thresholds.extreme_tod_rvol and ((atr or 0) >= 0.5 or (speed or 0) >= 3):
        return Severity.EXTREME
    if tod >= thresholds.high_tod_rvol and ((atr or 0) >= 0.3 or (local or 0) >= 3):
        return Severity.HIGH
    if tod >= thresholds.min_tod_rvol:
        return Severity.IN_PLAY
    return Severity.WATCH

