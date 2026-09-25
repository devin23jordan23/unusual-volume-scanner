from datetime import datetime, time
from zoneinfo import ZoneInfo


def is_market_open(tz_name: str = "America/New_York") -> bool:
    now = datetime.now(ZoneInfo(tz_name))
    return now.weekday() < 5 and time(9, 30) <= now.time() <= time(16, 0)


def is_premarket(tz_name: str = "America/New_York") -> bool:
    now = datetime.now(ZoneInfo(tz_name))
    return now.weekday() < 5 and time(8, 0) <= now.time() < time(9, 30)
