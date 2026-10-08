# Unusual Volume Scanner

Standalone Schwab-powered scanner for fresh volume ignition and sustained directional price expansion. Alerts are sent to a dedicated Discord webhook.

SPX is included using Schwab's `$SPX` index prices and levels. Because the index has no share volume, its volume profile, RVOL, and volume-weighted calculations use time-aligned SPY share volume; dollar liquidity uses SPY price. SPX alerts identify index movement, not an option contract. The lotto scanner evaluates SPXW/SPX contracts separately.

## Signal Model

The scanner runs two parallel detection lanes:

- Volume ignition combines time-of-day and local RVOL, dollar liquidity, and fresh ATR-normalized movement.
- Directional expansion combines 5/10/15/30-minute ATR displacement, consecutive directional bars, path efficiency, observed VWAP, active range-edge position, and new-high/new-low recency. Volume improves this lane's score but is not required.
- Mapped large-cap alerts receive a ranking boost when their industry or sector ETF confirms the direction or leads SPY over the same five-minute window. Sector context never blocks an otherwise valid mover.
- Confirmed alerts are ranked higher when their move crosses previous-day, premarket, intraday, multiday, or round-number levels. Crossed levels appear in Discord, while the absence of a key-level cross never blocks a valid mover.

The first impulse arms a short-lived candidate. Continued direction confirms it, sends one alert, and keeps the move active without repeating. A symbol only rearms after consolidation and a meaningful new level break, or after a meaningful reversal.
Confirmed movers from the same 30-second scan are sent in Discord messages containing up to three embeds. Overflow is sent immediately in additional groups, so batching never caps, delays, or drops alerts.

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

See `.env.example` for all `UVS_*` controls. The core universe is maintained in `app/config.py`; `UVS_IN_PLAY` can add temporary names without allowing stale Railway variables to remove core symbols. Stale volume-only conditions cannot alert after the opening window, while fresh directional expansion can alert without elevated RVOL.
Confirmed alerts are unlimited and cannot be capped by a deployment variable.
New listings without completed historical sessions use a temporary self-relative intraday profile until a normal volume and ATR profile is available.
`UVS_MIN_SECTOR_RELATIVE_SPY_PCT` controls the minimum five-minute sector-versus-SPY performance gap used to label a sector as leading; the default is `0.10` percentage points.

## Tests

```bash
python3 -m unittest discover -s tests
```
