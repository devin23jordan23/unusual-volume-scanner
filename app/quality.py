from dataclasses import dataclass

from .models import VolumeAlert
from .profiles import minute_index


ETF_SYMBOLS = {
    "DIA", "GLD", "ICLN", "IWM", "MTUM", "QQQ", "SLV", "SMH", "SOXX",
    "SPY", "TAN", "USO", "XLE", "XLF", "XLI", "XLK",
}


@dataclass(frozen=True)
class DeliveryDecision:
    actionable: bool
    reason: str


def delivery_decision(alert: VolumeAlert) -> DeliveryDecision:
    """Keep broad detection, but reserve Discord for actionable expansion."""
    move = abs(alert.price_change_5m_pct or 0)
    efficiency = alert.efficiency or 0
    speed = alert.speed_ratio or 0
    atr_move = alert.move_5m_atr or 0
    idx = minute_index(alert.snapshot.timestamp)
    midday = idx is not None and idx >= 120
    afternoon = idx is not None and idx >= 270
    is_etf = alert.snapshot.symbol in ETF_SYMBOLS
    absolute_floor = 0.25 if is_etf else 0.50
    efficient = efficiency >= 0.68
    direction = 1 if alert.direction == "BULLISH" else -1
    impulse_intact = alert.impulse_retention is None or alert.impulse_retention >= 0.75
    recent_change = direction * (alert.price_change_1m_pct or 0)
    recent_move_intact = alert.price_change_1m_pct is None or recent_change >= -0.08
    explosive = (
        move >= 0.75 and speed >= 2.5 and efficiency >= 0.70
        and impulse_intact and recent_move_intact
    )
    strong_atr_impulse = (
        atr_move >= 0.22 and move >= absolute_floor and efficiency >= 0.72
        and impulse_intact and recent_move_intact
    )
    institutional_level = alert.level_tier == 1
    sector_support = bool(
        alert.sector_context
        and "DIVERGENCE" not in alert.sector_context
        and ("LEADING" in alert.sector_context or "ALIGNED" in alert.sector_context)
    )
    clean_fast_expansion = bool(
        alert.lane == "DIRECTIONAL_EXPANSION"
        and move >= max(absolute_floor, 0.50)
        and atr_move >= 0.18
        and efficiency >= 0.78
        and alert.directional_bars >= 4
        and speed >= 2.0
        and impulse_intact
        and recent_move_intact
    )
    position = alert.snapshot.range_position
    at_active_edge = position is not None and (
        position >= 0.75 if direction > 0 else position <= 0.25
    )
    sustained_trend = bool(
        alert.lane == "DIRECTIONAL_EXPANSION"
        and at_active_edge
        and alert.directional_bars >= 4
        and (alert.directional_share or 0) >= 0.75
        and max(alert.efficiency_10m or 0, alert.efficiency_30m or 0) >= 0.72
        and (
            (alert.move_15m_atr or 0) >= 0.28
            or (alert.move_30m_atr or 0) >= 0.35
        )
        and atr_move >= 0.06
        and recent_move_intact
    )
    exceptional_afternoon_impulse = bool(
        explosive
        or clean_fast_expansion
        or sustained_trend
        or (
            strong_atr_impulse
            and move >= 0.75
            and (alert.local_rvol or 0) >= 3.0
        )
    )

    if move < absolute_floor and not strong_atr_impulse and not sustained_trend:
        return DeliveryDecision(False, "insufficient absolute 5m movement")
    if ((alert.local_rvol or 0) >= 5.0 and not explosive
            and not clean_fast_expansion and not sustained_trend):
        return DeliveryDecision(False, "extreme local volume lacks matching price expansion")
    if afternoon and not exceptional_afternoon_impulse:
        return DeliveryDecision(False, "afternoon move lacks fresh exceptional expansion")
    if (midday and not afternoon and not strong_atr_impulse
            and not clean_fast_expansion and not sustained_trend):
        return DeliveryDecision(False, "midday move lacks confirmed price expansion")
    if (alert.sector_context and "DIVERGENCE" in alert.sector_context
            and not institutional_level and not explosive and not sustained_trend):
        return DeliveryDecision(False, "sector divergence without exceptional movement")
    if (institutional_level and efficient and atr_move >= 0.18
            and move >= absolute_floor and speed >= 2.0
            and impulse_intact and recent_move_intact):
        return DeliveryDecision(True, "institutional level break with directional efficiency")
    if sustained_trend:
        return DeliveryDecision(True, "sustained directional trend at the active range edge")
    if (sector_support and efficient and speed >= 3.0
            and move >= max(absolute_floor, 0.50) and impulse_intact and recent_move_intact):
        return DeliveryDecision(True, "sector-confirmed fast directional expansion")
    if clean_fast_expansion:
        return DeliveryDecision(True, "clean fast directional expansion")
    if explosive or strong_atr_impulse:
        return DeliveryDecision(True, "exceptional self-relative price expansion")
    if (
        alert.setup == "OPENING DRIVE"
        and (alert.atr_progress or 0) >= 0.30
        and move >= max(absolute_floor, 0.50)
        and efficiency >= 0.60
        and impulse_intact
        and recent_move_intact
    ):
        return DeliveryDecision(True, "confirmed opening drive")
    if (
        alert.lane == "DIRECTIONAL_EXPANSION"
        and alert.score >= 120
        and move >= max(absolute_floor, 0.50)
        and efficiency >= 0.72
        and alert.directional_bars >= 3
        and impulse_intact
        and recent_move_intact
    ):
        return DeliveryDecision(True, "high-quality persistent expansion")
    return DeliveryDecision(False, "movement lacks actionable confluence")
