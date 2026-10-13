"""Desktop Calendar Widget for Moodle built with GTK4 & Libadwaita."""
import os
import sys
import threading
import subprocess
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, List, Set

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gdk, Gio

from .models import MoodleEvent
from .config import Config
from .storage import Storage
from .sync import MoodleSyncEngine
from .reminder import ReminderNotifier
from .auth import MoodleAuthClient, clean_base_url


class MoodleCalendarWidget(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, config: Config, storage: Storage, sync_engine: MoodleSyncEngine):
        super().__init__(application=app)
        self.config = config
        self.storage = storage
        self.sync_engine = sync_engine
        self.notifier = ReminderNotifier(config, storage)

        self.current_filter = "upcoming"  # upcoming, today, week, all, or specific_date
        self.selected_filter_date: Optional[date] = None
        self.is_syncing = False

        self.set_title("Moodle Calendar")
        self.set_default_size(self.config._data.get("window_width", 460), self.config._data.get("window_height", 720))
        self.add_css_class("calendar-widget-window")

        # Load custom CSS
        self._load_css()

        # Build Main UI
        self._build_ui()

        # Initial Refresh
        self.refresh_calendar_and_list()

        # Periodic reminder check (every 60 seconds)
        GLib.timeout_add_seconds(60, self._on_reminder_tick)

        # Periodic auto-sync (based on user config)
        sync_interval = max(5, self.config.sync_interval_minutes) * 60
        GLib.timeout_add_seconds(sync_interval, self._on_auto_sync_tick)

    def _load_css(self):
        css_file = Path(__file__).parent.parent / "assets" / "style.css"
        if css_file.exists():
            provider = Gtk.CssProvider()
            try:
                provider.load_from_path(str(css_file))
                display = Gdk.Display.get_default()
                if display:
                    Gtk.StyleContext.add_provider_for_display(
                        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                    )
            except Exception as e:
                print(f"Error loading CSS: {e}")

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_content(main_box)

        # 1. Header Bar
        header = Adw.HeaderBar()
        main_box.append(header)

        # Left Header items: Sync Button & Today Button
        self.sync_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self.sync_btn.set_tooltip_text("Sync Moodle Calendar Now")
        self.sync_btn.connect("clicked", self._on_sync_clicked)
        header.pack_start(self.sync_btn)

        self.today_btn = Gtk.Button(label="Today")
        self.today_btn.set_tooltip_text("Jump to Today")
        self.today_btn.add_css_class("flat")
        self.today_btn.connect("clicked", self._on_today_clicked)
        header.pack_start(self.today_btn)

        # Right Header items: Settings Button
        settings_btn = Gtk.Button.new_from_icon_name("emblem-system-symbolic")
        settings_btn.set_tooltip_text("Settings & Moodle URL")
        settings_btn.connect("clicked", self._on_settings_clicked)
        header.pack_end(settings_btn)

        # 2. Status Banner / Summary Bar
        self.status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.status_bar.add_css_class("widget-header-box")
        main_box.append(self.status_bar)

        self.status_label = Gtk.Label(label="Moodle Calendar")
        self.status_label.set_hexpand(True)
        self.status_label.set_halign(Gtk.Align.START)
        self.status_label.add_css_class("sync-status-label")
        self.status_bar.append(self.status_label)

        self.spinner = Gtk.Spinner()
        self.status_bar.append(self.spinner)

        # 3. Calendar Container
        cal_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        cal_container.add_css_class("widget-calendar-container")
        main_box.append(cal_container)

        self.calendar = Gtk.Calendar()
        self.calendar.set_show_heading(True)
        self.calendar.set_show_day_names(True)
        self.calendar.connect("notify::year", self._on_calendar_month_changed)
        self.calendar.connect("notify::month", self._on_calendar_month_changed)
        self.calendar.connect("notify::day", self._on_calendar_day_selected)
        cal_container.append(self.calendar)

        # 4. Filter Buttons Bar
        filters_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        filters_box.set_halign(Gtk.Align.CENTER)
        filters_box.set_margin_top(4)
        filters_box.set_margin_bottom(6)
        main_box.append(filters_box)

        self.btn_filter_upcoming = Gtk.ToggleButton(label="Upcoming")
        self.btn_filter_upcoming.set_active(True)
        self.btn_filter_upcoming.connect("toggled", lambda b: self._set_filter("upcoming", b))
        filters_box.append(self.btn_filter_upcoming)

        self.btn_filter_today = Gtk.ToggleButton(label="Today")
        self.btn_filter_today.connect("toggled", lambda b: self._set_filter("today", b))
        filters_box.append(self.btn_filter_today)

        self.btn_filter_week = Gtk.ToggleButton(label="This Week")
        self.btn_filter_week.connect("toggled", lambda b: self._set_filter("week", b))
        filters_box.append(self.btn_filter_week)

        self.btn_filter_all = Gtk.ToggleButton(label="All")
        self.btn_filter_all.connect("toggled", lambda b: self._set_filter("all", b))
        filters_box.append(self.btn_filter_all)

        # Active Day Filter Indicator (hidden by default)
        self.day_filter_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.day_filter_bar.set_margin_start(16)
        self.day_filter_bar.set_margin_end(16)
        self.day_filter_bar.set_margin_bottom(4)
        self.day_filter_bar.set_visible(False)
        main_box.append(self.day_filter_bar)

        self.day_filter_label = Gtk.Label(label="")
        self.day_filter_label.set_hexpand(True)
        self.day_filter_label.set_halign(Gtk.Align.START)
        self.day_filter_bar.append(self.day_filter_label)

        clear_day_filter_btn = Gtk.Button(label="Clear Filter")
        clear_day_filter_btn.add_css_class("flat")
        clear_day_filter_btn.connect("clicked", self._clear_day_filter)
        self.day_filter_bar.append(clear_day_filter_btn)

        # 5. Scrolled Window with Events List
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_vexpand(True)
        self.scroll.set_hexpand(True)
        main_box.append(self.scroll)

        self.events_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.events_box.set_margin_top(4)
        self.events_box.set_margin_bottom(16)
        self.scroll.set_child(self.events_box)

    def _set_filter(self, filter_name: str, button: Gtk.ToggleButton):
        if not button.get_active():
            return

        # Untoggle others
        for name, btn in [
            ("upcoming", self.btn_filter_upcoming),
            ("today", self.btn_filter_today),
            ("week", self.btn_filter_week),
            ("all", self.btn_filter_all),
        ]:
            if name != filter_name:
                btn.set_active(False)

        self.current_filter = filter_name
        self.selected_filter_date = None
        self.day_filter_bar.set_visible(False)
        self.refresh_events_list()

    def _clear_day_filter(self, _btn):
        self.selected_filter_date = None
        self.day_filter_bar.set_visible(False)
        self.btn_filter_upcoming.set_active(True)

    def _on_calendar_month_changed(self, _widget, _param):
        self._update_calendar_marks()

    def _on_calendar_day_selected(self, _widget, _param):
        year = self.calendar.get_year()
        # GTK4 calendar month is 0-indexed in some versions, 1-indexed in others.
        # In GTK4: get_month() returns 0-11
        month = self.calendar.get_month() + 1
        day = self.calendar.get_day()
        try:
            sel_date = date(year, month, day)
        except ValueError:
            return

        self.selected_filter_date = sel_date
        self.current_filter = "specific_date"

        # Untoggle category buttons
        self.btn_filter_upcoming.set_active(False)
        self.btn_filter_today.set_active(False)
        self.btn_filter_week.set_active(False)
        self.btn_filter_all.set_active(False)

        self.day_filter_label.set_markup(f"<b>Events on {sel_date.strftime('%A, %b %d')}:</b>")
        self.day_filter_bar.set_visible(True)

        self.refresh_events_list()

    def _on_today_clicked(self, _btn):
        now = datetime.now()
        self.calendar.set_year(now.year)
        self.calendar.set_month(now.month - 1)
        self.calendar.set_day(now.day)
        self._update_calendar_marks()
        self.btn_filter_today.set_active(True)

    def _update_calendar_marks(self):
        """Mark days on the calendar that have scheduled deadlines."""
        self.calendar.clear_marks()
        year = self.calendar.get_year()
        month = self.calendar.get_month() + 1

        marked_days = self.storage.get_marked_days_for_month(year, month)
        for day in marked_days:
            self.calendar.mark_day(day)

    def refresh_calendar_and_list(self):
        self._update_calendar_marks()
        self.refresh_events_list()
        self._update_status_bar()

    def _update_status_bar(self):
        all_events = self.storage.get_upcoming_events()
        count = len(all_events)
        last_sync = self.config.last_sync_time

        sync_str = "Never synced"
        if last_sync:
            try:
                dt = datetime.fromisoformat(last_sync)
                sync_str = f"Synced {dt.strftime('%H:%M')}"
            except Exception:
                sync_str = "Synced"

        if self.config.is_configured:
            self.status_label.set_text(f"{count} upcoming task{'s' if count != 1 else ''} | {sync_str}")
        else:
            self.status_label.set_text("Not connected (Click Settings to set up)")

    def refresh_events_list(self):
        # Clear existing list items
        while child := self.events_box.get_first_child():
            self.events_box.remove(child)

        all_events = self.storage.get_all_events()
        now = datetime.now().astimezone()
        today_date = now.date()
        week_end_date = today_date + timedelta(days=7)

        # Filter events
        filtered: List[MoodleEvent] = []
        if self.selected_filter_date:
            filtered = [e for e in all_events if e.deadline and e.deadline.date() == self.selected_filter_date]
        elif self.current_filter == "upcoming":
            filtered = [e for e in all_events if e.deadline and e.deadline >= (now - timedelta(hours=2))]
        elif self.current_filter == "today":
            filtered = [e for e in all_events if e.deadline and e.deadline.date() == today_date]
        elif self.current_filter == "week":
            filtered = [e for e in all_events if e.deadline and today_date <= e.deadline.date() <= week_end_date]
        elif self.current_filter == "all":
            filtered = all_events

        # Empty state handling
        if not filtered:
            self._render_empty_state()
            return

        # Render event cards
        for event in filtered:
            card = self._create_event_card(event)
            self.events_box.append(card)

    def _create_event_card(self, event: MoodleEvent) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("event-card")

        # Top row: Course Name + Status Urgency Badge
        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        card.append(top_row)

        course_label = Gtk.Label(label=event.clean_course)
        course_label.add_css_class("card-course")
        course_label.set_halign(Gtk.Align.START)
        course_label.set_xalign(0.0)
        course_label.set_wrap(True)
        top_row.append(course_label)

        # Status badge
        status_code = event.status
        badge_text = {
            "overdue": "Overdue",
            "today": "Due Today",
            "soon": "Due Soon",
            "upcoming": "Upcoming",
        }.get(status_code, "Upcoming")

        status_badge = Gtk.Label(label=badge_text)
        status_badge.add_css_class("status-badge")
        status_badge.add_css_class(status_code)
        status_badge.set_hexpand(True)
        status_badge.set_halign(Gtk.Align.END)
        top_row.append(status_badge)

        # Title
        title_label = Gtk.Label(label=event.title)
        title_label.add_css_class("card-title")
        title_label.set_halign(Gtk.Align.START)
        title_label.set_wrap(True)
        title_label.set_xalign(0.0)
        card.append(title_label)

        # Time & Countdown Row
        time_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        card.append(time_row)

        if event.deadline:
            clock_icon = Gtk.Image.new_from_icon_name("preferences-system-time-symbolic")
            time_row.append(clock_icon)

            formatted_time = event.deadline.strftime("%a, %b %d at %H:%M")
            time_label = Gtk.Label(label=formatted_time)
            time_label.add_css_class("card-time")
            time_row.append(time_label)

            countdown_label = Gtk.Label(label=f"({event.time_remaining_str})")
            countdown_label.add_css_class("card-countdown")
            countdown_label.set_hexpand(True)
            countdown_label.set_halign(Gtk.Align.END)
            time_row.append(countdown_label)

        # Description (first 2 lines if available)
        if event.description:
            lines = [ln.strip() for ln in event.description.split("\n") if ln.strip()]
            preview = " ".join(lines[:2])
            if len(preview) > 140:
                preview = preview[:137] + "..."
            desc_label = Gtk.Label(label=preview)
            desc_label.add_css_class("card-desc")
            desc_label.set_halign(Gtk.Align.START)
            desc_label.set_wrap(True)
            desc_label.set_xalign(0.0)
            card.append(desc_label)

        # Action Buttons Row
        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        action_row.set_margin_top(4)
        card.append(action_row)

        if event.url:
            open_btn = Gtk.Button.new_with_label("Open in Moodle")
            open_btn.add_css_class("moodle-btn")
            open_btn.add_css_class("suggested-action")
            open_btn.connect("clicked", lambda _b, u=event.url: self._open_moodle_url(u))
            action_row.append(open_btn)

        return card

    def _render_empty_state(self):
        empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        empty_box.set_halign(Gtk.Align.CENTER)
        empty_box.set_valign(Gtk.Align.CENTER)
        empty_box.set_margin_top(40)
        empty_box.set_margin_bottom(40)
        empty_box.set_margin_start(20)
        empty_box.set_margin_end(20)

        if not self.config.is_configured:
            icon = Gtk.Image.new_from_icon_name("x-office-calendar-symbolic")
            icon.set_pixel_size(64)
            empty_box.append(icon)

            title = Gtk.Label(label="Connect to University Moodle")
            title.add_css_class("card-title")
            empty_box.append(title)

            desc = Gtk.Label(
                label="Connect your university Moodle portal to track deadlines and receive automatic desktop reminders."
            )
            desc.set_wrap(True)
            desc.set_justify(Gtk.Justification.CENTER)
            empty_box.append(desc)

            cfg_btn = Gtk.Button(label="Connect University Portal")
            cfg_btn.add_css_class("suggested-action")
            cfg_btn.set_halign(Gtk.Align.CENTER)
            cfg_btn.connect("clicked", self._on_settings_clicked)
            empty_box.append(cfg_btn)

            demo_btn = Gtk.Button(label="Load Demo University Events")
            demo_btn.add_css_class("flat")
            demo_btn.set_halign(Gtk.Align.CENTER)
            demo_btn.connect("clicked", self._load_demo_events)
            empty_box.append(demo_btn)
        else:
            icon = Gtk.Image.new_from_icon_name("object-select-symbolic")
            icon.set_pixel_size(48)
            empty_box.append(icon)

            msg = Gtk.Label(label="No deadlines found for this filter.")
            msg.add_css_class("card-title")
            empty_box.append(msg)

            submsg = Gtk.Label(label="All caught up! Or click Sync to check for updates.")
            submsg.add_css_class("card-desc")
            empty_box.append(submsg)

        self.events_box.append(empty_box)

    def _open_moodle_url(self, url: str):
        try:
            subprocess.Popen(["xdg-open", url])
        except Exception as e:
            print(f"Failed to open URL {url}: {e}")

    def _on_sync_clicked(self, _btn):
        if self.is_syncing:
            return
        self.is_syncing = True
        self.spinner.start()
        self.sync_btn.set_sensitive(False)
        self.status_label.set_text("Syncing with Moodle...")

        def _worker():
            success, count, err = self.sync_engine.sync()
            GLib.idle_add(self._on_sync_finished, success, count, err)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_sync_finished(self, success: bool, count: int, err: str):
        self.is_syncing = False
        self.spinner.stop()
        self.sync_btn.set_sensitive(True)

        if success:
            self.refresh_calendar_and_list()
            # Also run a reminder check
            self.notifier.check_and_notify()
        else:
            self.status_label.set_text(f"Sync failed: {err[:35]}...")
            # If not configured, open settings
            if not self.config.is_configured:
                self._on_settings_clicked(None)

    def _on_settings_clicked(self, _btn):
        dialog = MoodleSettingsDialog(self, self.config, self.sync_engine, self.notifier)
        dialog.present()

    def _load_demo_events(self, _btn):
        from .sync import IcsParser
        from datetime import timezone
        now = datetime.now(timezone.utc)
        t1 = (now + timedelta(hours=3)).strftime("%Y%m%dT%H%M%SZ")
        t2 = (now + timedelta(days=1, hours=4)).strftime("%Y%m%dT%H%M%SZ")
        t3 = (now + timedelta(days=3)).strftime("%Y%m%dT%H%M%SZ")
        t4 = (now + timedelta(days=6)).strftime("%Y%m%dT%H%M%SZ")

        demo_ics = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Moodle Demo//EN
