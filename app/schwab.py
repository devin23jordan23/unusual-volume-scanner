import base64
import fcntl
import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

from .config import Settings
from .models import Candle, StockSnapshot
from .oauth import callback_code

LOG = logging.getLogger(__name__)
AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
BASE_URL = "https://api.schwabapi.com/marketdata/v1"
REDIRECT_URI = os.getenv("SCHWAB_REDIRECT_URI", "https://127.0.0.1")


class SchwabClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client_id = os.getenv("SCHWAB_CLIENT_ID", "")
        self.client_secret = os.getenv("SCHWAB_CLIENT_SECRET", "")
        self.seed_refresh_token = os.getenv("SCHWAB_REFRESH_TOKEN", "")
        self.seed_access_token = os.getenv("SCHWAB_ACCESS_TOKEN", "")
        os.makedirs(settings.data_dir, exist_ok=True)
        self.token_file = os.path.join(settings.data_dir, "schwab_tokens.json")
        callback = os.getenv("SCHWAB_AUTH_CALLBACK_URL", "")
        if callback and not os.path.exists(self.token_file):
            self.exchange_callback_url(callback)

    def stock_snapshots(self, symbols: list[str]) -> list[StockSnapshot]:
        output = []
        now = datetime.now(ZoneInfo(self.settings.timezone))
        for batch in chunks(symbols, 50):
            data = self.get("/quotes", {"symbols": ",".join(batch)})
            for symbol in batch:
                snapshot = parse_quote(symbol, data.get(symbol, {}), now)
                if snapshot:
                    output.append(snapshot)
        return output

    def price_history(self, symbol: str, calendar_days: int = 50) -> list[Candle]:
        now = datetime.now(ZoneInfo(self.settings.timezone))
        start = now - timedelta(days=calendar_days)
        data = self.get("/pricehistory", {
            "symbol": symbol,
            "periodType": "day",
            "frequencyType": "minute",
            "frequency": 1,
            "startDate": int(start.timestamp() * 1000),
            "endDate": int(now.timestamp() * 1000),
            "needExtendedHoursData": "false",
        })
        candles = []
        for raw in data.get("candles", []):
            try:
                timestamp = datetime.fromtimestamp(raw["datetime"] / 1000, ZoneInfo(self.settings.timezone))
                candles.append(Candle(timestamp, float(raw["open"]), float(raw["high"]), float(raw["low"]), float(raw["close"]), int(raw["volume"])))
            except (KeyError, TypeError, ValueError):
                continue
        return candles

    def get(self, endpoint: str, params: dict | None = None) -> dict:
        for attempt in range(2):
            access_token = self.access_token()
            response = requests.get(
                f"{BASE_URL}{endpoint}",
                headers=self.headers(access_token),
                params=params or {},
                timeout=20,
            )
            if response.status_code == 401 and attempt == 0:
                self.refresh_after_unauthorized(access_token)
                continue
            response.raise_for_status()
            return response.json()
        return {}

    def headers(self, access_token: str | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token or self.access_token()}", "Accept": "application/json"}

    def access_token(self) -> str:
        tokens = self.load_tokens()
        if not tokens:
            raise RuntimeError(f"Schwab authorization required: {self.authorization_url()}")
        if expired(tokens):
            with self.token_lock():
                tokens = self.load_tokens()
                if expired(tokens):
                    tokens = self.refresh_tokens(tokens)
        return tokens.get("access_token") or ""

    def load_tokens(self) -> dict:
        if os.path.exists(self.token_file):
            with open(self.token_file, "r") as handle:
                return json.load(handle)
        if not self.seed_refresh_token:
            return {}
        return {"refresh_token": self.seed_refresh_token, "access_token": self.seed_access_token, "expires_in": 0, "saved_at": 0}

    def save_tokens(self, tokens: dict) -> None:
        tokens["saved_at"] = time.time()
        temporary = f"{self.token_file}.{os.getpid()}.tmp"
        with open(temporary, "w") as handle:
            json.dump(tokens, handle, indent=2)
        os.replace(temporary, self.token_file)

    def refresh_after_unauthorized(self, failed_access_token: str) -> None:
        with self.token_lock():
            tokens = self.load_tokens()
            if tokens.get("access_token") == failed_access_token:
                self.refresh_tokens(tokens)

    @contextmanager
    def token_lock(self):
        with open(f"{self.token_file}.lock", "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def refresh_tokens(self, tokens: dict) -> dict:
        response = requests.post(TOKEN_URL, headers=self.basic_headers(), data={"grant_type": "refresh_token", "refresh_token": tokens.get("refresh_token", "")}, timeout=20)
        if response.status_code in (400, 401, 403):
            raise RuntimeError("Schwab refresh token is expired or invalid")
        response.raise_for_status()
        refreshed = response.json()
        refreshed.setdefault("refresh_token", tokens.get("refresh_token"))
        self.save_tokens(refreshed)
        return refreshed

    def authorization_url(self) -> str:
        return f"{AUTH_URL}?{urlencode({'response_type': 'code', 'client_id': self.client_id, 'redirect_uri': REDIRECT_URI, 'scope': 'readonly'})}"

    def exchange_callback_url(self, callback_url: str) -> dict:
        code = callback_code(callback_url)
        if not code:
            raise RuntimeError("callback URL does not contain a Schwab authorization code")
        response = requests.post(TOKEN_URL, headers=self.basic_headers(), data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI}, timeout=20)
        response.raise_for_status()
        tokens = response.json()
        self.save_tokens(tokens)
        return tokens

    def basic_headers(self) -> dict[str, str]:
        if not self.client_id or not self.client_secret:
            raise RuntimeError("SCHWAB_CLIENT_ID and SCHWAB_CLIENT_SECRET are required")
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        return {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"}


def parse_quote(symbol: str, raw: dict, now: datetime) -> StockSnapshot | None:
    quote = raw.get("quote") or raw
    price = first_number(quote, "lastPrice", "mark", "regularMarketLastPrice", "closePrice")
    # Prefer regular-session volume so premarket prints do not inflate RTH RVOL.
    volume = first_number(quote, "regularMarketTotalVolume", "totalVolume", "volume")
    if price is None or volume is None:
        return None
    return StockSnapshot(
        symbol, price, int(volume), now,
        first_number(quote, "regularMarketOpenPrice", "openPrice", "open"),
        first_number(quote, "regularMarketPreviousClose", "closePrice", "previousClose"),
        first_number(quote, "regularMarketDayHigh", "highPrice", "high"),
        first_number(quote, "regularMarketDayLow", "lowPrice", "low"),
    )


def first_number(raw: dict, *keys: str) -> float | None:
    for key in keys:
        try:
            if raw.get(key) is not None:
                return float(raw[key])
        except (TypeError, ValueError):
            pass
    return None


def expired(tokens: dict) -> bool:
    return time.time() > float(tokens.get("saved_at", 0)) + int(tokens.get("expires_in", 1800)) - 300


def chunks(items: list[str], size: int):
    for index in range(0, len(items), size):
        yield items[index:index + size]

