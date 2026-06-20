"""
storage.py — Persistent state management for EventIQ.

SQLite-backed storage for:
  - events_log     : every prediction + decision made by the supervisory agent
  - feedback_log   : post-event officer feedback
  - active_events  : currently active / in-progress events

Public API:
    log_event(event_decision)     → int (row id)
    get_recent_events(n)          → list of dicts
    save_feedback(event_id, data) → None
    get_feedback(event_id)        → dict | None
    get_all_feedback()            → list of dicts
    get_active_events()           → list of dicts
    set_event_status(id, status)  → None
    get_kpi_summary()             → dict
    clear_old_logs(days)          → int (rows deleted)
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_HERE)
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "logs", "eventiq.db")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS events_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id         TEXT,
    event_type       TEXT,
    event_cause      TEXT,
    corridor         TEXT,
    zone             TEXT,
    police_station   TEXT,
    latitude         REAL,
    longitude        REAL,
    priority_actual  TEXT,
    priority_pred    TEXT,
    congestion_score REAL,
    risk_level       TEXT,
    cascade_prob     REAL,
    cascade_severity TEXT,
    nearest_ps       TEXT,
    resource_plan    TEXT,
    diversion_plan   TEXT,
    llm_brief        TEXT,
    input_json       TEXT,
    status           TEXT DEFAULT 'active',
    created_at       TEXT,
    updated_at       TEXT
);
"""

_CREATE_FEEDBACK = """
CREATE TABLE IF NOT EXISTS feedback_log (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    event_log_id         INTEGER,
    actual_congestion    REAL,
    actual_duration_min  REAL,
    officers_deployed    INTEGER,
    barricades_deployed  INTEGER,
    diversion_used       TEXT,
    what_worked          TEXT,
    what_didnt           TEXT,
    submitted_at         TEXT,
    FOREIGN KEY(event_log_id) REFERENCES events_log(id)
);
"""

_CREATE_ACTIVE = """
CREATE TABLE IF NOT EXISTS active_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_log_id   INTEGER,
    corridor       TEXT,
    zone           TEXT,
    police_station TEXT,
    latitude       REAL,
    longitude      REAL,
    risk_level     TEXT,
    started_at     TEXT,
    FOREIGN KEY(event_log_id) REFERENCES events_log(id)
);
"""


# ---------------------------------------------------------------------------
# Storage class
# ---------------------------------------------------------------------------

