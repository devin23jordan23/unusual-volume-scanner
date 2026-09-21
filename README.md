# Unusual Volume Scanner

Standalone Schwab-powered scanner for stocks trading unusually high volume for the current time of day **and** producing meaningful price expansion. Alerts are sent to a dedicated Discord webhook.

## Signal Model

The scanner builds a 30-session, one-minute profile for every symbol and calculates:

- Time-of-day RVOL: today's regular-session volume divided by normal cumulative volume through the same minute.
- Local 5-minute RVOL: the latest five-minute volume divided by normal volume during those same clock minutes.
- ATR progress: distance from today's open divided by 14-session ATR.
- Five-minute price speed: current five-minute movement divided by normal same-time movement.

Volume is not enough by itself. An alert requires unusual participation, meaningful price movement, and sufficient dollar liquidity.

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.main
```

Environment variables are not loaded automatically from `.env`; export them in your shell or configure them in Railway.

## Required Railway Variables

```text
SCHWAB_CLIENT_ID=
SCHWAB_CLIENT_SECRET=
SCHWAB_REFRESH_TOKEN=
DISCORD_UNUSUAL_VOLUME_WEBHOOK=
SCANNER_TIMEZONE=America/New_York
DATA_DIR=/app/data
```

Mount a persistent Railway volume at `/app/data`. Historical profiles, refreshed Schwab tokens, and alert cooldown state are stored there.

For browser authorization, temporarily set `SCHWAB_AUTH_SETUP_KEY`, deploy with a public Railway domain, and open `/schwab-auth`. Remove the setup key after authorization.

## Tuning

See `.env.example` for all `UVS_*` controls. Defaults use SMB-style stock-in-play tiers of `2x`, `3x`, and `5x` time-of-day RVOL, while requiring ATR or five-minute price-speed confirmation.

## Tests

```bash
python3 -m unittest discover -s tests
```
