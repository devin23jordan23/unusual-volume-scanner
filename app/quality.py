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
    late_session = idx is not None and idx >= 150
    is_etf = alert.snapshot.symbol in ETF_SYMBOLS
    absolute_floor = 0.25 if is_etf else 0.40
    efficient = efficiency >= 0.68
    explosive = move >= 0.75 and speed >= 2.5 and efficiency >= 0.70
    strong_atr_impulse = atr_move >= 0.22 and move >= absolute_floor and efficiency >= 0.72
    institutional_level = alert.level_tier == 1
    sector_support = bool(
        alert.sector_context
        and "DIVERGENCE" not in alert.sector_context
        and ("LEADING" in alert.sector_context or "ALIGNED" in alert.sector_context)
    )

    if move < absolute_floor and not strong_atr_impulse:
        return DeliveryDecision(False, "insufficient absolute 5m movement")
    if late_session and not institutional_level and not explosive:
        return DeliveryDecision(False, "late-session move lacks a key level or explosive expansion")
    if alert.sector_context and "DIVERGENCE" in alert.sector_context and not institutional_level and not explosive:
        return DeliveryDecision(False, "sector divergence without exceptional movement")
    if institutional_level and efficient:
        return DeliveryDecision(True, "institutional level break with directional efficiency")
    if sector_support and efficient and speed >= 3.0:
        return DeliveryDecision(True, "sector-confirmed directional expansion")
    if explosive or strong_atr_impulse:
        return DeliveryDecision(True, "exceptional self-relative price expansion")
    if (
        alert.setup == "OPENING DRIVE"
        and (alert.atr_progress or 0) >= 0.30
        and move >= max(absolute_floor, 0.50)
        and efficiency >= 0.60
    ):
        return DeliveryDecision(True, "confirmed opening drive")
    if (
        alert.lane == "DIRECTIONAL_EXPANSION"
        and alert.score >= 120
        and move >= max(absolute_floor, 0.50)
        and efficiency >= 0.72
        and alert.directional_bars >= 3
    ):
        return DeliveryDecision(True, "high-quality persistent expansion")
    return DeliveryDecision(False, "movement lacks actionable confluence")
