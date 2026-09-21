from urllib.parse import parse_qs, urlparse


def callback_code(callback_url: str) -> str:
    try:
        return parse_qs(urlparse(callback_url.strip()).query).get("code", [""])[0]
    except (AttributeError, TypeError, ValueError):
        return ""

