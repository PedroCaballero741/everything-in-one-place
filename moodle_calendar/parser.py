"""RFC 5545 iCalendar (.ics) parser customized for Moodle university calendar exports."""
import re
import html
from datetime import datetime, timezone, date, time
from typing import List, Dict, Optional, Tuple
from .models import MoodleEvent


class IcsParser:
    """Parses iCalendar .ics feeds exported from Moodle."""

    @staticmethod
    def unfold_lines(text: str) -> List[str]:
        """Unfold RFC 5545 folded lines (lines starting with space or tab)."""
        raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        unfolded: List[str] = []
        for line in raw_lines:
            if not line:
                continue
            if (line.startswith(" ") or line.startswith("\t")) and unfolded:
                unfolded[-1] += line[1:]
            else:
                unfolded.append(line)
        return unfolded

    @staticmethod
    def unescape_ics_text(val: str) -> str:
        """Unescape RFC 5545 text escapes: \\n, \\,, \\;, \\\\."""
        val = val.replace(r"\n", "\n").replace(r"\N", "\n")
        val = val.replace(r"\,", ",").replace(r"\;", ";")
        val = val.replace(r"\\", "\\")
        return val.strip()

    @staticmethod
    def clean_html(raw_html: str) -> str:
        """Strip HTML tags and unescape HTML entities commonly found in Moodle descriptions."""
        if not raw_html:
            return ""
        # Convert <br>, <br/>, <p> to newlines
        text = re.sub(r"<(?:br\s*/?|/p|/div)>", "\n", raw_html, flags=re.IGNORECASE)
        # Strip all other HTML tags
        text = re.sub(r"<[^>]+>", "", text)
        # Unescape HTML entities (&amp;, &nbsp;, &oacute;, etc.)
        text = html.unescape(text)
        # Collapse excessive newlines/spaces
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text

    @classmethod
    def parse_datetime(cls, dt_str: str, params: Dict[str, str]) -> Optional[datetime]:
        """
        Parse iCalendar date/datetime string into a timezone-aware datetime in the local timezone.
        Handles:
          - 20261015T180000Z (UTC)
          - 20261015T180000 (Local / floating)
          - 20261015 (Date-only)
          - TZID parameters
        """
        dt_str = dt_str.strip()
        local_tz = datetime.now().astimezone().tzinfo

        try:
            # 1. UTC format: 20261015T180000Z
            if dt_str.endswith("Z"):
                parsed = datetime.strptime(dt_str, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                return parsed.astimezone(local_tz)

            # 2. Date with time: 20261015T180000
            if "T" in dt_str:
                # Handle possible fractional seconds or standard format
                time_part = dt_str.split("T")[1]
                if len(time_part) == 6:
                    parsed = datetime.strptime(dt_str, "%Y%m%dT%H%M%S")
                else:
                    parsed = datetime.strptime(dt_str[:15], "%Y%m%dT%H%M%S")
                # Attach local timezone
                return parsed.replace(tzinfo=local_tz)

            # 3. Date only: 20261015 (All day event)
            if len(dt_str) == 8 and dt_str.isdigit():
                d = datetime.strptime(dt_str, "%Y%m%d").date()
                # Represent as end of that day (23:59:59) for deadline purposes
                return datetime.combine(d, time(23, 59, 59), tzinfo=local_tz)

        except Exception:
            pass

        return None

    @classmethod
    def parse_property(cls, line: str) -> Tuple[str, Dict[str, str], str]:
        """Split line into (name, parameters, value)."""
        colon_idx = line.find(":")
        if colon_idx == -1:
            return "", {}, ""

        prop_spec = line[:colon_idx]
        val = line[colon_idx + 1 :]

        parts = prop_spec.split(";")
        prop_name = parts[0].upper().strip()
        params: Dict[str, str] = {}

        for p in parts[1:]:
            if "=" in p:
                k, v = p.split("=", 1)
                params[k.upper().strip()] = v.strip('"')

        return prop_name, params, val

    @classmethod
    def extract_course(cls, category: str, summary: str, description: str) -> str:
        """
        Extract course name from CATEGORIES, DESCRIPTION, or SUMMARY.
        Moodle often puts the course name in CATEGORIES, or in description as 'Course: Name' / 'Curso: Name'.
        """
        if category:
            return category.strip()

        # Look in description for "Course: ..." or "Curso: ..."
        course_match = re.search(r"(?:Course|Curso):\s*([^\n\r<]+)", description, re.IGNORECASE)
        if course_match:
            return course_match.group(1).strip()

        # Look for [Course Name] prefix in summary
        summary_match = re.search(r"^\[(.*?)\]", summary)
        if summary_match:
            return summary_match.group(1).strip()

        return "General"

    @classmethod
    def parse(cls, ics_content: str) -> List[MoodleEvent]:
        """Parse raw .ics text content into a list of MoodleEvent objects."""
        lines = cls.unfold_lines(ics_content)
        events: List[MoodleEvent] = []
        in_event = False
        current_data: Dict[str, Any] = {}

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.upper() == "BEGIN:VEVENT":
                in_event = True
                current_data = {}
                continue
            elif line.upper() == "END:VEVENT":
                if in_event and current_data.get("uid"):
                    summary = cls.unescape_ics_text(current_data.get("summary", "Untitled Assignment"))
                    raw_desc = cls.unescape_ics_text(current_data.get("description", ""))
                    clean_desc = cls.clean_html(raw_desc)
                    cat = cls.unescape_ics_text(current_data.get("categories", ""))
                    course = cls.extract_course(cat, summary, raw_desc)
                    url = current_data.get("url", "")

                    # Fallback URL extraction from description if URL field is empty
                    if not url:
                        url_match = re.search(r"https?://[^\s\"'<>]+", raw_desc)
                        if url_match:
                            url = url_match.group(0)

                    event = MoodleEvent(
                        uid=current_data["uid"],
                        title=summary,
                        description=clean_desc,
                        dtstart=current_data.get("dtstart"),
                        dtend=current_data.get("dtend"),
                        course=course,
                        url=url,
                        location=cls.unescape_ics_text(current_data.get("location", "")),
                        category=cat,
                        last_modified=current_data.get("last_modified"),
                    )
                    events.append(event)
                in_event = False
                continue

            if in_event:
                prop_name, params, raw_val = cls.parse_property(line)
                if not prop_name:
                    continue

                if prop_name == "UID":
                    current_data["uid"] = raw_val.strip()
                elif prop_name == "SUMMARY":
                    current_data["summary"] = raw_val
                elif prop_name == "DESCRIPTION":
                    current_data["description"] = raw_val
                elif prop_name == "DTSTART":
                    current_data["dtstart"] = cls.parse_datetime(raw_val, params)
                elif prop_name == "DTEND":
                    current_data["dtend"] = cls.parse_datetime(raw_val, params)
                elif prop_name == "CATEGORIES":
                    current_data["categories"] = raw_val
                elif prop_name == "URL":
                    current_data["url"] = raw_val.strip()
                elif prop_name == "LOCATION":
                    current_data["location"] = raw_val
                elif prop_name == "LAST-MODIFIED":
                    current_data["last_modified"] = cls.parse_datetime(raw_val, params)

        # Sort events by deadline (dtend or dtstart)
        events.sort(key=lambda e: (e.deadline is None, e.deadline))
        return events
