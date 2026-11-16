from dataclasses import dataclass

from .config import MARKET_INDEX_SYMBOLS
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
    opening_directional_drive = bool(
        idx is not None and idx < 10
        and alert.lane == "DIRECTIONAL_EXPANSION"
        and move >= 0.65
        and efficiency >= 0.60
        and alert.directional_bars >= 3
        and (alert.directional_share or 0) >= 0.70
        and at_active_edge
        and impulse_intact
        and recent_move_intact
    )
    structured_level_break = bool(
        alert.lane == "DIRECTIONAL_EXPANSION"
        and institutional_level
        and sector_support
        and at_active_edge
        and move >= 0.65
        and speed >= 2.5
        and max(alert.move_10m_atr or 0, alert.move_15m_atr or 0) >= 0.38
        and efficiency >= 0.64
        and alert.directional_bars >= 6
        and (alert.directional_share or 0) >= 0.78
        and impulse_intact
        and recent_move_intact
    )
    directional_recent_move = max(recent_change, 0)
    front_loaded_spike = bool(
        alert.lane == "DIRECTIONAL_EXPANSION"
        and alert.price_change_1m_pct is not None
        and move >= 1.50
        and speed >= 2.0
        and (alert.local_rvol or 0) < 1.0
        and directional_recent_move < move * 0.15
        and not sustained_trend
    )
    market_index_momentum = bool(
        alert.snapshot.symbol in MARKET_INDEX_SYMBOLS
        and alert.lane == "DIRECTIONAL_EXPANSION"
        and move >= 0.15
        and direction * (alert.price_change_5m_pct or 0) > 0
        and max(
            direction * (alert.price_change_10m_pct or 0),
            direction * (alert.price_change_15m_pct or 0),
        ) >= 0.20
        and efficiency >= 0.65
        and alert.directional_bars >= 4
        and (alert.directional_share or 0) >= 0.60
        and speed >= 3.0
        and (alert.local_rvol or 0) >= 2.5
        and at_active_edge
        and impulse_intact
        and recent_move_intact
    )
    sustained_index_trend = bool(
        alert.setup == "SUSTAINED INDEX TREND"
        and alert.snapshot.symbol in MARKET_INDEX_SYMBOLS
        and alert.lane == "DIRECTIONAL_EXPANSION"
        and direction * (alert.price_change_5m_pct or 0) >= 0.06
        and direction * (alert.price_change_10m_pct or 0) >= 0.15
        and direction * (alert.price_change_15m_pct or 0) >= 0.16
        and direction * (alert.price_change_30m_pct or 0) >= 0.20
        and efficiency >= 0.60
        and (alert.efficiency_10m or 0) >= 0.60
        and alert.directional_bars >= 4
        and (alert.directional_share or 0) >= 0.65
        and at_active_edge
        and impulse_intact
        and recent_change >= 0.02
    )
    sustained_liquid_stock_trend = bool(
        alert.setup == "SUSTAINED LIQUID TREND"
        and alert.snapshot.symbol not in MARKET_INDEX_SYMBOLS
        and alert.lane == "DIRECTIONAL_EXPANSION"
        and direction * (alert.price_change_5m_pct or 0) >= 0.18
        and direction * (alert.price_change_10m_pct or 0) >= 0.24
        and direction * (alert.price_change_15m_pct or 0) >= 0.25
        and direction * (alert.price_change_30m_pct or 0) >= 0.30
        and efficiency >= 0.75
        and (alert.efficiency_10m or 0) >= 0.65
        and alert.directional_bars >= 4
        and (alert.directional_share or 0) >= 0.65
        and at_active_edge
        and impulse_intact
        and recent_change >= 0.05
    )
    liquid_trend_acceleration = bool(
        alert.setup == "TREND ACCELERATION"
        and alert.lane == "DIRECTIONAL_EXPANSION"
        and move >= 0.35
        and direction * (alert.price_change_15m_pct or 0) >= 0.35
        and direction * (alert.price_change_30m_pct or 0) >= 0.65
        and efficiency >= 0.70
        and alert.directional_bars >= 3
        and alert.tod_rvol >= 1.50
        and (alert.local_rvol or 0) >= 2.50
        and at_active_edge
        and impulse_intact
        and recent_change >= 0.08
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

    if front_loaded_spike:
        return DeliveryDecision(False, "front-loaded spike lacks fresh continuation")
    if market_index_momentum:
        return DeliveryDecision(True, "fresh market-index momentum")
    if sustained_index_trend:
        return DeliveryDecision(True, "sustained market-index trend at the active range edge")
    if sustained_liquid_stock_trend:
        return DeliveryDecision(True, "sustained liquid-stock trend at the active range edge")
    if liquid_trend_acceleration:
        return DeliveryDecision(True, "liquid trend acceleration at the active range edge")
    if (move < absolute_floor and not strong_atr_impulse and not sustained_trend
            and not opening_directional_drive):
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
            and not institutional_level and not explosive and not strong_atr_impulse
            and not sustained_trend and not opening_directional_drive):
        return DeliveryDecision(False, "sector divergence without exceptional movement")
    if opening_directional_drive:
        return DeliveryDecision(True, "fresh opening percentage expansion")
    if structured_level_break:
        return DeliveryDecision(True, "structured multi-window level break")
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
