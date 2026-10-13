"""Calendar synchronization engine: fetches Moodle iCalendar feed and updates cache."""
import urllib.request
import urllib.error
import ssl
from pathlib import Path
from typing import Tuple, Optional, List
from .models import MoodleEvent
from .parser import IcsParser
from .storage import Storage
from .config import Config


class MoodleSyncEngine:
    def __init__(self, config: Optional[Config] = None, storage: Optional[Storage] = None):
        self.config = config or Config()
        self.storage = storage or Storage(self.config)

    def fetch_feed(self, url_or_path: str) -> Tuple[bool, str, str]:
        """
        Fetch iCalendar data from a URL or local file path.
        Returns: (success, content, error_message)
        """
        target = url_or_path.strip()
        if not target:
            return False, "", "No calendar URL configured."

        # Support webcal:// scheme
        if target.startswith("webcal://"):
            target = "https://" + target[len("webcal://") :]

        # Local file support
        if target.startswith("file://") or Path(target).is_file():
            path_str = target.replace("file://", "")
            try:
                content = Path(path_str).read_text(encoding="utf-8")
                return True, content, ""
            except Exception as e:
                return False, "", f"Failed to read file: {e}"

        # HTTP/HTTPS Fetch
        req = urllib.request.Request(
            target,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0 MoodleDesktopCalendar/1.0",
                "Accept": "text/calendar, text/plain, */*",
            },
        )

        # Build SSL context with system CA certificates
        ctx = ssl.create_default_context()

        try:
            with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
                raw_bytes = resp.read()
                # Determine charset or default to utf-8
                charset = resp.headers.get_content_charset() or "utf-8"
                content = raw_bytes.decode(charset, errors="replace")
                return True, content, ""
        except urllib.error.HTTPError as e:
            return False, "", f"HTTP error {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            return False, "", f"Network connection error: {e.reason}"
        except Exception as e:
            return False, "", f"Unexpected error during sync: {e}"

    def sync(self, override_url: Optional[str] = None) -> Tuple[bool, int, str]:
        """
        Perform a full sync: fetch, parse, persist, and update status.
        Supports both iCal feed URLs and Moodle Web Services token sync.
        Returns: (success, events_count, error_message)
        """
        url = override_url or self.config.moodle_url

        # 1. Direct iCal URL sync
        if url:
            success, content, error = self.fetch_feed(url)
            if not success:
                self.config.set_sync_result("error", error)
                return False, 0, error

            if "BEGIN:VCALENDAR" not in content.upper():
                err_msg = "Fetched content is not a valid iCalendar feed. Check the URL."
                self.config.set_sync_result("error", err_msg)
                return False, 0, err_msg

            try:
                events = IcsParser.parse(content)
                self.storage.save_events(events, raw_ics=content)
                self.config.set_sync_result("success", "")
                return True, len(events), ""
            except Exception as e:
                err_msg = f"Failed to parse calendar events: {e}"
                self.config.set_sync_result("error", err_msg)
                return False, 0, err_msg

        # 2. University Portal Web Services API sync
        if self.config.university_url and self.config.wstoken:
            try:
                from .auth import MoodleAuthClient
                auth_client = MoodleAuthClient(self.config, self.storage)
                events = auth_client._fetch_events_via_wstoken(self.config.university_url, self.config.wstoken)
                self.storage.save_events(events)
                self.config.set_sync_result("success", "")
                return True, len(events), ""
            except Exception as e:
                err_msg = f"Portal API sync failed: {e}"
                self.config.set_sync_result("error", err_msg)
                return False, 0, err_msg

        msg = "No calendar feed URL or portal account configured. Please configure in settings."
        self.config.set_sync_result("error", msg)
        return False, 0, msg
