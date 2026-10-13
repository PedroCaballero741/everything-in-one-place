"""Systemd user service and Desktop integration manager for Moodle Calendar & Reminders."""
import sys
import shutil
import subprocess
from pathlib import Path
from typing import Tuple


PROJECT_DIR = Path(__file__).parent.parent.resolve()
PYTHON_BIN = sys.executable
MAIN_SCRIPT = PROJECT_DIR / "main.py"
ICON_PATH = PROJECT_DIR / "assets" / "moodle-calendar.png"


def install_desktop_launcher() -> Tuple[bool, str]:
    """Install .desktop entry in ~/.local/share/applications/ so it appears in Ubuntu app menu."""
    apps_dir = Path.home() / ".local" / "share" / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    desktop_file = apps_dir / "moodle-desktop-calendar.desktop"

    content = f"""[Desktop Entry]
Name=Moodle Calendar
Comment=Moodle university calendar widget and deadline reminders
Exec={PYTHON_BIN} {MAIN_SCRIPT} --widget
Icon={ICON_PATH}
Terminal=false
Type=Application
Categories=Office;Calendar;Education;Utility;
Keywords=moodle;calendar;reminders;university;deadlines;
StartupNotify=true
"""
    try:
        desktop_file.write_text(content, encoding="utf-8")
        desktop_file.chmod(0o755)

        # Update desktop database if available
        if shutil.which("update-desktop-database"):
            subprocess.run(["update-desktop-database", str(apps_dir)], check=False)

        return True, str(desktop_file)
    except Exception as e:
        return False, str(e)


def install_autostart() -> Tuple[bool, str]:
    """Install autostart entry in ~/.config/autostart/."""
    autostart_dir = Path.home() / ".config" / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True)
    desktop_file = autostart_dir / "moodle-desktop-calendar.desktop"

    content = f"""[Desktop Entry]
Name=Moodle Calendar Widget
Comment=Moodle university calendar widget and deadline reminders
Exec={PYTHON_BIN} {MAIN_SCRIPT} --widget
Icon={ICON_PATH}
Terminal=false
Type=Application
X-GNOME-Autostart-enabled=true
"""
    try:
        desktop_file.write_text(content, encoding="utf-8")
        return True, str(desktop_file)
    except Exception as e:
        return False, str(e)


def install_systemd_service() -> Tuple[bool, str]:
    """
    Install and activate a systemd user service and timer that runs the reminder checker
    continuously in the background without needing the window open.
    """
    systemd_user_dir = Path.home() / ".config" / "systemd" / "user"
    systemd_user_dir.mkdir(parents=True, exist_ok=True)

    service_file = systemd_user_dir / "moodle-reminder.service"
    service_content = f"""[Unit]
Description=Moodle University Calendar Reminder Daemon
After=network.target

[Service]
Type=simple
ExecStart={PYTHON_BIN} {MAIN_SCRIPT} --daemon
Restart=always
RestartSec=30
Environment=DISPLAY=:0
Environment=WAYLAND_DISPLAY=wayland-0
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%U/bus

[Install]
WantedBy=default.target
"""
    try:
        service_file.write_text(service_content, encoding="utf-8")

        # Reload systemd user daemon
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        # Enable and start service
        subprocess.run(["systemctl", "--user", "enable", "--now", "moodle-reminder.service"], check=True)

        return True, "Moodle reminder systemd service enabled and started successfully."
    except Exception as e:
        return False, f"Failed to configure systemd user service: {e}"


def uninstall_systemd_service() -> Tuple[bool, str]:
    """Stop and disable systemd user service."""
    try:
        subprocess.run(["systemctl", "--user", "stop", "moodle-reminder.service"], check=False)
        subprocess.run(["systemctl", "--user", "disable", "moodle-reminder.service"], check=False)
        service_file = Path.home() / ".config" / "systemd" / "user" / "moodle-reminder.service"
        if service_file.exists():
            service_file.unlink()
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        return True, "Service removed."
    except Exception as e:
        return False, str(e)
