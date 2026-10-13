import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any


@dataclass
class MoodleEvent:
    uid: str
    title: str
    description: str = ""
    dtstart: Optional[datetime] = None
    dtend: Optional[datetime] = None
    course: str = ""
    url: str = ""
    location: str = ""
    category: str = ""
    raw_event_type: str = ""
    last_modified: Optional[datetime] = None

    @property
    def clean_course(self) -> str:
        """Return human-friendly course name without internal university codes."""
        if not self.course:
            return "General"
        cleaned = self.course
        # Remove leading department/campus prefixes like 'BAQ ', 'BOG ', 'DEP - '
        cleaned = re.sub(r'^(?:[A-Z]{2,4}\s+)?(?:DEP\s*-\s*)?', '', cleaned)
        # Remove trailing course code / section / year numbers like ' - 11356 - T01 - 2026 - 2'
        cleaned = re.sub(r'\s*-\s*\d+.*$', '', cleaned)
        return cleaned.strip() or self.course

    @property
    def deadline(self) -> Optional[datetime]:
        """Return the effective deadline (dtend or dtstart)."""
        return self.dtend or self.dtstart

    @property
    def is_all_day(self) -> bool:
        """Check if event is all-day (time is midnight to midnight or no time)."""
        if not self.deadline:
            return False
        return self.deadline.hour == 0 and self.deadline.minute == 0 and self.deadline.second == 0

    @property
    def status(self) -> str:
        """Return urgency status: overdue, today, soon, upcoming."""
        if not self.deadline:
            return "unknown"
        now = datetime.now().astimezone()
        diff = self.deadline - now
        seconds = diff.total_seconds()
        if seconds < 0:
            return "overdue"
        elif seconds <= 86400 and self.deadline.date() == now.date():
            return "today"
        elif seconds <= 86400 * 2:
            return "soon"
        else:
            return "upcoming"

    @property
    def time_remaining_str(self) -> str:
        """Human-readable time remaining string."""
        if not self.deadline:
            return "No date"
        now = datetime.now().astimezone()
        diff = self.deadline - now
        total_seconds = int(diff.total_seconds())

        if total_seconds < 0:
            past_sec = abs(total_seconds)
            if past_sec < 3600:
                mins = past_sec // 60
                return f"Overdue by {mins}m"
            elif past_sec < 86400:
                hours = past_sec // 3600
                return f"Overdue by {hours}h"
            else:
                days = past_sec // 86400
                return f"Overdue by {days}d"

        if total_seconds < 3600:
            mins = total_seconds // 60
            return f"In {mins} min{'s' if mins != 1 else ''}"
        elif total_seconds < 86400:
            hours = total_seconds // 3600
            mins = (total_seconds % 3600) // 60
            if mins > 0:
                return f"In {hours}h {mins}m"
            return f"In {hours}h"
        elif total_seconds < 86400 * 2:
            return f"Tomorrow at {self.deadline.strftime('%H:%M')}"
        else:
            days = total_seconds // 86400
            return f"In {days} days ({self.deadline.strftime('%b %d')})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uid": self.uid,
            "title": self.title,
            "description": self.description,
            "dtstart": self.dtstart.isoformat() if self.dtstart else None,
            "dtend": self.dtend.isoformat() if self.dtend else None,
            "course": self.course,
            "url": self.url,
            "location": self.location,
            "category": self.category,
            "raw_event_type": self.raw_event_type,
            "last_modified": self.last_modified.isoformat() if self.last_modified else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MoodleEvent":
        dtstart = datetime.fromisoformat(data["dtstart"]) if data.get("dtstart") else None
        dtend = datetime.fromisoformat(data["dtend"]) if data.get("dtend") else None
        last_modified = datetime.fromisoformat(data["last_modified"]) if data.get("last_modified") else None
        return cls(
            uid=data["uid"],
            title=data.get("title", ""),
            description=data.get("description", ""),
            dtstart=dtstart,
            dtend=dtend,
            course=data.get("course", ""),
            url=data.get("url", ""),
            location=data.get("location", ""),
            category=data.get("category", ""),
            raw_event_type=data.get("raw_event_type", ""),
            last_modified=last_modified,
        )