class EventStorage:
    """Thread-safe SQLite storage for EventIQ decisions and feedback."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.execute(_CREATE_EVENTS)
            conn.execute(_CREATE_FEEDBACK)
            conn.execute(_CREATE_ACTIVE)

    # ------------------------------------------------------------------
    # Event log
    # ------------------------------------------------------------------

    def log_event(self, decision: dict) -> int:
        """
        Persist a supervisory agent decision.

        Args:
            decision: EventDecision dict (output of supervisory_agent.run()).

        Returns:
            Integer row id of the inserted record.
        """
        now = datetime.now(timezone.utc).isoformat()
        sql = """
        INSERT INTO events_log
          (event_id, event_type, event_cause, corridor, zone, police_station,
           latitude, longitude, priority_actual, priority_pred, congestion_score,
           risk_level, cascade_prob, cascade_severity, nearest_ps,
           resource_plan, diversion_plan, llm_brief, input_json, status,
           created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """
        inp = decision.get("input", {})
        vals = (
            decision.get("event_id", ""),
            inp.get("event_type", ""),
            inp.get("event_cause", ""),
            inp.get("corridor", ""),
            inp.get("zone", ""),
            inp.get("police_station", ""),
            float(inp.get("latitude", 0)),
            float(inp.get("longitude", 0)),
            inp.get("priority", ""),
            decision.get("priority_pred", ""),
            float(decision.get("congestion_score", 0)),
            decision.get("risk_level", ""),
            float(decision.get("cascade_prob", 0)),
            decision.get("cascade_severity", "None"),
            json.dumps(decision.get("nearest_stations", [])),
            json.dumps(decision.get("resource_plan", {})),
            json.dumps(decision.get("diversion_plan", {})),
            decision.get("llm_brief", ""),
            json.dumps(inp),
            "active",
            now,
            now,
        )
        with self._conn() as conn:
            cur = conn.execute(sql, vals)
            row_id = cur.lastrowid

            # Also insert into active_events
            conn.execute(
                """
                INSERT INTO active_events
                  (event_log_id, corridor, zone, police_station,
                   latitude, longitude, risk_level, started_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    row_id,
                    inp.get("corridor", ""),
                    inp.get("zone", ""),
                    inp.get("police_station", ""),
                    float(inp.get("latitude", 0)),
                    float(inp.get("longitude", 0)),
                    decision.get("risk_level", ""),
                    now,
                ),
            )
        return row_id

    def get_recent_events(self, n: int = 20) -> list:
        """Return the n most recent events from events_log."""
        sql = "SELECT * FROM events_log ORDER BY created_at DESC LIMIT ?"
        with self._conn() as conn:
            rows = conn.execute(sql, (n,)).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def set_event_status(self, row_id: int, status: str) -> None:
        """Update status of an event (active / resolved / closed)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE events_log SET status=?, updated_at=? WHERE id=?",
                (status, now, row_id),
            )
            if status in ("resolved", "closed"):
                conn.execute(
                    "DELETE FROM active_events WHERE event_log_id=?", (row_id,)
                )

    def get_event_by_id(self, row_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM events_log WHERE id=?", (row_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    # ------------------------------------------------------------------
    # Active events
    # ------------------------------------------------------------------

    def get_active_events(self) -> list:
        """Return all currently active events (for cascade detection)."""
        sql = """
        SELECT ae.*, el.congestion_score, el.priority_pred, el.event_type,
               el.event_cause, el.cascade_prob
        FROM active_events ae
        JOIN events_log el ON ae.event_log_id = el.id
        ORDER BY ae.started_at DESC
        """
        with self._conn() as conn:
            rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

    def save_feedback(self, event_log_id: int, feedback: dict) -> None:
        """Store post-event officer feedback."""
        now = datetime.now(timezone.utc).isoformat()
        sql = """
        INSERT INTO feedback_log
          (event_log_id, actual_congestion, actual_duration_min,
           officers_deployed, barricades_deployed, diversion_used,
           what_worked, what_didnt, submitted_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """
        vals = (
            event_log_id,
            float(feedback.get("actual_congestion", 0) or 0),
            float(feedback.get("actual_duration_min", 0) or 0),
            int(feedback.get("officers_deployed", 0) or 0),
            int(feedback.get("barricades_deployed", 0) or 0),
            str(feedback.get("diversion_used", "") or ""),
            str(feedback.get("what_worked", "") or ""),
            str(feedback.get("what_didnt", "") or ""),
            now,
        )
        with self._conn() as conn:
            conn.execute(sql, vals)

    def get_feedback(self, event_log_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM feedback_log WHERE event_log_id=? ORDER BY id DESC LIMIT 1",
                (event_log_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_all_feedback(self) -> list:
        sql = """
        SELECT f.*, e.event_type, e.corridor, e.risk_level, e.congestion_score,
               e.priority_actual, e.created_at AS event_created_at
        FROM feedback_log f
        JOIN events_log e ON f.event_log_id = e.id
        ORDER BY f.submitted_at DESC
        """
        with self._conn() as conn:
            rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # KPI summary
    # ------------------------------------------------------------------

    def get_kpi_summary(self) -> dict:
        """Return aggregate KPIs for the command center dashboard."""
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM events_log").fetchone()[0]
            active = conn.execute(
                "SELECT COUNT(*) FROM active_events"
            ).fetchone()[0]
            critical = conn.execute(
                "SELECT COUNT(*) FROM events_log WHERE risk_level='Critical'"
            ).fetchone()[0]
            high = conn.execute(
                "SELECT COUNT(*) FROM events_log WHERE risk_level='High'"
            ).fetchone()[0]
            avg_score = conn.execute(
                "SELECT AVG(congestion_score) FROM events_log"
            ).fetchone()[0]
            feedback_count = conn.execute(
                "SELECT COUNT(*) FROM feedback_log"
            ).fetchone()[0]
            cascade_count = conn.execute(
                "SELECT COUNT(*) FROM events_log WHERE cascade_severity != 'None'"
            ).fetchone()[0]
            corridor_counts = conn.execute(
                "SELECT corridor, COUNT(*) as cnt FROM events_log "
                "GROUP BY corridor ORDER BY cnt DESC LIMIT 5"
            ).fetchall()
            risk_dist = conn.execute(
                "SELECT risk_level, COUNT(*) as cnt FROM events_log GROUP BY risk_level"
            ).fetchall()

        return {
            "total_events": total,
            "active_events": active,
            "critical_events": critical,
            "high_events": high,
            "avg_congestion_score": round(float(avg_score or 0), 1),
            "feedback_submissions": feedback_count,
            "cascade_detections": cascade_count,
            "top_corridors": [dict(r) for r in corridor_counts],
            "risk_distribution": {r["risk_level"]: r["cnt"] for r in risk_dist},
        }

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def clear_old_logs(self, days: int = 30) -> int:
        """Delete events older than `days` days. Returns rows deleted."""
        cutoff = f"datetime('now', '-{days} days')"
        with self._conn() as conn:
            cur = conn.execute(
                f"DELETE FROM events_log WHERE created_at < {cutoff}"
            )
            return cur.rowcount

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row) -> dict:
        if row is None:
            return {}
        d = dict(row)
        for field in ("nearest_ps", "resource_plan", "diversion_plan", "input_json"):
            if d.get(field) and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d
