from dataclasses import dataclass
from datetime import datetime
from enum import Enum


@dataclass(frozen=True)
class StockSnapshot:
    symbol: str
    price: float
    volume: int
    timestamp: datetime
    open_price: float | None = None
    previous_close: float | None = None
    high_price: float | None = None
    low_price: float | None = None

    @property
    def change_from_open_pct(self) -> float | None:
        if not self.open_price:
            return None
        return (self.price - self.open_price) / self.open_price * 100

    @property
    def change_from_close_pct(self) -> float | None:
        if not self.previous_close:
            return None
        return (self.price - self.previous_close) / self.previous_close * 100

    @property
    def range_position(self) -> float | None:
        if self.high_price is None or self.low_price is None or self.high_price <= self.low_price:
            return None
        return (self.price - self.low_price) / (self.high_price - self.low_price)


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class VolumeProfile:
    symbol: str
    sessions: int
    minute_volume: tuple[float, ...]
    move_5m_pct: tuple[float, ...]
    atr14: float
    as_of: str
    generated_on: str

    def expected_cumulative(self, minute_index: int, minute_fraction: float = 1.0) -> float:
        idx = max(0, min(minute_index, len(self.minute_volume) - 1))
        return sum(self.minute_volume[:idx]) + self.minute_volume[idx] * max(0.0, min(minute_fraction, 1.0))

    def expected_window(self, end_minute_index: int, minutes: int = 5) -> float:
        end = max(0, min(end_minute_index + 1, len(self.minute_volume)))
        return sum(self.minute_volume[max(0, end - minutes):end])

    def normal_5m_move_pct(self, minute_index: int) -> float | None:
        if not self.move_5m_pct:
            return None
        idx = max(0, min(minute_index, len(self.move_5m_pct) - 1))
        value = self.move_5m_pct[idx]
        return value if value > 0 else None


@dataclass(frozen=True)
class MovementFeatures:
    volume_5m: int | None
    change_5m_pct: float | None
    change_10m_pct: float | None
    change_15m_pct: float | None
    move_5m_atr: float | None
    move_10m_atr: float | None
    move_15m_atr: float | None
    efficiency_5m: float | None
    efficiency_10m: float | None
    directional_bars: int
    directional_share: float | None
    vwap: float | None
    vwap_aligned: bool
    vwap_crossed: bool
    new_extreme_age_seconds: float | None
    fresh_level_break: bool


class Severity(str, Enum):
    WATCH = "WATCH"
    IN_PLAY = "IN PLAY"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


@dataclass(frozen=True)
class VolumeAlert:
    snapshot: StockSnapshot
    severity: Severity
    direction: str
    setup: str
    reasons: tuple[str, ...]
    tod_rvol: float
    local_rvol: float | None
    volume_5m: int | None
    dollar_volume_5m: float
    price_change_5m_pct: float | None
    speed_ratio: float | None
    move_5m_atr: float | None
    atr_progress: float | None
    range_atr: float | None
    lane: str = "VOLUME_IGNITION"
    score: float = 0.0
    confirmation_ready: bool = False
    efficiency: float | None = None
    directional_bars: int = 0
    vwap: float | None = None
