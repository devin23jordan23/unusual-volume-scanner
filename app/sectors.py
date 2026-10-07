from dataclasses import replace

from .models import VolumeAlert


SECTOR_BENCHMARKS = {
    "AAPL": "XLK", "ADBE": "XLK", "ANET": "XLK", "CRM": "XLK",
    "CRWD": "XLK", "DDOG": "XLK", "DELL": "XLK", "MSFT": "XLK",
    "NET": "XLK", "NOW": "XLK", "ORCL": "XLK", "PANW": "XLK",
    "PLTR": "XLK", "SNOW": "XLK", "TEAM": "XLK",
    "AMD": "SOXX", "AMAT": "SOXX", "ARM": "SOXX", "ASML": "SOXX",
    "AVGO": "SOXX", "INTC": "SOXX", "KLAC": "SOXX", "LRCX": "SOXX",
    "MRVL": "SOXX", "MU": "SOXX", "NVDA": "SOXX", "QCOM": "SOXX",
    "SMCI": "SOXX", "SNDK": "SOXX", "TSM": "SOXX", "WDC": "SOXX",
    "GOOG": "XLC", "GOOGL": "XLC", "META": "XLC", "NFLX": "XLC",
    "RBLX": "XLC",
    "ABNB": "XLY", "AMZN": "XLY", "HD": "XLY", "LOW": "XLY",
    "LULU": "XLY", "MCD": "XLY", "NKE": "XLY", "SBUX": "XLY",
    "TGT": "XLY", "TSLA": "XLY",
    "AFRM": "XLF", "BAC": "XLF", "COIN": "XLF", "HOOD": "XLF",
    "JPM": "XLF", "MA": "XLF", "PYPL": "XLF", "UPST": "XLF",
    "V": "XLF",
    "ISRG": "XLV", "LLY": "XLV", "UNH": "XLV",
    "MRNA": "IBB", "REGN": "IBB",
    "CVX": "XLE", "XOM": "XLE",
    "BA": "XLI", "BE": "XLI", "CAT": "XLI", "DE": "XLI",
    "LMT": "XLI", "UBER": "XLI",
    "CEG": "XLU", "NRG": "XLU", "VST": "XLU",
    "COST": "XLP", "WMT": "XLP",
    "ENPH": "TAN", "FSLR": "TAN",
}


def context_symbols() -> set[str]:
    return {"SPY", *SECTOR_BENCHMARKS.values()}


def add_sector_context(
    alert: VolumeAlert,
    stock_move_5m: float | None,
    sector_move_5m: float | None,
    spy_move_5m: float | None,
    min_relative_pct: float,
) -> VolumeAlert:
    sector = SECTOR_BENCHMARKS.get(alert.snapshot.symbol)
    if sector is None or sector_move_5m is None or spy_move_5m is None:
        return alert

    direction = 1 if alert.direction == "BULLISH" else -1
    sector_relative = sector_move_5m - spy_move_5m
    directional_sector = direction * sector_move_5m
    directional_relative = direction * sector_relative
    stock_relative = None if stock_move_5m is None else stock_move_5m - sector_move_5m
    directional_stock_relative = None if stock_relative is None else direction * stock_relative

    if directional_sector > 0 and directional_relative >= min_relative_pct:
        label = "SECTOR LEADING"
        boost = 15
    elif directional_sector > 0:
        label = "SECTOR ALIGNED"
        boost = 8
    elif directional_relative >= min_relative_pct:
        label = "SECTOR RELATIVE STRENGTH" if direction > 0 else "SECTOR RELATIVE WEAKNESS"
        boost = 5
    else:
        label = "SECTOR DIVERGENCE"
        boost = 0

    if directional_stock_relative is not None and directional_stock_relative >= min_relative_pct:
        label += " / STOCK LEADING"
        boost += 4

    reason = (
        f"{sector} {sector_move_5m:+.2f}% in 5m, "
        f"{sector_relative:+.2f}% vs SPY"
    )
    return replace(
        alert,
        reasons=alert.reasons + (reason,),
        score=alert.score + boost,
        sector_symbol=sector,
        sector_move_5m_pct=sector_move_5m,
        sector_relative_spy_5m_pct=sector_relative,
        stock_relative_sector_5m_pct=stock_relative,
        sector_context=label,
    )
