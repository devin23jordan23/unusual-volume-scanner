import os
from dataclasses import dataclass, field


DEFAULT_UNIVERSE = {
    "AAPL", "AAOI", "ABNB", "ADBE", "AFRM", "AMAT", "AMD", "AMZN",
    "ANET", "ARM", "ASML", "AVGO", "BA", "BAC", "BE",
    "CAT", "CEG", "CMG", "COIN", "COST", "CRM", "CRWD", "CVX", "DDOG",
    "DE", "DELL", "DIA", "ENPH", "FSLR", "GLD", "GOOG", "GOOGL", "HD", "HOOD",
    "INTC", "ISRG", "IWM", "JPM", "KLAC", "LLY", "LMT", "LOW",
    "LRCX", "LULU", "MA", "MCD", "MDB", "META", "MRNA", "MRVL",
    "MSFT", "MSTR", "MTUM", "MU", "NBIS", "NET", "NFLX", "NKE", "NOW",
    "NRG", "NVDA", "OKLO", "OKTA", "ORCL", "PANW", "PLTR", "PYPL",
    "QCOM", "QQQ", "RBLX", "REGN", "SBUX", "SKHY", "SLV", "SMCI", "SMH",
    "SNDK", "SNOW", "SOFI", "SOXX", "SPY", "TEAM", "TGT", "SHOP", "TSLA",
    "TSM", "UBER", "UNH", "UPST", "USO", "V", "VRT", "VST", "WMT", "XLE",
    "XLF", "XLK", "XOM", "ZS",
}


@dataclass(frozen=True)
class Thresholds:
    min_price: float = 5.0
    max_price: float = 10_000.0
    min_volume_today: int = 250_000
    min_5m_dollar_volume: float = 10_000_000
    min_tod_rvol: float = 2.0
    high_tod_rvol: float = 3.0
    extreme_tod_rvol: float = 5.0
    min_local_rvol: float = 2.5
    min_atr_progress: float = 0.20
    min_range_atr: float = 0.35
    min_5m_move_pct: float = 0.50
    min_5m_atr_move: float = 0.15
    min_speed_ratio: float = 2.0
    realert_min_price_change_pct: float = 1.0
    cooldown_seconds: int = 600
    candidate_expiry_seconds: int = 300
    candidate_confirm_seconds: int = 120
    min_directional_efficiency: float = 0.55
    min_directional_bars: int = 3
    min_directional_5m_atr: float = 0.12
    min_directional_10m_atr: float = 0.20
    min_directional_15m_atr: float = 0.28
    directional_edge_position: float = 0.70
    max_extreme_age_seconds: int = 300
    consolidation_retrace_atr: float = 0.15
    rearm_break_atr: float = 0.10
    reversal_rearm_atr: float = 0.20


@dataclass(frozen=True)
class Settings:
    timezone: str = "America/New_York"
    poll_seconds: int = 30
    data_dir: str = "data"
    discord_webhook: str = ""
    log_level: str = "INFO"
    profile_sessions: int = 30
    max_alerts_per_scan: int = 0
    min_alert_interval_seconds: int = 0
    universe: set[str] = field(default_factory=lambda: set(DEFAULT_UNIVERSE))
    thresholds: Thresholds = field(default_factory=Thresholds)


def load_settings() -> Settings:
    extra = csv_set(os.getenv("UVS_IN_PLAY", ""))
    return Settings(
        timezone=os.getenv("SCANNER_TIMEZONE", "America/New_York"),
        poll_seconds=int(os.getenv("UVS_POLL_SECONDS", "30")),
        data_dir=os.getenv("DATA_DIR", "data"),
        discord_webhook=os.getenv("DISCORD_UNUSUAL_VOLUME_WEBHOOK", ""),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        profile_sessions=int(os.getenv("UVS_PROFILE_SESSIONS", "30")),
        max_alerts_per_scan=0,
        min_alert_interval_seconds=int(os.getenv("UVS_MIN_ALERT_INTERVAL_SECONDS", "0")),
        universe=set(DEFAULT_UNIVERSE) | extra,
        thresholds=Thresholds(
            min_price=float(os.getenv("UVS_MIN_PRICE", "5")),
            max_price=float(os.getenv("UVS_MAX_PRICE", "10000")),
            min_volume_today=int(os.getenv("UVS_MIN_VOLUME_TODAY", "250000")),
            min_5m_dollar_volume=float(os.getenv("UVS_MIN_5M_DOLLAR_VOLUME", "10000000")),
            min_tod_rvol=float(os.getenv("UVS_MIN_TOD_RVOL", "2.0")),
            high_tod_rvol=float(os.getenv("UVS_HIGH_TOD_RVOL", "3.0")),
            extreme_tod_rvol=float(os.getenv("UVS_EXTREME_TOD_RVOL", "5.0")),
            min_local_rvol=float(os.getenv("UVS_MIN_LOCAL_RVOL", "2.5")),
            min_atr_progress=float(os.getenv("UVS_MIN_ATR_PROGRESS", "0.20")),
            min_range_atr=float(os.getenv("UVS_MIN_RANGE_ATR", "0.35")),
            min_5m_move_pct=float(os.getenv("UVS_MIN_5M_MOVE_PCT", "0.50")),
            min_5m_atr_move=float(os.getenv("UVS_MIN_5M_ATR_MOVE", "0.15")),
            min_speed_ratio=float(os.getenv("UVS_MIN_SPEED_RATIO", "2.0")),
            realert_min_price_change_pct=float(os.getenv("UVS_REALERT_MIN_PRICE_CHANGE_PCT", "1.0")),
            cooldown_seconds=int(os.getenv("UVS_COOLDOWN_SECONDS", "600")),
            candidate_expiry_seconds=int(os.getenv("UVS_CANDIDATE_EXPIRY_SECONDS", "300")),
            candidate_confirm_seconds=int(os.getenv("UVS_CANDIDATE_CONFIRM_SECONDS", "120")),
            min_directional_efficiency=float(os.getenv("UVS_MIN_DIRECTIONAL_EFFICIENCY", "0.55")),
            min_directional_bars=int(os.getenv("UVS_MIN_DIRECTIONAL_BARS", "3")),
            min_directional_5m_atr=float(os.getenv("UVS_MIN_DIRECTIONAL_5M_ATR", "0.12")),
            min_directional_10m_atr=float(os.getenv("UVS_MIN_DIRECTIONAL_10M_ATR", "0.20")),
            min_directional_15m_atr=float(os.getenv("UVS_MIN_DIRECTIONAL_15M_ATR", "0.28")),
            directional_edge_position=float(os.getenv("UVS_DIRECTIONAL_EDGE_POSITION", "0.70")),
            max_extreme_age_seconds=int(os.getenv("UVS_MAX_EXTREME_AGE_SECONDS", "300")),
            consolidation_retrace_atr=float(os.getenv("UVS_CONSOLIDATION_RETRACE_ATR", "0.15")),
            rearm_break_atr=float(os.getenv("UVS_REARM_BREAK_ATR", "0.10")),
            reversal_rearm_atr=float(os.getenv("UVS_REVERSAL_REARM_ATR", "0.20")),
        ),
    )


def csv_set(value: str) -> set[str]:
    return {item.strip().upper() for item in value.split(",") if item.strip()}
