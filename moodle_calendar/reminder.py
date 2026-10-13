"""Reminder engine: checks upcoming deadlines and dispatches system notifications."""
import subprocess
import threading
import time
from datetime import datetime
from typing import Optional, List, Dict
from pathlib import Path
from .models import MoodleEvent
from .storage import Storage
from .config import Config


class ReminderNotifier:
    def __init__(self, config: Optional[Config] = None, storage: Optional[Storage] = None):
        self.config = config or Config()
        self.storage = storage or Storage(self.config)

    def format_threshold_label(self, minutes: int) -> str:
        """Human label for a threshold: e.g. 1440 -> 24 hours."""
        if minutes >= 1440:
            days = minutes // 1440
            return f"{days} day{'s' if days > 1 else ''}"
        elif minutes >= 60:
            hours = minutes // 60
            return f"{hours} hour{'s' if hours > 1 else ''}"
        else:
            return f"{minutes} minute{'s' if minutes > 1 else ''}"

    def send_notification(self, event: MoodleEvent, threshold_min: int) -> bool:
        """Dispatch a desktop notification using notify-send."""
        if not self.config.enable_notifications:
            return False

        urgency = "critical" if threshold_min <= 60 else "normal"
        time_label = self.format_threshold_label(threshold_min)

        summary = f"Due in {time_label}: {event.title}"
        body_lines = [
            f"Course: {event.clean_course}",
            f"Deadline: {event.deadline.strftime('%A, %b %d at %H:%M') if event.deadline else 'Soon'}",
        ]

        if event.description:
            # First line or short preview of description
            desc_preview = event.description.split("\n")[0][:120]
            if desc_preview:
                body_lines.append(f"{desc_preview}")

        if event.url:
            body_lines.append(f"Moodle: {event.url}")

        body = "\n".join(body_lines)

        # Check if custom icon exists
        icon_path = Path(__file__).parent.parent / "assets" / "moodle-calendar.png"
        icon_name = str(icon_path) if icon_path.exists() else "appointment-soon"

        # Action handling in background thread if URL exists
        def _dispatch():
            cmd = [
                "notify-send",
                "-a", "Moodle Calendar",
                "-i", icon_name,
                "-u", urgency,
            ]

            if event.url:
                # Try with action button to open Moodle
                action_cmd = cmd + [
                    "-A", "open=Open in Moodle",
                    summary,
                    body,
                ]
                try:
                    res = subprocess.run(action_cmd, capture_output=True, text=True, timeout=25)
                    if res.returncode == 0 and "open" in res.stdout:
                        subprocess.Popen(["xdg-open", event.url])
                    return
                except (subprocess.TimeoutExpired, Exception):
                    # Fallback to standard notification without action
                    pass

            # Standard notification fallback
            try:
                subprocess.run(cmd + [summary, body], check=False)
            except Exception as e:
                print(f"Error sending notification: {e}")

        # Run in separate thread to avoid blocking caller
        thread = threading.Thread(target=_dispatch, daemon=True)
        thread.start()
        return True

    def check_and_notify(self) -> int:
        """
        Check all upcoming events against configured reminder thresholds.
        Returns the number of notifications triggered.
        """
        if not self.config.enable_notifications:
            return 0

        now = datetime.now().astimezone()
        thresholds = sorted(self.config.reminder_thresholds, reverse=True)
        events = self.storage.get_upcoming_events()
        notifications_sent = 0

        for event in events:
            if not event.deadline:
                continue

            # Remaining seconds until deadline
            time_until_deadline = (event.deadline - now).total_seconds()
            # If past deadline by more than 5 minutes, do not notify
            if time_until_deadline < -300:
                continue

            remaining_minutes = time_until_deadline / 60.0

            for threshold in thresholds:
                # Trigger if remaining time is within this threshold
                # Example: for 30m threshold, trigger when remaining_minutes <= 30
                if remaining_minutes <= threshold:
                    # Check if already sent
                    if not self.storage.is_reminder_sent(event.uid, threshold):
                        self.send_notification(event, threshold)
                        self.storage.mark_reminder_sent(event.uid, threshold)
                        notifications_sent += 1

        return notifications_sent

    def run_loop(self, poll_interval: int = 60, sync_engine=None):
        """
        Continuous loop for background daemon mode.
        Checks reminders every `poll_interval` seconds and performs periodic sync.
        """
        last_sync_check = 0
        sync_interval_sec = self.config.sync_interval_minutes * 60

        print(f"Moodle Reminder Daemon started. Polling every {poll_interval}s, sync every {self.config.sync_interval_minutes}m.")
        while True:
            try:
                # Check reminders
                sent = self.check_and_notify()
                if sent > 0:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Dispatched {sent} reminder notification(s).")

                # Periodic sync
                current_time = time.time()
                if sync_engine and (current_time - last_sync_check >= sync_interval_sec):
                    last_sync_check = current_time
                    success, count, err = sync_engine.sync()
                    if success:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Auto-sync successful: {count} events updated.")
                    else:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Auto-sync warning: {err}")

            except Exception as e:
                print(f"Daemon error: {e}")

            time.sleep(poll_interval)