BEGIN:VEVENT
UID:demo-1@moodle
SUMMARY:Entrega Tarea 2: Árboles y Grafos
DESCRIPTION:Subir informe en PDF con implementación en Python.<br />Course: Estructuras de Datos
DTSTART:{t1}
DTEND:{t1}
CATEGORIES:Estructuras de Datos
URL:https://campus.universidad.edu/mod/assign/view.php?id=101
END:VEVENT
BEGIN:VEVENT
UID:demo-2@moodle
SUMMARY:Cuestionario Virtual: Leyes de Newton
DESCRIPTION:Examen corto de 30 minutos con 15 preguntas de opción múltiple.<br />Course: Física I
DTSTART:{t2}
DTEND:{t2}
CATEGORIES:Física I
URL:https://campus.universidad.edu/mod/quiz/view.php?id=102
END:VEVENT
BEGIN:VEVENT
UID:demo-3@moodle
SUMMARY:Avance Proyecto: Base de Datos Relacional
DESCRIPTION:Entrega del diagrama entidad-relación y script SQL normalizado.<br />Course: Bases de Datos
DTSTART:{t3}
DTEND:{t3}
CATEGORIES:Bases de Datos
URL:https://campus.universidad.edu/mod/assign/view.php?id=103
END:VEVENT
BEGIN:VEVENT
UID:demo-4@moodle
SUMMARY:Taller 3: Integrales Múltiples
DESCRIPTION:Resolver problemas 1 al 10 del capítulo 14.<br />Course: Cálculo Integral
DTSTART:{t4}
DTEND:{t4}
CATEGORIES:Cálculo Integral
URL:https://campus.universidad.edu/mod/assign/view.php?id=104
END:VEVENT
END:VCALENDAR"""
        events = IcsParser.parse(demo_ics)
        self.storage.save_events(events, raw_ics=demo_ics)
        self.config.set_sync_result("success", "")
        self.refresh_calendar_and_list()

    def _on_reminder_tick(self) -> bool:
        """Periodic timer checking for approaching deadlines."""
        try:
            self.notifier.check_and_notify()
        except Exception as e:
            print(f"Error checking reminders: {e}")
        return True  # Keep GLib timer active

    def _on_auto_sync_tick(self) -> bool:
        """Periodic auto-sync in background."""
        if self.config.is_configured and not self.is_syncing:
            self._on_sync_clicked(None)
        return True  # Keep GLib timer active


class MoodleSettingsDialog(Adw.PreferencesWindow):
    def __init__(self, parent_window: MoodleCalendarWidget, config: Config, sync_engine: MoodleSyncEngine, notifier: ReminderNotifier):
        super().__init__()
        self.parent_window = parent_window
        self.config = config
        self.sync_engine = sync_engine
        self.notifier = notifier
        self.auth_client = MoodleAuthClient(config, parent_window.storage)

        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_title("Moodle Settings")
        self.set_default_size(520, 680)

        self._build_settings_page()

    def _build_settings_page(self):
        page = Adw.PreferencesPage()
        page.set_title("Configuration")
        page.set_icon_name("preferences-system-symbolic")
        self.add(page)

        # 1. University Portal Login
        univ_group = Adw.PreferencesGroup()
        univ_group.set_title("University Portal Login")
        univ_group.set_description(
            "Enter your university Moodle URL (e.g. https://moodle.your-university.edu) and your student credentials to automatically connect and sync."
        )
        page.add(univ_group)

        self.univ_url_row = Adw.EntryRow()
        self.univ_url_row.set_title("University Portal URL")
        self.univ_url_row.set_text(self.config.university_url or "")
        univ_group.add(self.univ_url_row)

        self.user_row = Adw.EntryRow()
        self.user_row.set_title("Username / Student ID")
        self.user_row.set_text(self.config.username or "")
        univ_group.add(self.user_row)

        self.pass_row = Adw.PasswordEntryRow()
        self.pass_row.set_title("Password")
        univ_group.add(self.pass_row)

        # Login action button row
        login_action_row = Adw.ActionRow()
        login_action_row.set_title("Automated Connect")
        login_action_row.set_subtitle("Authenticate and extract calendar feed")

        self.login_spinner = Gtk.Spinner()
        login_action_row.add_suffix(self.login_spinner)

        self.login_btn = Gtk.Button(label="Connect & Sync")
        self.login_btn.add_css_class("suggested-action")
        self.login_btn.set_valign(Gtk.Align.CENTER)
        self.login_btn.connect("clicked", self._on_login_clicked)
        login_action_row.add_suffix(self.login_btn)
        univ_group.add(login_action_row)

        # Status label row for login feedback
        self.login_status_row = Adw.ActionRow()
        self.login_status_row.set_title("Status")
        self.login_status_label = Gtk.Label(label="Ready to connect")
        self.login_status_label.set_wrap(True)
        self.login_status_label.set_xalign(1.0)
        self.login_status_row.add_suffix(self.login_status_label)
        univ_group.add(self.login_status_row)

        # 2. Direct Calendar URL (Alternative / Advanced)
        conn_group = Adw.PreferencesGroup()
        conn_group.set_title("Direct Calendar Export URL")
        conn_group.set_description("If you already have your Moodle iCal URL, paste it here directly.")
        page.add(conn_group)

        self.url_row = Adw.EntryRow()
        self.url_row.set_title("Calendar URL (webcal:// or https://)")
        self.url_row.set_text(self.config.moodle_url or "")
        conn_group.add(self.url_row)

        action_row = Adw.ActionRow()
        action_row.set_title("Save Calendar URL")
        test_btn = Gtk.Button(label="Save & Sync")
        test_btn.set_valign(Gtk.Align.CENTER)
        test_btn.connect("clicked", self._on_save_and_sync)
        action_row.add_suffix(test_btn)
        conn_group.add(action_row)

        # Tutorial Expander
        expander = Adw.ExpanderRow()
        expander.set_title("Manual instructions: finding your Moodle calendar URL")
        expander.set_subtitle("Step-by-step instructions for your university Moodle portal")
        conn_group.add(expander)

        tutorial_text = (
            "1. Abre el portal Moodle de tu universidad en tu navegador.\n"
            "2. Ve a la sección 'Calendario' en la barra lateral o menú.\n"
            "3. Baja al final de la página y haz clic en 'Exportar calendario'.\n"
            "4. En 'Eventos para exportar', elige 'Todos los eventos'.\n"
            "5. En 'Período de tiempo', elige 'Recientes y próximos 60 días'.\n"
            "6. Haz clic en 'Obtener URL del calendario' y cópiala aquí."
        )
        tut_label = Gtk.Label(label=tutorial_text)
        tut_label.set_wrap(True)
        tut_label.set_xalign(0.0)
        tut_label.set_margin_start(16)
        tut_label.set_margin_end(16)
        tut_label.set_margin_top(8)
        tut_label.set_margin_bottom(8)
        expander.add_row(tut_label)

        # 3. Notifications & Reminders Group
        rem_group = Adw.PreferencesGroup()
        rem_group.set_title("Desktop Reminders")
        rem_group.set_description("Receive desktop alerts on Ubuntu before assignment and quiz deadlines.")
        page.add(rem_group)

        self.notif_switch = Adw.SwitchRow()
        self.notif_switch.set_title("Enable Desktop Notifications")
        self.notif_switch.set_subtitle("Dispatches system alerts when deadlines are close")
        self.notif_switch.set_active(self.config.enable_notifications)
        self.notif_switch.connect("notify::active", self._on_notif_toggled)
        rem_group.add(self.notif_switch)

        test_notif_row = Adw.ActionRow()
        test_notif_row.set_title("Test Desktop Notification")
        test_notif_row.set_subtitle("Verify Ubuntu desktop popups are working")
        send_test_btn = Gtk.Button(label="Send Test Alert")
        send_test_btn.set_valign(Gtk.Align.CENTER)
        send_test_btn.connect("clicked", self._on_send_test_notif)
        test_notif_row.add_suffix(send_test_btn)
        rem_group.add(test_notif_row)

        # 4. Automation Group
        auto_group = Adw.PreferencesGroup()
        auto_group.set_title("Background Service and Sync")
        page.add(auto_group)

        self.interval_row = Adw.ComboRow()
        self.interval_row.set_title("Automatic Sync Frequency")
        interval_model = Gtk.StringList.new(["Every 15 minutes", "Every 30 minutes", "Every 1 hour", "Every 2 hours"])
        self.interval_row.set_model(interval_model)
        
        cur_min = self.config.sync_interval_minutes
        idx = 1
        if cur_min <= 15:
            idx = 0
        elif cur_min <= 30:
            idx = 1
        elif cur_min <= 60:
            idx = 2
        else:
            idx = 3
        self.interval_row.set_selected(idx)
        self.interval_row.connect("notify::selected", self._on_interval_changed)
        auto_group.add(self.interval_row)

        daemon_row = Adw.ActionRow()
        daemon_row.set_title("Background Reminder Daemon")
        daemon_row.set_subtitle("Keep reminder notifications running even when widget is closed")
        daemon_btn = Gtk.Button(label="Enable Systemd Service")
        daemon_btn.set_valign(Gtk.Align.CENTER)
        daemon_btn.connect("clicked", self._on_enable_systemd)
        daemon_row.add_suffix(daemon_btn)
        auto_group.add(daemon_row)

    def _on_login_clicked(self, _btn):
        url = self.univ_url_row.get_text().strip()
        user = self.user_row.get_text().strip()
        pwd = self.pass_row.get_text()

        if not url:
            self.login_status_label.set_text("Please enter your university Moodle URL.")
            return
        if not user or not pwd:
            self.login_status_label.set_text("Username and password are required.")
            return

        self.config.university_url = url
        self.config.username = user

        self.login_btn.set_sensitive(False)
        self.login_spinner.start()
        self.login_status_label.set_text("Connecting to university portal...")

        def _worker():
            success, count, msg, cal_url = self.auth_client.login_with_credentials(url, user, pwd)
            GLib.idle_add(self._on_login_finished, success, count, msg, cal_url)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_login_finished(self, success: bool, count: int, msg: str, cal_url: str):
        self.login_btn.set_sensitive(True)
        self.login_spinner.stop()

        if success:
            self.login_status_label.set_text(f"Connected! {count} deadlines loaded.")
            if cal_url:
                self.url_row.set_text(cal_url)
            self.parent_window.refresh_calendar_and_list()
            # Close dialog after a short delay on success
            GLib.timeout_add(1200, self.close)
        else:
            self.login_status_label.set_text(f"Error: {msg}")

    def _on_save_and_sync(self, _btn):
        new_url = self.url_row.get_text().strip()
        self.config.moodle_url = new_url
        self.parent_window.refresh_calendar_and_list()
        self.parent_window._on_sync_clicked(None)
        self.close()

    def _on_notif_toggled(self, switch_row, _param):
        self.config.enable_notifications = switch_row.get_active()

    def _on_interval_changed(self, combo_row, _param):
        idx = combo_row.get_selected()
        mins = [15, 30, 60, 120][idx]
        self.config.sync_interval_minutes = mins

    def _on_send_test_notif(self, _btn):
        from .models import MoodleEvent
        now = datetime.now().astimezone()
        test_event = MoodleEvent(
            uid="test-notif",
            title="Tarea de Ejemplo: Álgebra Lineal",
            description="Esta es una notificación de prueba de Moodle Calendar Widget.",
            dtstart=now + timedelta(hours=2),
            dtend=now + timedelta(hours=2),
            course="Álgebra Lineal",
            url=self.config.university_url or "https://moodle.org",
        )
        self.notifier.send_notification(test_event, threshold_min=120)

    def _on_enable_systemd(self, btn: Gtk.Button):
        from .service import install_systemd_service
        ok, msg = install_systemd_service()
        if ok:
            btn.set_label("Enabled")
            btn.set_sensitive(False)
        else:
            print(f"Failed to install systemd service: {msg}")
