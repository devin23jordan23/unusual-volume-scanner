import os
from dataclasses import dataclass, field


DEFAULT_UNIVERSE = {
    "AAPL", "AAOI", "ABNB", "ADBE", "AFRM", "AMAT", "AMD", "AMZN",
    "ANET", "ARM", "ASML", "AVGO", "BA", "BE",
    "CAT", "CEG", "CMG", "COIN", "COST", "CRM", "CRWD", "CVX", "DDOG",
    "DE", "DELL", "DIA", "ENPH", "FSLR", "GLD", "GOOGL", "HD", "HOOD",
    "INTC", "ISRG", "IWM", "KLAC", "LLY", "LMT", "LOW",
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
    min_5m_move_pct: float = 0.35
    min_speed_ratio: float = 2.0
    cooldown_seconds: int = 600


@dataclass(frozen=True)
class Settings:
    timezone: str = "America/New_York"
    poll_seconds: int = 30
    data_dir: str = "data"
    discord_webhook: str = ""
    log_level: str = "INFO"
    profile_sessions: int = 30
    max_alerts_per_scan: int = 1
    min_alert_interval_seconds: int = 120
    universe: set[str] = field(default_factory=lambda: set(DEFAULT_UNIVERSE))
    thresholds: Thresholds = field(default_factory=Thresholds)


def load_settings() -> Settings:
    universe = csv_set(os.getenv("UVS_UNIVERSE", ",".join(sorted(DEFAULT_UNIVERSE))))
    extra = csv_set(os.getenv("UVS_IN_PLAY", ""))
    return Settings(
        timezone=os.getenv("SCANNER_TIMEZONE", "America/New_York"),
        poll_seconds=int(os.getenv("UVS_POLL_SECONDS", "30")),
        data_dir=os.getenv("DATA_DIR", "data"),
        discord_webhook=os.getenv("DISCORD_UNUSUAL_VOLUME_WEBHOOK", ""),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        profile_sessions=int(os.getenv("UVS_PROFILE_SESSIONS", "30")),
        max_alerts_per_scan=int(os.getenv("UVS_MAX_ALERTS_PER_SCAN", "1")),
        min_alert_interval_seconds=int(os.getenv("UVS_MIN_ALERT_INTERVAL_SECONDS", "120")),
        universe=universe | extra,
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
            min_5m_move_pct=float(os.getenv("UVS_MIN_5M_MOVE_PCT", "0.35")),
            min_speed_ratio=float(os.getenv("UVS_MIN_SPEED_RATIO", "2.0")),
            cooldown_seconds=int(os.getenv("UVS_COOLDOWN_SECONDS", "600")),
        ),
    )


def csv_set(value: str) -> set[str]:
    return {item.strip().upper() for item in value.split(",") if item.strip()}

