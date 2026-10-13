"""SQLite persistent storage and cache for Moodle events and reminder history."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Set, Dict, Any
from .models import MoodleEvent
from .config import Config


class Storage:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.db_path = self.config.data_dir / "moodle.db"
        self.ics_export_path = self.config.data_dir / "moodle.ics"
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    uid TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    dtstart TEXT,
                    dtend TEXT,
                    course TEXT,
                    url TEXT,
                    location TEXT,
                    category TEXT,
                    raw_event_type TEXT,
                    last_modified TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS reminder_history (
                    event_uid TEXT,
                    threshold_min INTEGER,
                    notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (event_uid, threshold_min)
                );

                CREATE INDEX IF NOT EXISTS idx_events_dtend ON events(dtend);
                CREATE INDEX IF NOT EXISTS idx_events_dtstart ON events(dtstart);
            """)

    def save_events(self, events: List[MoodleEvent], raw_ics: Optional[str] = None):
        """Save parsed events and optionally export raw .ics file for external calendar integration."""
        with self._get_connection() as conn:
            # We insert or replace incoming events
            cur = conn.cursor()
            for e in events:
                cur.execute("""
                    INSERT OR REPLACE INTO events (
                        uid, title, description, dtstart, dtend, course, url,
                        location, category, raw_event_type, last_modified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    e.uid,
                    e.title,
                    e.description,
                    e.dtstart.isoformat() if e.dtstart else None,
                    e.dtend.isoformat() if e.dtend else None,
                    e.course,
                    e.url,
                    e.location,
                    e.category,
                    e.raw_event_type,
                    e.last_modified.isoformat() if e.last_modified else None,
                ))

            # Also clean up events that no longer exist in the feed (optional, keep recent)
            if events:
                placeholders = ",".join("?" for _ in events)
                uids = [e.uid for e in events]
                cur.execute(f"DELETE FROM events WHERE uid NOT IN ({placeholders})", uids)

            conn.commit()

        # Save copy of raw .ics file
        if raw_ics:
            try:
                self.ics_export_path.write_text(raw_ics, encoding="utf-8")
            except Exception as ex:
                print(f"Warning: Failed to save moodle.ics export: {ex}")

    def get_all_events(self) -> List[MoodleEvent]:
        """Retrieve all events sorted by deadline."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM events")
            rows = cur.fetchall()

        events = []
        for r in rows:
            events.append(self._row_to_event(r))

        events.sort(key=lambda e: (e.deadline is None, e.deadline))
        return events

    def get_upcoming_events(self, limit: Optional[int] = None) -> List[MoodleEvent]:
        """Get events that have deadlines in the future or within the last 2 hours."""
        all_events = self.get_all_events()
        now = datetime.now().astimezone()

        upcoming = []
        for e in all_events:
            if not e.deadline:
                continue
            # Include events up to 2 hours overdue so user can see recent completed/pending tasks
            diff = (e.deadline - now).total_seconds()
            if diff >= -7200:
                upcoming.append(e)

        if limit:
            return upcoming[:limit]
        return upcoming

    def get_events_for_date(self, target_date) -> List[MoodleEvent]:
        """Get events that fall on a specific date (year, month, day)."""
        all_events = self.get_all_events()
        matching = []
        for e in all_events:
            if e.deadline and e.deadline.date() == target_date:
                matching.append(e)
        return matching

    def get_marked_days_for_month(self, year: int, month: int) -> Set[int]:
        """Return the set of days (day of month, 1-31) that have deadlines in this month."""
        all_events = self.get_all_events()
        days = set()
        for e in all_events:
            if e.deadline and e.deadline.year == year and e.deadline.month == month:
                days.add(e.deadline.day)
        return days

    def is_reminder_sent(self, event_uid: str, threshold_min: int) -> bool:
        """Check if notification has already been triggered for this event at this threshold."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 1 FROM reminder_history
                WHERE event_uid = ? AND threshold_min = ?
            """, (event_uid, threshold_min))
            return cur.fetchone() is not None

    def mark_reminder_sent(self, event_uid: str, threshold_min: int):
        """Record that a reminder was sent for this event at this threshold."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO reminder_history (event_uid, threshold_min)
                VALUES (?, ?)
            """, (event_uid, threshold_min))
            conn.commit()

    def _row_to_event(self, r: sqlite3.Row) -> MoodleEvent:
        return MoodleEvent(
            uid=r["uid"],
            title=r["title"] or "",
            description=r["description"] or "",
            dtstart=datetime.fromisoformat(r["dtstart"]) if r["dtstart"] else None,
            dtend=datetime.fromisoformat(r["dtend"]) if r["dtend"] else None,
            course=r["course"] or "General",
            url=r["url"] or "",
            location=r["location"] or "",
            category=r["category"] or "",
            raw_event_type=r["raw_event_type"] or "",
            last_modified=datetime.fromisoformat(r["last_modified"]) if r["last_modified"] else None,
        )
