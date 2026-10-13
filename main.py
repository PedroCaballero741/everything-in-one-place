#!/usr/bin/env python3
"""
Moodle Calendar & Deadline Reminders for Linux (GNOME / Ubuntu).
Provides an interactive desktop calendar widget and automated deadline alerts.
"""
import sys
import argparse
from datetime import datetime, timedelta
from moodle_calendar.config import Config
from moodle_calendar.storage import Storage
from moodle_calendar.sync import MoodleSyncEngine
from moodle_calendar.reminder import ReminderNotifier
from moodle_calendar.service import (
    install_desktop_launcher,
    install_autostart,
    install_systemd_service,
)


def run_widget():
    """Launch GTK4 / Libadwaita Desktop Calendar Widget."""
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw
    from moodle_calendar.widget import MoodleCalendarWidget

    config = Config()
    storage = Storage(config)
    sync_engine = MoodleSyncEngine(config, storage)

    app = Adw.Application(application_id="com.moodle.desktop.calendar")

    def on_activate(application):
        win = MoodleCalendarWidget(application, config, storage, sync_engine)
        win.present()

    app.connect("activate", on_activate)
    app.run(sys.argv[:1])


def run_sync(override_url=None):
    config = Config()
    storage = Storage(config)
    sync_engine = MoodleSyncEngine(config, storage)

    print("Syncing Moodle Calendar...")
    success, count, err = sync_engine.sync(override_url)
    if success:
        print(f"[OK] Sync successful! Found {count} calendar event(s).")
    else:
        print(f"[ERROR] Sync failed: {err}")
        sys.exit(1)


def run_daemon():
    config = Config()
    storage = Storage(config)
    sync_engine = MoodleSyncEngine(config, storage)
    notifier = ReminderNotifier(config, storage)

    notifier.run_loop(poll_interval=60, sync_engine=sync_engine)


def run_status():
    config = Config()
    storage = Storage(config)
    events = storage.get_upcoming_events()

    print("\n================= MOODLE CALENDAR STATUS =================")
    if config.university_url:
        print(f"Connected Portal: {config.university_url} (User: {config.username or 'authenticated'})")
    if config.moodle_url:
        print(f"Calendar Feed URL: {config.moodle_url}")
    if not config.is_configured:
        print("Status: Not connected (Configure in settings)")
    print(f"Last sync: {config.last_sync_time or 'Never'}")
    print(f"Sync status: {config.last_sync_status}")
    if config.last_sync_error:
        print(f"Sync error: {config.last_sync_error}")
    print("-------------------------------------------------------------")

    if not events:
        print("No upcoming deadlines. Everything is up to date!")
    else:
        print(f"Upcoming Deadlines ({len(events)}):")
        for idx, e in enumerate(events, 1):
            deadline_str = e.deadline.strftime("%Y-%m-%d %H:%M") if e.deadline else "No date"
            print(f"  {idx}. [{e.clean_course}] {e.title}")
            print(f"     Due: {deadline_str} ({e.time_remaining_str}) | Status: {e.status}")
            if e.url:
                print(f"     Link: {e.url}")
    print("=============================================================\n")


def load_demo():
    from moodle_calendar.parser import IcsParser
    config = Config()
    storage = Storage(config)

    from datetime import timezone
    now = datetime.now(timezone.utc)
    t1 = (now + timedelta(hours=3)).strftime("%Y%m%dT%H%M%SZ")
    t2 = (now + timedelta(days=1, hours=5)).strftime("%Y%m%dT%H%M%SZ")
    t3 = (now + timedelta(days=3)).strftime("%Y%m%dT%H%M%SZ")
    t4 = (now + timedelta(days=6)).strftime("%Y%m%dT%H%M%SZ")

    demo_ics = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Moodle Demo//EN
