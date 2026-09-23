# Unusual Volume Scanner

Standalone Schwab-powered scanner for fresh volume ignition and sustained directional price expansion. Alerts are sent to a dedicated Discord webhook.

## Signal Model

The scanner runs two parallel detection lanes:

- Volume ignition combines time-of-day and local RVOL, dollar liquidity, and fresh ATR-normalized movement.
- Directional expansion combines 5/10/15-minute ATR displacement, consecutive directional bars, path efficiency, observed VWAP, active range-edge position, and new-high/new-low recency. Volume improves this lane's score but is not required.

The first impulse arms a short-lived candidate. Continued direction confirms it, sends one alert, and keeps the move active without repeating. A symbol only rearms after consolidation and a meaningful new level break, or after a meaningful reversal.

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

See `.env.example` for all `UVS_*` controls. Stale volume-only conditions cannot alert after the opening window, while fresh directional expansion can alert without elevated RVOL.

## Tests

```bash
python3 -m unittest discover -s tests
```
