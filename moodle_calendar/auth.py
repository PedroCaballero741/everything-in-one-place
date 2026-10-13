"""University Moodle authentication and automated calendar extraction.
Supports direct credentials login (Mobile token & Web session) and in-app WebKit login.
"""
import re
import ssl
import json
import urllib.request
import urllib.parse
import http.cookiejar
from datetime import datetime, timezone
from typing import Tuple, Optional, List, Dict, Any

from .models import MoodleEvent
from .config import Config
from .storage import Storage
from .parser import IcsParser


def clean_base_url(raw_url: str) -> str:
    """Normalize input URL like 'https://moodle.university.edu/login/index.php' to 'https://moodle.university.edu'."""
    url = raw_url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    parsed = urllib.parse.urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    # If path has a subfolder before /login/index.php, preserve the moodle root directory
    path = parsed.path
    if "/login/" in path:
        subpath = path.split("/login/")[0]
        base = base + subpath
    elif path.endswith(".php"):
        # e.g. /index.php
        subpath = "/".join(path.rstrip("/").split("/")[:-1])
        if subpath:
            base = base + subpath

    return base.rstrip("/")


class MoodleAuthClient:
    """Handles logging into any university Moodle portal and retrieving calendar feeds."""

    def __init__(self, config: Optional[Config] = None, storage: Optional[Storage] = None):
        self.config = config or Config()
        self.storage = storage or Storage(self.config)
        self.ssl_context = ssl.create_default_context()

    def login_with_credentials(
        self, site_url: str, username: str, password: str
    ) -> Tuple[bool, int, str, str]:
        """
        Attempts to authenticate using both Moodle Mobile Token API and Web Session,
        then extracts the user's permanent calendar export URL and events.
        
        Returns: (success: bool, events_count: int, message: str, calendar_url: str)
        """
        base_url = clean_base_url(site_url)
        if not username or not password:
            return False, 0, "Username and password cannot be empty.", ""

        # Strategy 1: Attempt Moodle Mobile Token API
        token_success, token_count, token_err, events_from_api = self._try_token_login(
            base_url, username, password
        )

        # Strategy 2: Attempt Web Session Login to extract permanent iCal export URL
        session_success, session_count, session_err, calendar_url, events_from_ics = (
            self._try_session_login_and_export_url(base_url, username, password)
        )

        if calendar_url:
            self.config.moodle_url = calendar_url
            if events_from_ics:
                self.storage.save_events(events_from_ics)
                self.config.set_sync_result("success", "")
                return True, len(events_from_ics), "Connected successfully via calendar export URL!", calendar_url
            elif events_from_api:
                self.storage.save_events(events_from_api)
                self.config.set_sync_result("success", "")
                return True, len(events_from_api), "Connected successfully!", calendar_url
            else:
                return True, 0, "Connected! Calendar URL obtained (no upcoming deadlines right now).", calendar_url

        if token_success:
            self.config.university_url = base_url
            self.config.username = username
            if events_from_api:
                self.storage.save_events(events_from_api)
            self.config.set_sync_result("success", "")
            return True, len(events_from_api), "Connected successfully via Moodle Web Services API!", ""

        # If both failed, format a clear error message
        err_msg = session_err or token_err or "Invalid username or password. Please verify your credentials."
        self.config.set_sync_result("error", err_msg)
        return False, 0, err_msg, ""

    def _try_token_login(
        self, base_url: str, username: str, password: str
    ) -> Tuple[bool, int, str, List[MoodleEvent]]:
        """Try authenticating against /login/token.php."""
        token_url = f"{base_url}/login/token.php"
        data = urllib.parse.urlencode({
            "service": "moodle_mobile_app",
            "username": username,
            "password": password,
        }).encode("utf-8")

        req = urllib.request.Request(
            token_url,
            data=data,
            headers={
                "User-Agent": "MoodleMobile/4.0 (Linux)",
                "Accept": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=15, context=self.ssl_context) as resp:
                result = json.loads(resp.read().decode("utf-8", errors="replace"))

            if "token" in result:
                token = result["token"]
                self.config.wstoken = token
                self.config.university_url = base_url
                self.config.username = username
                events = self._fetch_events_via_wstoken(base_url, token)
                return True, len(events), "", events
            elif "error" in result:
                return False, 0, result["error"], []
        except Exception as e:
            return False, 0, str(e), []

        return False, 0, "No token returned", []

    def _fetch_events_via_wstoken(self, base_url: str, wstoken: str) -> List[MoodleEvent]:
        """Fetch upcoming deadlines using Moodle Web Services REST API."""
        events: List[MoodleEvent] = []
        now = datetime.now().astimezone()

        ws_url = f"{base_url}/webservice/rest/server.php"
        params = urllib.parse.urlencode({
            "wstoken": wstoken,
            "wsfunction": "core_calendar_get_action_events_by_timesort",
            "moodlewsrestformat": "json",
            "timesortfrom": int(now.timestamp()) - 86400,  # from 1 day ago
            "limitnum": 50,
        })

        req = urllib.request.Request(
            f"{ws_url}?{params}",
            headers={"User-Agent": "MoodleDesktop/1.0", "Accept": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=15, context=self.ssl_context) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))

            raw_events = data.get("events", [])
            for rev in raw_events:
                uid = f"ws-{rev.get('id', '')}@{urllib.parse.urlparse(base_url).netloc}"
                title = rev.get("name", "Untitled Task")
                desc = IcsParser.clean_html(rev.get("description", ""))
                course_info = rev.get("course", {})
                course_name = course_info.get("fullname") or course_info.get("shortname") or "General"
                url = rev.get("url") or (rev.get("action", {}) or {}).get("url") or ""

                timesort = rev.get("timesort") or rev.get("timestart")
                dt = datetime.fromtimestamp(timesort, tz=timezone.utc).astimezone(now.tzinfo) if timesort else None

                event = MoodleEvent(
                    uid=uid,
                    title=title,
                    description=desc,
                    dtstart=dt,
                    dtend=dt,
                    course=course_name,
                    url=url,
                    category=course_name,
                )
                events.append(event)
        except Exception as ex:
            print(f"Warning: Failed to fetch events via wstoken: {ex}")

        return events

    def _try_session_login_and_export_url(
        self, base_url: str, username: str, password: str
    ) -> Tuple[bool, int, str, str, List[MoodleEvent]]:
        """
        Log into Moodle web session, access calendar/export.php, and extract the permanent iCal URL.
        """
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cj),
            urllib.request.HTTPSHandler(context=self.ssl_context),
        )

        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        login_url = f"{base_url}/login/index.php"

        # Step 1: GET login page to obtain logintoken
        try:
            req1 = urllib.request.Request(login_url, headers=headers)
            with opener.open(req1, timeout=15) as r1:
                html1 = r1.read().decode("utf-8", errors="replace")
        except Exception as e:
            return False, 0, f"Cannot connect to university portal: {e}", "", []

        token_match = re.search(r'name=["\']logintoken["\']\s+value=["\']([^"\']+)["\']', html1)
        logintoken = token_match.group(1) if token_match else ""

        # Step 2: POST credentials
        post_data = urllib.parse.urlencode({
            "anchor": "",
            "logintoken": logintoken,
            "username": username,
            "password": password,
        }).encode("utf-8")

        post_headers = headers.copy()
        post_headers["Referer"] = login_url
        post_headers["Content-Type"] = "application/x-www-form-urlencoded"

        try:
            req2 = urllib.request.Request(login_url, data=post_data, headers=post_headers)
            with opener.open(req2, timeout=20) as r2:
                final_url = r2.geturl()
                html2 = r2.read().decode("utf-8", errors="replace")
        except Exception as e:
            return False, 0, f"Error submitting login form: {e}", "", []

        # Check if login failed (still on login/index.php or error message present)
        if "/login/index.php" in final_url and ("invalidlogin" in html2 or "errormsg" in html2 or "Datos erróneos" in html2):
            return False, 0, "Acceso inválido: Usuario o contraseña incorrectos.", "", []

        # Step 3: Access /calendar/export.php
        export_page_url = f"{base_url}/calendar/export.php"
        try:
            req3 = urllib.request.Request(export_page_url, headers=headers)
            with opener.open(req3, timeout=15) as r3:
                export_html = r3.read().decode("utf-8", errors="replace")
        except Exception as e:
            return False, 0, f"Failed to access calendar export page: {e}", "", []

        # Find sesskey in export page if present
        sesskey_match = re.search(r'name=["\']sesskey["\']\s+value=["\']([^"\']+)["\']', export_html)
        sesskey = sesskey_match.group(1) if sesskey_match else ""

        # Step 4: Submit export form to generate URL or download
        # Usually submitting: events[exportevents]=all & period[timeperiod]=recentupcoming & generateurl=1
        export_post_data = urllib.parse.urlencode({
            "sesskey": sesskey,
            "_qf__core_calendar_export_form": "1",
            "events[exportevents]": "all",
            "period[timeperiod]": "recentupcoming",
            "generateurl": "1",
        }).encode("utf-8")

        try:
            req4 = urllib.request.Request(export_page_url, data=export_post_data, headers=post_headers)
            with opener.open(req4, timeout=15) as r4:
                resp_html = r4.read().decode("utf-8", errors="replace")
        except Exception as e:
            resp_html = export_html

        # Step 5: Look for export_execute.php URL in resp_html or export_html
        cal_url = self._extract_calendar_url(resp_html) or self._extract_calendar_url(export_html)

        if cal_url:
            # If relative, prepend base_url
            if cal_url.startswith("/"):
                cal_url = base_url + cal_url
            elif not cal_url.startswith("http"):
                cal_url = f"{base_url}/{cal_url}"

            # Fetch events right now using this URL
            try:
                req_cal = urllib.request.Request(cal_url, headers={"User-Agent": "MoodleDesktop/1.0"})
                with urllib.request.urlopen(req_cal, timeout=15, context=self.ssl_context) as r_cal:
                    ics_data = r_cal.read().decode("utf-8", errors="replace")
                    events = IcsParser.parse(ics_data)
                    return True, len(events), "", cal_url, events
            except Exception:
                return True, 0, "", cal_url, []

        return False, 0, "Could not locate calendar export URL.", "", []

    def _extract_calendar_url(self, html_text: str) -> Optional[str]:
        """Regex search for Moodle's export_execute.php URL in HTML."""
        # Pattern 1: in value="..." attribute or href="..."
        matches = re.findall(r'(https?://[^\s"\'<>]+/calendar/export_execute\.php\?[^\s"\'<>]+)', html_text)
        if matches:
            return matches[0].replace("&amp;", "&")

        # Pattern 2: relative path
        rel_matches = re.findall(r'(/calendar/export_execute\.php\?[^\s"\'<>]+)', html_text)
        if rel_matches:
            return rel_matches[0].replace("&amp;", "&")

        return None
