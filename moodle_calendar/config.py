"""Configuration management for Moodle Calendar & Reminders."""
import json
import os
from pathlib import Path
from typing import List, Dict, Any


DEFAULT_THRESHOLDS = [1440, 180, 30]  # 24 hours, 3 hours, 30 minutes before deadline


class Config:
    def __init__(self):
        self.config_dir = Path.home() / ".config" / "moodle-desktop-calendar"
        self.config_file = self.config_dir / "config.json"
        self.data_dir = Path.home() / ".local" / "share" / "moodle-desktop-calendar"

        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._data: Dict[str, Any] = {
            "university_url": "",
            "username": "",
            "wstoken": "",
            "moodle_url": "",
            "sync_interval_minutes": 30,
            "reminder_thresholds": DEFAULT_THRESHOLDS,
            "enable_notifications": True,
            "autostart_daemon": True,
            "window_width": 460,
            "window_height": 720,
            "window_always_on_top": False,
            "last_sync_time": None,
            "last_sync_status": "none",
            "last_sync_error": "",
        }
        self.load()

    @property
    def university_url(self) -> str:
        return self._data.get("university_url", "")

    @university_url.setter
    def university_url(self, val: str):
        self._data["university_url"] = val.strip()
        self.save()

    @property
    def username(self) -> str:
        return self._data.get("username", "")

    @username.setter
    def username(self, val: str):
        self._data["username"] = val.strip()
        self.save()

    @property
    def wstoken(self) -> str:
        return self._data.get("wstoken", "")

    @wstoken.setter
    def wstoken(self, val: str):
        self._data["wstoken"] = val.strip()
        self.save()

    @property
    def is_configured(self) -> bool:
        return bool(self.moodle_url or (self.university_url and (self.wstoken or self.username)))

    def load(self):
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self._data.update(saved)
            except Exception as e:
                print(f"Warning: Failed to load config: {e}")

    def save(self):
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving config: {e}")

    @property
    def moodle_url(self) -> str:
        return self._data.get("moodle_url", "")

    @moodle_url.setter
    def moodle_url(self, val: str):
        self._data["moodle_url"] = val.strip()
        self.save()

    @property
    def sync_interval_minutes(self) -> int:
        return int(self._data.get("sync_interval_minutes", 30))

    @sync_interval_minutes.setter
    def sync_interval_minutes(self, val: int):
        self._data["sync_interval_minutes"] = max(5, int(val))
        self.save()

    @property
    def reminder_thresholds(self) -> List[int]:
        return self._data.get("reminder_thresholds", DEFAULT_THRESHOLDS)

    @reminder_thresholds.setter
    def reminder_thresholds(self, val: List[int]):
        self._data["reminder_thresholds"] = sorted([int(x) for x in val], reverse=True)
        self.save()

    @property
    def enable_notifications(self) -> bool:
        return bool(self._data.get("enable_notifications", True))

    @enable_notifications.setter
    def enable_notifications(self, val: bool):
        self._data["enable_notifications"] = val
        self.save()

    @property
    def autostart_daemon(self) -> bool:
        return bool(self._data.get("autostart_daemon", True))

    @autostart_daemon.setter
    def autostart_daemon(self, val: bool):
        self._data["autostart_daemon"] = val
        self.save()

    @property
    def window_always_on_top(self) -> bool:
        return bool(self._data.get("window_always_on_top", False))

    @window_always_on_top.setter
    def window_always_on_top(self, val: bool):
        self._data["window_always_on_top"] = val
        self.save()

    @property
    def last_sync_time(self) -> Optional[str]:
        return self._data.get("last_sync_time")

    def set_sync_result(self, status: str, error: str = ""):
        from datetime import datetime
        self._data["last_sync_time"] = datetime.now().astimezone().isoformat()
        self._data["last_sync_status"] = status
        self._data["last_sync_error"] = error
        self.save()

    @property
    def last_sync_status(self) -> str:
        return self._data.get("last_sync_status", "none")

    @property
    def last_sync_error(self) -> str:
        return self._data.get("last_sync_error", "")