BEGIN:VEVENT
UID:demo-1@moodle
SUMMARY:Entrega Tarea 2: Árboles Binarios y Grafos
DESCRIPTION:Subir código en Python y reporte en PDF antes de la hora límite.<br />Course: Estructuras de Datos
DTSTART:{t1}
DTEND:{t1}
CATEGORIES:Estructuras de Datos
URL:https://moodle.org
END:VEVENT
BEGIN:VEVENT
UID:demo-2@moodle
SUMMARY:Quiz Virtual 1: Cinemática y Leyes de Newton
DESCRIPTION:Cuestionario interactivo de 15 preguntas.<br />Course: Física I
DTSTART:{t2}
DTEND:{t2}
CATEGORIES:Física I
URL:https://moodle.org
END:VEVENT
BEGIN:VEVENT
UID:demo-3@moodle
SUMMARY:Avance 1 Proyecto Final: Modelo Entidad-Relación
DESCRIPTION:Diseño conceptual de la base de datos y script SQL de creación.<br />Course: Bases de Datos
DTSTART:{t3}
DTEND:{t3}
CATEGORIES:Bases de Datos
URL:https://moodle.org
END:VEVENT
BEGIN:VEVENT
UID:demo-4@moodle
SUMMARY:Taller 3: Derivadas Parciales e Integrales Dobles
DESCRIPTION:Ejercicios impares de la sección 4.3.<br />Course: Cálculo Multivariado
DTSTART:{t4}
DTEND:{t4}
CATEGORIES:Cálculo Multivariado
URL:https://moodle.org
END:VEVENT
END:VCALENDAR"""

    events = IcsParser.parse(demo_ics)
    storage.save_events(events, raw_ics=demo_ics)
    config.set_sync_result("success", "")
    print(f"[OK] Loaded {len(events)} demo university events into local calendar cache!")
    run_status()


def run_install():
    print("Installing Moodle Calendar into Ubuntu desktop system...")
    ok1, res1 = install_desktop_launcher()
    print(f"[{'OK' if ok1 else 'ERROR'}] Desktop application launcher: {res1}")

    ok2, res2 = install_autostart()
    print(f"[{'OK' if ok2 else 'ERROR'}] Desktop autostart entry: {res2}")

    ok3, res3 = install_systemd_service()
    print(f"[{'OK' if ok3 else 'ERROR'}] Background reminder daemon: {res3}")
    print("\nInstallation complete! You can now launch 'Moodle Calendar' from your Ubuntu application menu.")


def run_login(univ_url=None, username=None):
    import getpass
    from moodle_calendar.auth import MoodleAuthClient
    config = Config()
    storage = Storage(config)
    auth = MoodleAuthClient(config, storage)

    url = univ_url or input(f"University Portal URL [{config.university_url}]: ").strip() or config.university_url
    user = username or input(f"Username / Código [{config.username}]: ").strip() or config.username
    pwd = getpass.getpass("Password / Contraseña: ")

    print(f"\nAuthenticating with {url}...")
    success, count, msg, cal_url = auth.login_with_credentials(url, user, pwd)
    if success:
        print(f"[OK] {msg}")
        if cal_url:
            print(f"[OK] Calendar feed URL: {cal_url}")
        print(f"[OK] Loaded {count} deadline(s) into local calendar!")
        run_status()
    else:
        print(f"[ERROR] Login failed: {msg}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Moodle Desktop Calendar & Deadline Reminders")
    parser.add_argument("--widget", action="store_true", help="Launch interactive desktop widget")
    parser.add_argument("--login", action="store_true", help="Authenticate with university Moodle portal")
    parser.add_argument("--url", type=str, help="University portal URL (e.g. https://moodle.your-university.edu)")
    parser.add_argument("--user", type=str, help="Username or student code")
    parser.add_argument("--sync", action="store_true", help="Perform immediate calendar sync")
    parser.add_argument("--sync-url", type=str, help="Sync from specified calendar export URL")
    parser.add_argument("--daemon", action="store_true", help="Run background reminder checking daemon")
    parser.add_argument("--status", action="store_true", help="Display current deadlines in console")
    parser.add_argument("--demo", action="store_true", help="Load demo university tasks for testing")
    parser.add_argument("--install", action="store_true", help="Install desktop shortcut and background service")
    parser.add_argument("--notify-test", action="store_true", help="Dispatch a test desktop notification")

    args = parser.parse_args()

    if args.demo:
        load_demo()
    elif args.login:
        run_login(args.url, args.user)
    elif args.sync or args.sync_url:
        run_sync(args.sync_url)
    elif args.daemon:
        run_daemon()
    elif args.status:
        run_status()
    elif args.install:
        run_install()
    elif args.notify_test:
        config = Config()
        notifier = ReminderNotifier(config)
        from moodle_calendar.models import MoodleEvent
        now = datetime.now().astimezone()
        ev = MoodleEvent(
            uid="test",
            title="Tarea de Ejemplo: Álgebra Lineal",
            description="Revisión de entrega de vectores y matrices.",
            dtstart=now + timedelta(hours=2),
            dtend=now + timedelta(hours=2),
            course="Álgebra Lineal",
            url=config.university_url or "https://moodle.org"
        )
        notifier.send_notification(ev, threshold_min=120)
        print("[OK] Sent test desktop notification!")
    else:
        run_widget()


if __name__ == "__main__":
    main()
