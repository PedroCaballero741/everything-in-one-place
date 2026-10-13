# Moodle Desktop Calendar and Reminders for Linux (GNOME / Ubuntu)

An interactive desktop calendar widget and automated reminder system for university Moodle assignments, quizzes, and deadlines. Built with **Python**, **GTK 4**, and **Libadwaita** for native performance and look-and-feel on Ubuntu Linux.

---

## Features

- **Interactive Desktop Widget**:
  - Monthly calendar view with highlighted dates for upcoming deadlines.
  - Filter tabs: **Upcoming**, **Today**, **This Week**, **All**, or click any day on the calendar to see tasks for that date.
  - Urgency indicators (Overdue, Due Today, Due Soon, Upcoming) and relative countdowns (*"Due in 2 hours"*, *"Tomorrow at 18:00"*).
  - One-click **"Open in Moodle"** button on each task to open the assignment submission page directly in your browser.
- **Desktop Reminders and Notifications**:
  - Native Ubuntu desktop alerts (`notify-send`) before deadlines (e.g. 24 hours, 3 hours, 30 minutes before due time).
  - Background daemon runs via `systemd --user` so you never miss a deadline even when the widget window is closed.
  - Smart deduplication (stores notification history in local SQLite database).
- **Automatic Moodle Sync**:
  - Connects to your university Moodle via direct API credentials or iCalendar export feed.
  - Automatically syncs every 30 minutes (configurable).
  - Also exports a synchronized `.ics` file at `~/.local/share/moodle-desktop-calendar/moodle.ics` for GNOME Calendar or Thunderbird.
- **Native Ubuntu / GNOME Integration**:
  - Includes `.desktop` application menu launcher with custom icon.
  - Autostarts on system login.

---

## Quick Start / Inicio Rapido

### 1. Launch the Desktop Widget

From your terminal, run:
```bash
python3 main.py
```
Or open your Ubuntu application launcher (press Super / Windows key) and search for **"Moodle Calendar"**.

---

### 2. Connect Your University Moodle

You can connect any university Moodle portal in two ways:

#### Method A: Direct University Portal Login (Recommended / Recomendado)
1. Open the widget Settings.
2. Under **"University Portal Login"**:
   - **University Portal URL**: Your university Moodle URL (e.g. `https://moodle.your-university.edu`).
   - **Username**: Tu usuario o codigo institucional.
   - **Password**: Tu contrasena institucional.
3. Click **"Connect & Sync"**.
4. The application automatically authenticates against your university portal, extracts your calendar feed, and schedules all desktop reminders.

#### Method B: Direct Calendar Export URL (Manual)
1. Log into your university Moodle portal in your browser.
2. Go to **"Calendario"** -> **"Exportar calendario"**.
3. Select **"Todos los eventos"** and **"Recientes y proximos 60 dias"**.
4. Click **"Obtener URL del calendario"**.
5. Paste the link into the **"Direct Calendar Export URL"** section in Settings and click **"Save & Sync"**.

---

#### Command Line Login (CLI)
You can also authenticate directly from the terminal:
```bash
python3 main.py --login --url https://moodle.your-university.edu --user TU_USUARIO
```

---

## Command-Line Usage (CLI)

| Command | Description |
| :--- | :--- |
| `python3 main.py` | Launch the GTK4 Desktop Calendar Widget |
| `python3 main.py --login` | Authenticate directly with university portal |
| `python3 main.py --status` | View current deadlines and countdowns in the terminal |
| `python3 main.py --sync` | Perform an immediate calendar synchronization |
| `python3 main.py --demo` | Load sample university courses and deadlines to test right away |
| `python3 main.py --notify-test` | Dispatch a test Ubuntu desktop notification |
| `python3 main.py --install` | Install `.desktop` application shortcut and systemd user daemon |
| `python3 main.py --daemon` | Run the background reminder daemon directly |

---

## Background Daemon Service (systemd)

The reminder daemon runs automatically in the background as a user service:

- Check service status:
  ```bash
  systemctl --user status moodle-reminder.service
  ```
- Restart service:
  ```bash
  systemctl --user restart moodle-reminder.service
  ```
- View service logs:
  ```bash
  journalctl --user -u moodle-reminder.service -f
  ```

---

## Project Structure

```
everything-in-one-place/
├── main.py                     # Main CLI and GUI launcher
├── install.sh                  # One-click installation script
├── assets/
│   ├── moodle-calendar.png     # High-resolution application icon
│   ├── moodle-calendar.svg     # Vector icon
│   └── style.css               # Modern Libadwaita styling
├── moodle_calendar/
│   ├── __init__.py
│   ├── models.py               # MoodleEvent data model and countdown calculations
│   ├── parser.py               # RFC 5545 iCalendar (.ics) parser with HTML cleaning
│   ├── storage.py              # SQLite storage for cached events and reminder history
│   ├── sync.py                 # HTTP/Webcal sync engine
│   ├── auth.py                 # Direct university portal login & token client
│   ├── reminder.py             # Desktop notification dispatcher (notify-send)
│   ├── widget.py               # GTK4 and Libadwaita desktop widget window
│   ├── config.py               # Persistent JSON configuration (~/.config/moodle-desktop-calendar)
│   └── service.py              # Systemd user service and desktop entry installer
└── README.md                   # Documentation
```
