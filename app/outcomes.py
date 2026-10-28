import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime

from .models import StockSnapshot, VolumeAlert


HORIZONS = ((300, "outcome_5m_pct"), (900, "outcome_15m_pct"),
            (1800, "outcome_30m_pct"), (3600, "outcome_60m_pct"))


class AlertOutcomeStore:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS alert_outcomes (
                id INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                alert_time TEXT NOT NULL,
                alert_epoch REAL NOT NULL,
                alert_price REAL NOT NULL,
                direction TEXT NOT NULL,
                lane TEXT NOT NULL,
                setup TEXT NOT NULL,
                severity TEXT NOT NULL,
                score REAL NOT NULL,
                tod_rvol REAL NOT NULL,
                local_rvol REAL,
                move_5m_pct REAL,
                move_10m_pct REAL,
                move_15m_pct REAL,
                move_5m_atr REAL,
                move_10m_atr REAL,
                move_15m_atr REAL,
                atr_progress REAL,
                efficiency REAL,
                efficiency_10m REAL,
                directional_bars INTEGER NOT NULL,
                directional_share REAL,
                sector_context TEXT,
                crossed_levels TEXT NOT NULL,
                delivery_status TEXT NOT NULL,
                delivery_reason TEXT NOT NULL,
                mfe_pct REAL NOT NULL DEFAULT 0,
                mae_pct REAL NOT NULL DEFAULT 0,
                outcome_5m_pct REAL,
                outcome_15m_pct REAL,
                outcome_30m_pct REAL,
                outcome_60m_pct REAL,
                latest_outcome_pct REAL NOT NULL DEFAULT 0,
                last_seen_at TEXT,
                UNIQUE(symbol, alert_time, lane)
            )
        """)
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_alert_outcomes_symbol_epoch "
            "ON alert_outcomes(symbol, alert_epoch)"
        )
        self._ensure_columns({
            "move_10m_pct": "REAL",
            "move_15m_pct": "REAL",
            "move_10m_atr": "REAL",
            "move_15m_atr": "REAL",
            "efficiency_10m": "REAL",
            "directional_share": "REAL",
        })
        self.connection.commit()

    def _ensure_columns(self, columns: dict[str, str]) -> None:
        existing = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(alert_outcomes)").fetchall()
        }
        for name, column_type in columns.items():
            if name not in existing:
                self.connection.execute(
                    f"ALTER TABLE alert_outcomes ADD COLUMN {name} {column_type}"
                )

    def record(self, alert: VolumeAlert, status: str, reason: str) -> None:
        if status.startswith("SUPPRESSED"):
            recent = self.connection.execute(
                "SELECT alert_epoch FROM alert_outcomes WHERE symbol=? AND lane=? "
                "AND delivery_status=? AND delivery_reason=? ORDER BY alert_epoch DESC LIMIT 1",
                (alert.snapshot.symbol, alert.lane, status, reason),
            ).fetchone()
            if recent and alert.snapshot.timestamp.timestamp() - recent["alert_epoch"] < 300:
                return
        self.connection.execute("""
            INSERT INTO alert_outcomes (
                symbol, alert_time, alert_epoch, alert_price, direction, lane, setup,
                severity, score, tod_rvol, local_rvol, move_5m_pct, move_5m_atr,
                move_10m_pct, move_15m_pct, move_10m_atr, move_15m_atr,
                atr_progress, efficiency, efficiency_10m, directional_bars,
                directional_share, sector_context,
                crossed_levels, delivery_status, delivery_reason, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, alert_time, lane) DO UPDATE SET
                delivery_status=excluded.delivery_status,
                delivery_reason=excluded.delivery_reason
        """, (
            alert.snapshot.symbol, alert.snapshot.timestamp.isoformat(),
            alert.snapshot.timestamp.timestamp(), alert.snapshot.price, alert.direction,
            alert.lane, alert.setup, alert.severity.value, alert.score, alert.tod_rvol,
            alert.local_rvol, alert.price_change_5m_pct, alert.move_5m_atr,
            alert.price_change_10m_pct, alert.price_change_15m_pct,
            alert.move_10m_atr, alert.move_15m_atr,
            alert.atr_progress, alert.efficiency, alert.efficiency_10m,
            alert.directional_bars, alert.directional_share,
            alert.sector_context, json.dumps(alert.crossed_levels), status, reason,
            alert.snapshot.timestamp.isoformat(),
        ))
        self.connection.commit()

    def observe(self, snapshots: list[StockSnapshot]) -> None:
        for snapshot in snapshots:
            rows = self.connection.execute(
                "SELECT * FROM alert_outcomes WHERE symbol=? AND alert_epoch<=? "
                "AND alert_epoch>=?",
                (snapshot.symbol, snapshot.timestamp.timestamp(),
                 snapshot.timestamp.timestamp() - 25_200),
            ).fetchall()
            for row in rows:
                self._observe_row(row, snapshot)
        self.connection.commit()

    def _observe_row(self, row: sqlite3.Row, snapshot: StockSnapshot) -> None:
        sign = 1 if row["direction"] == "BULLISH" else -1
        outcome = sign * (snapshot.price - row["alert_price"]) / row["alert_price"] * 100
        elapsed = snapshot.timestamp.timestamp() - row["alert_epoch"]
        updates = {
            "mfe_pct": max(float(row["mfe_pct"]), outcome),
            "mae_pct": max(float(row["mae_pct"]), -outcome),
            "latest_outcome_pct": outcome,
            "last_seen_at": snapshot.timestamp.isoformat(),
        }
        for seconds, column in HORIZONS:
            if elapsed >= seconds and row[column] is None:
                updates[column] = outcome
        assignments = ", ".join(f"{key}=?" for key in updates)
        self.connection.execute(
            f"UPDATE alert_outcomes SET {assignments} WHERE id=?",
            (*updates.values(), row["id"]),
        )

    def summary(self, day: str, delivered_only: bool = True) -> dict:
        condition = "AND delivery_status='DELIVERED'" if delivered_only else ""
        rows = self.connection.execute(
            f"SELECT * FROM alert_outcomes WHERE substr(alert_time, 1, 10)=? {condition}",
            (day,),
        ).fetchall()
        winners = [row for row in rows if float(row["mfe_pct"]) >= 0.75]
        return {
            "alerts": len(rows),
            "winners": len(winners),
            "win_rate": len(winners) / len(rows) if rows else 0,
            "average_mfe_pct": sum(float(row["mfe_pct"]) for row in rows) / len(rows) if rows else 0,
            "average_mae_pct": sum(float(row["mae_pct"]) for row in rows) / len(rows) if rows else 0,
        }

    def write_daily_report(self, day: str, directory: str) -> str | None:
        rows = self.connection.execute(
            "SELECT * FROM alert_outcomes WHERE substr(alert_time, 1, 10)=?",
            (day,),
        ).fetchall()
        if not rows:
            return None
        grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in rows:
            grouped[f"lane:{row['lane']}"].append(row)
            grouped[f"sector:{sector_bucket(row['sector_context'])}"].append(row)
            grouped[f"level:{'YES' if json.loads(row['crossed_levels']) else 'NO'}"].append(row)
            grouped[f"time:{time_bucket(row['alert_time'])}"].append(row)
        report = {
            "date": day,
            "definition": "worked = at least 0.75% MFE and positive 15-minute continuation",
            "delivered": outcome_metrics([row for row in rows if row["delivery_status"] == "DELIVERED"]),
            "suppressed": outcome_metrics([row for row in rows if row["delivery_status"].startswith("SUPPRESSED")]),
            "groups": {name: outcome_metrics(items) for name, items in sorted(grouped.items())},
            "top_movers": [
                {"symbol": row["symbol"], "time": row["alert_time"], "lane": row["lane"],
                 "status": row["delivery_status"], "mfe_pct": round(float(row["mfe_pct"]), 3),
                 "mae_pct": round(float(row["mae_pct"]), 3),
                 "outcome_15m_pct": row["outcome_15m_pct"]}
                for row in sorted(rows, key=lambda item: float(item["mfe_pct"]), reverse=True)[:20]
            ],
        }
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"{day}.json")
        temporary = f"{path}.tmp"
        with open(temporary, "w") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
        os.replace(temporary, path)
        return path


def outcome_metrics(rows: list[sqlite3.Row]) -> dict:
    worked = [
        row for row in rows
        if float(row["mfe_pct"]) >= 0.75 and float(row["outcome_15m_pct"] or 0) > 0
    ]
    return {
        "signals": len(rows),
        "worked": len(worked),
        "worked_rate": round(len(worked) / len(rows), 4) if rows else 0,
        "average_mfe_pct": round(sum(float(row["mfe_pct"]) for row in rows) / len(rows), 4) if rows else 0,
        "average_mae_pct": round(sum(float(row["mae_pct"]) for row in rows) / len(rows), 4) if rows else 0,
    }


def sector_bucket(value: str | None) -> str:
    if not value:
        return "NONE"
    if "DIVERGENCE" in value:
        return "DIVERGENCE"
    if "LEADING" in value or "ALIGNED" in value:
        return "CONFIRMED"
    return "OTHER"


def time_bucket(value: str) -> str:
    stamp = datetime.fromisoformat(value)
    minutes = stamp.hour * 60 + stamp.minute
    if minutes < 10 * 60:
        return "OPENING_0930_1000"
    if minutes < 11 * 60 + 30:
        return "MORNING_1000_1130"
    if minutes < 14 * 60:
        return "MIDDAY_1130_1400"
    return "AFTERNOON_1400_1600"
