#!/usr/bin/env python3
"""PiNova System Studio — cross-platform system dashboard.

Runs on Raspberry Pi OS, Linux, Windows, and macOS. Uses psutil for
cross-platform performance counters and Tkinter for the desktop interface.
Existing Linux/Raspberry Pi history remains at ~/raspberry_pi_monitor/monitor_history.db.
"""
from __future__ import annotations

import csv
import json
import os
import platform
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import tkinter as tk
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import ttk, messagebox, filedialog

APP_NAME = "PiNova System Studio"
VERSION = "5.1"
SYSTEM = platform.system()

def _user_data_dir():
    """Choose a conventional, per-user data folder on each supported OS."""
    home = Path.home()
    if SYSTEM == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return base / "PiNovaSystemStudio"
    if SYSTEM == "Darwin":
        return home / "Library" / "Application Support" / "PiNova System Studio"
    # Keep the established Raspberry Pi/Linux database path for compatibility.
    return home / "raspberry_pi_monitor"

def _config_path():
    home = Path.home()
    if SYSTEM == "Windows":
        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        return base / "PiNovaSystemStudio" / "settings.json"
    if SYSTEM == "Darwin":
        return home / "Library" / "Application Support" / "PiNova System Studio" / "settings.json"
    return home / ".config" / "pinova-system-studio" / "settings.json"

DATA_DIR = _user_data_dir()
DB_PATH = DATA_DIR / "monitor_history.db"
CONFIG_PATH = _config_path()

COLORS = {
    "bg": "#0A1020", "sidebar": "#0D172A", "panel": "#111F35",
    "panel_hi": "#172945", "border": "#243955", "text": "#F3F7FF",
    "muted": "#8FA5C2", "mint": "#57F2C2", "blue": "#65A8FF",
    "purple": "#B79CFF", "amber": "#FFC76A", "pink": "#FF7C9B",
    "red": "#FF657A", "green": "#58D99A", "grid": "#21334D",
}

METRICS = {
    "Temperature": ("temperature", 2, "°C"),
    "CPU": ("cpu_usage", 3, "%"),
    "Memory": ("ram_usage", 4, "%"),
    "Storage": ("disk_usage", 5, "%"),
}
DEFAULT_SETTINGS = {"interval": 3, "temperature_limit": 75, "cpu_limit": 85,
                    "memory_limit": 90, "storage_limit": 90}


def load_settings():
    data = dict(DEFAULT_SETTINGS)
    try:
        user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        for key in data:
            if key in user:
                data[key] = user[key]
    except (OSError, ValueError, TypeError):
        pass
    try:
        data["interval"] = max(2, min(60, int(data["interval"])))
        for key in ("temperature_limit", "cpu_limit", "memory_limit", "storage_limit"):
            data[key] = max(1, min(100 if key != "temperature_limit" else 120, float(data[key])))
    except (ValueError, TypeError):
        data = dict(DEFAULT_SETTINGS)
    return data


def save_settings(settings):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def ensure_database():
    """Create compatible table if absent; never delete or reset existing history."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=5) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS system_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            temperature REAL,
            cpu_usage REAL,
            ram_usage REAL,
            disk_usage REAL
        )""")


def save_reading(reading):
    now = datetime.now()
    try:
        with sqlite3.connect(DB_PATH, timeout=5) as con:
            con.execute("""INSERT INTO system_history
                (date,time,temperature,cpu_usage,ram_usage,disk_usage)
                VALUES (?,?,?,?,?,?)""", (
                now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"),
                reading.get("temperature"), reading.get("cpu"),
                reading.get("memory"), reading.get("storage")
            ))
    except sqlite3.Error as exc:
        print("History write warning:", exc, file=sys.stderr)


_cpu_sample = None

def read_cpu():
    """Non-blocking CPU usage via psutil, with a Linux /proc fallback."""
    try:
        import psutil
        return round(float(psutil.cpu_percent(interval=None)), 1)
    except Exception:
        pass
    try:
        fields = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
        values = [int(item) for item in fields]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        old = _cpu_sample
        globals()["_cpu_sample"] = (total, idle)
        if old is None:
            return 0.0
        dt, di = total - old[0], idle - old[1]
        return round(max(0.0, min(100.0, (1.0 - di / dt) * 100.0)), 1) if dt > 0 else 0.0
    except Exception:
        return 0.0

def read_temperature():
    """Read a Linux thermal zone or any available psutil temperature sensor."""
    thermal = Path("/sys/class/thermal")
    candidates = [thermal / "thermal_zone0" / "temp"]
    if thermal.exists():
        candidates += sorted(thermal.glob("thermal_zone*/temp"))
    for path in candidates:
        try:
            value = float(path.read_text().strip())
            if value > 1000:
                value /= 1000.0
            if -20 <= value <= 150:
                return round(value, 1)
        except (OSError, ValueError):
            continue
    try:
        import psutil
        sensors = psutil.sensors_temperatures(fahrenheit=False)
        for name, entries in sensors.items():
            if any(token in name.lower() for token in ("cpu", "core", "package", "thermal")):
                for entry in entries:
                    if entry.current is not None:
                        return round(float(entry.current), 1)
        for entries in sensors.values():
            for entry in entries:
                if entry.current is not None:
                    return round(float(entry.current), 1)
    except Exception:
        pass
    # Windows and many Macs do not expose a standard software temperature API.
    return None

def read_memory():
    try:
        import psutil
        return round(float(psutil.virtual_memory().percent), 1)
    except Exception:
        pass
    try:
        items = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            items[key] = int(value.strip().split()[0])
        total = items.get("MemTotal", 0)
        available = items.get("MemAvailable", items.get("MemFree", 0))
        return round((total - available) / total * 100, 1) if total else 0.0
    except (OSError, ValueError):
        return 0.0

def read_storage():
    try:
        import psutil
        usage = psutil.disk_usage(str(Path.home()))
        return round(usage.used / usage.total * 100, 1) if usage.total else 0.0
    except Exception:
        try:
            usage = shutil.disk_usage(Path.home())
            return round(usage.used / usage.total * 100, 1) if usage.total else 0.0
        except OSError:
            return 0.0

def read_uptime():
    try:
        import psutil
        seconds = max(0, int(time.time() - psutil.boot_time()))
    except Exception:
        try:
            seconds = int(float(Path("/proc/uptime").read_text().split()[0]))
        except (OSError, ValueError, IndexError):
            return "Unavailable"
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"

def read_cpu_model():
    if platform.system() == "Windows":
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)"],
                capture_output=True, text=True, timeout=3, check=False)
            if result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                    capture_output=True, text=True, timeout=3, check=False)
            if result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith(("model name", "hardware", "model")):
                _, value = line.split(":", 1)
                if value.strip():
                    return value.strip()
    except (OSError, ValueError):
        pass
    return platform.processor() or platform.uname().processor or "Unknown processor"

def read_processes():
    try:
        import psutil
        rows = []
        for proc in psutil.process_iter(["pid", "name", "memory_percent"]):
            try:
                name = proc.info.get("name") or "?"
                cpu = proc.cpu_percent(interval=None)
                memory = proc.info.get("memory_percent") or 0.0
                rows.append((int(proc.info["pid"]), str(name), float(cpu), float(memory)))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, KeyError, TypeError):
                continue
        return sorted(rows, key=lambda row: row[2], reverse=True)[:250]
    except Exception:
        try:
            result = subprocess.run(["ps", "-eo", "pid,comm,%cpu,%mem"],
                                    capture_output=True, text=True, timeout=4, check=True)
            rows = []
            for line in result.stdout.splitlines()[1:]:
                bits = line.split(None, 3)
                if len(bits) == 4:
                    try:
                        rows.append((int(bits[0]), bits[1], float(bits[2]), float(bits[3])))
                    except ValueError:
                        continue
            return sorted(rows, key=lambda row: row[2], reverse=True)[:250]
        except Exception:
            return []

def read_network():
    """Return per-interface (bytes received, bytes sent) counters across OSes."""
    try:
        import psutil
        counters = psutil.net_io_counters(pernic=True)
        return {name: (int(stat.bytes_recv), int(stat.bytes_sent)) for name, stat in counters.items()}
    except Exception:
        stats = {}
        try:
            for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
                if ":" not in line:
                    continue
                iface, values = line.split(":", 1)
                nums = values.split()
                if len(nums) >= 9:
                    stats[iface.strip()] = (int(nums[0]), int(nums[8]))
        except (OSError, ValueError):
            pass
        return stats

def human_bytes(count):
    value = float(max(0, count))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{value:.0f} B"
        value /= 1024
    return f"{value:.1f} TB"


def query_history(period="All time", limit=5000):
    now = datetime.now()
    where, params = "", []
    if period == "Today":
        where, params = " WHERE date = ?", [now.strftime("%Y-%m-%d")]
    elif period == "Last 24 hours":
        start = now - timedelta(hours=24)
        where, params = " WHERE date || ' ' || time >= ?", [start.strftime("%Y-%m-%d %H:%M:%S")]
    elif period == "7 days":
        where, params = " WHERE date >= ?", [(now.date() - timedelta(days=6)).strftime("%Y-%m-%d")]
    elif period == "30 days":
        where, params = " WHERE date >= ?", [(now.date() - timedelta(days=29)).strftime("%Y-%m-%d")]
    try:
        with sqlite3.connect(DB_PATH, timeout=5) as con:
            cur = con.execute("SELECT date,time,temperature,cpu_usage,ram_usage,disk_usage FROM system_history" + where + " ORDER BY id DESC LIMIT ?", (*params, limit))
            rows = cur.fetchall()
        rows.reverse()
        return rows
    except sqlite3.Error as exc:
        print("History read warning:", exc, file=sys.stderr)
        return []


class PiNovaApp:
    def __init__(self, root):
        self.root = root
        self.settings = load_settings()
        self.root.title(f"{APP_NAME}  •  v{VERSION}")
        self.root.geometry("1320x830")
        self.root.minsize(1080, 700)
        self.root.configure(bg=COLORS["bg"])
        self.page = "Overview"
        self.running = True
        self.paused = False
        self.graph_metric = tk.StringVar(value="CPU")
        self.history_metric = tk.StringVar(value="All")
        self.history_period = tk.StringVar(value="Today")
        self.process_search = tk.StringVar(value="")
        self.latest = {"temperature": None, "cpu": 0.0, "memory": 0.0, "storage": 0.0}
        self.samples = deque(maxlen=90)
        self.net_prev = None
        self.net_snapshot = {}
        self.alert_log = deque(maxlen=100)
        self.active_alerts = {}
        self.metric_cards = {}
        ensure_database()
        self._seed_graph_from_history()
        self._style()
        self._build_shell()
        self.navigate("Overview")
        self._sample(first=True)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _seed_graph_from_history(self):
        """Warm the chart from prior records so it is useful immediately on launch."""
        try:
            for date_text, time_text, temp, cpu, memory, storage in query_history("All time", 90):
                stamp = datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M:%S")
                self.samples.append((stamp, {"temperature": temp, "cpu": cpu or 0.0,
                                             "memory": memory or 0.0, "storage": storage or 0.0}))
        except (ValueError, TypeError):
            pass

    def _style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TCombobox", fieldbackground=COLORS["panel_hi"], background=COLORS["panel_hi"],
                        foreground=COLORS["text"], arrowcolor=COLORS["mint"], padding=6)
        style.map("TCombobox", fieldbackground=[("readonly", COLORS["panel_hi"])],
                  foreground=[("readonly", COLORS["text"])])
        style.configure("Treeview", background=COLORS["panel"], fieldbackground=COLORS["panel"],
                        foreground=COLORS["text"], rowheight=30, borderwidth=0)
        style.configure("Treeview.Heading", background=COLORS["panel_hi"], foreground=COLORS["muted"],
                        relief="flat", padding=8)
        style.map("Treeview", background=[("selected", "#254B70")], foreground=[("selected", COLORS["text"])])
        style.configure("TButton", background=COLORS["panel_hi"], foreground=COLORS["text"], padding=(10, 7), borderwidth=0)
        style.map("TButton", background=[("active", "#244061")])
        style.configure("Accent.TButton", background=COLORS["mint"], foreground=COLORS["bg"], padding=(12, 8))
        style.map("Accent.TButton", background=[("active", "#8BFFDB")])
        style.configure("TCheckbutton", background=COLORS["panel"], foreground=COLORS["text"])
        style.configure("Horizontal.TProgressbar", troughcolor=COLORS["panel_hi"], background=COLORS["mint"], thickness=8)

    def _build_shell(self):
        self.sidebar = tk.Frame(self.root, bg=COLORS["sidebar"], width=232)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        brand = tk.Frame(self.sidebar, bg=COLORS["sidebar"])
        brand.pack(fill="x", padx=20, pady=(26, 7))
        logo = tk.Canvas(brand, width=42, height=42, bg=COLORS["sidebar"], highlightthickness=0)
        logo.pack(side="left", padx=(0, 11))
        logo.create_oval(2, 2, 40, 40, fill=COLORS["panel_hi"], outline=COLORS["mint"], width=2)
        logo.create_line(11, 27, 17, 17, 23, 24, 31, 11, fill=COLORS["mint"], width=3, smooth=True)
        titlebox = tk.Frame(brand, bg=COLORS["sidebar"]); titlebox.pack(side="left")
        tk.Label(titlebox, text="PiNova", bg=COLORS["sidebar"], fg=COLORS["text"],
                 font=("Arial", 19, "bold")).pack(anchor="w")
        tk.Label(titlebox, text="SYSTEM STUDIO", bg=COLORS["sidebar"], fg=COLORS["mint"],
                 font=("Arial", 8, "bold")).pack(anchor="w", pady=(1, 0))
        tk.Label(self.sidebar, text="YOUR SYSTEM, AT A GLANCE", bg=COLORS["sidebar"], fg=COLORS["muted"],
                 font=("Arial", 8, "bold")).pack(anchor="w", padx=22, pady=(12, 24))

        self.nav = {}
        nav_items = [("Overview", "◈"), ("Processes", "▤"), ("History & Reports", "◷"),
                     ("Network", "⌁"), ("System Info", "▧"), ("Alert Center", "⚑"), ("Settings", "⚙")]
        for name, icon in nav_items:
            btn = tk.Button(self.sidebar, text=f"  {icon}   {name}", anchor="w", command=lambda n=name: self.navigate(n),
                            bg=COLORS["sidebar"], fg=COLORS["muted"], activebackground=COLORS["panel_hi"],
                            activeforeground=COLORS["mint"], relief="flat", bd=0, padx=18, pady=13,
                            font=("Arial", 10, "bold"), cursor="hand2")
            btn.pack(fill="x", padx=10, pady=2)
            self.nav[name] = btn

        bottom = tk.Frame(self.sidebar, bg=COLORS["sidebar"])
        bottom.pack(side="bottom", fill="x", padx=20, pady=20)
        tk.Frame(bottom, bg=COLORS["border"], height=1).pack(fill="x", pady=(0, 14))
        tk.Label(bottom, text="MONITORING STATUS", bg=COLORS["sidebar"], fg=COLORS["muted"],
                 font=("Arial", 8, "bold")).pack(anchor="w")
        self.sidebar_status = tk.Label(bottom, text="● Initializing", bg=COLORS["sidebar"], fg=COLORS["mint"],
                                       font=("Arial", 10, "bold"))
        self.sidebar_status.pack(anchor="w", pady=(6, 0))
        tk.Label(bottom, text=f"v{VERSION}  •  Local-first", bg=COLORS["sidebar"], fg=COLORS["muted"],
                 font=("Arial", 8)).pack(anchor="w", pady=(13, 0))

        self.main = tk.Frame(self.root, bg=COLORS["bg"])
        self.main.pack(side="left", fill="both", expand=True)
        self.topbar = tk.Frame(self.main, bg=COLORS["bg"])
        self.topbar.pack(fill="x", padx=28, pady=(23, 12))
        title_stack = tk.Frame(self.topbar, bg=COLORS["bg"]); title_stack.pack(side="left")
        self.page_title = tk.Label(title_stack, text="Overview", bg=COLORS["bg"], fg=COLORS["text"],
                                   font=("Arial", 24, "bold"))
        self.page_title.pack(anchor="w")
        self.page_subtitle = tk.Label(title_stack, text="Live system observatory", bg=COLORS["bg"], fg=COLORS["muted"],
                                      font=("Arial", 10))
        self.page_subtitle.pack(anchor="w", pady=(3, 0))
        right = tk.Frame(self.topbar, bg=COLORS["bg"]); right.pack(side="right", anchor="e")
        self.clock = tk.Label(right, text="", bg=COLORS["bg"], fg=COLORS["text"], font=("Arial", 10, "bold"))
        self.clock.pack(anchor="e")
        self.hostline = tk.Label(right, text=platform.node(), bg=COLORS["bg"], fg=COLORS["muted"], font=("Arial", 9))
        self.hostline.pack(anchor="e", pady=(4, 0))
        self.body = tk.Frame(self.main, bg=COLORS["bg"])
        self.body.pack(fill="both", expand=True, padx=28, pady=(4, 20))

    def navigate(self, page):
        self.page = page
        for key, btn in self.nav.items():
            selected = key == page
            btn.configure(bg=COLORS["panel_hi"] if selected else COLORS["sidebar"],
                          fg=COLORS["mint"] if selected else COLORS["muted"])
        self.page_title.configure(text=page)
        subtitles = {
            "Overview": "Live system observatory",
            "Processes": "See what is running and where resources go",
            "History & Reports": "Explore trends and export your monitoring data",
            "Network": "Live interface traffic and transfer rates",
            "System Info": "Hardware, operating system and application details",
            "Alert Center": "Threshold events and system health notices",
            "Settings": "Tune sampling, thresholds and the monitoring experience",
        }
        self.page_subtitle.configure(text=subtitles.get(page, "PiNova System Studio"))
        self._clear_body()
        if page == "Overview": self.show_overview()
        elif page == "Processes": self.show_processes()
        elif page == "History & Reports": self.show_history()
        elif page == "Network": self.show_network()
        elif page == "System Info": self.show_system_info()
        elif page == "Alert Center": self.show_alerts()
        elif page == "Settings": self.show_settings()

    def _clear_body(self):
        for child in self.body.winfo_children(): child.destroy()

    def _panel(self, parent, pad=16):
        return tk.Frame(parent, bg=COLORS["panel"], padx=pad, pady=pad,
                        highlightthickness=1, highlightbackground=COLORS["border"])

    def _section_title(self, parent, title, hint=None):
        row = tk.Frame(parent, bg=COLORS["panel"]); row.pack(fill="x", pady=(0, 10))
        tk.Label(row, text=title, bg=COLORS["panel"], fg=COLORS["text"],
                 font=("Arial", 11, "bold")).pack(side="left")
        if hint:
            tk.Label(row, text=hint, bg=COLORS["panel"], fg=COLORS["muted"],
                     font=("Arial", 9)).pack(side="right")
        return row

    def _create_metric_card(self, parent, key, title, accent, description):
        box = self._panel(parent, 14)
        box.grid_propagate(True)
        bar = tk.Frame(box, bg=accent, height=3); bar.pack(fill="x", pady=(0, 12))
        tk.Label(box, text=title.upper(), bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Arial", 8, "bold")).pack(anchor="w")
        value = tk.Label(box, text="--", bg=COLORS["panel"], fg=accent,
                         font=("Arial", 23, "bold"))
        value.pack(anchor="w", pady=(6, 1))
        detail = tk.Label(box, text=description, bg=COLORS["panel"], fg=COLORS["muted"],
                          font=("Arial", 9))
        detail.pack(anchor="w")
        track = tk.Canvas(box, height=6, bg=COLORS["panel_hi"], highlightthickness=0)
        track.pack(fill="x", pady=(12, 0))
        self.metric_cards[key] = (value, detail, track, accent)
        return box

    def show_overview(self):
        self.metric_cards = {}
        cards = tk.Frame(self.body, bg=COLORS["bg"]); cards.pack(fill="x", pady=(0, 14))
        for col in range(4): cards.grid_columnconfigure(col, weight=1, uniform="metric")
        metrics = [("temperature", "Temperature", COLORS["amber"], "CPU thermal sensor"),
                   ("cpu", "Processor", COLORS["blue"], "CPU utilization"),
                   ("memory", "Memory", COLORS["purple"], "RAM utilization"),
                   ("storage", "Storage", COLORS["mint"], "Home disk utilization")]
        for col, (key, title, color, desc) in enumerate(metrics):
            card = self._create_metric_card(cards, key, title, color, desc)
            card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 6, 0 if col == 3 else 6))

        status = self._panel(self.body, 12); status.pack(fill="x", pady=(0, 14))
        self.health_badge = tk.Label(status, text="● Checking system health", bg=COLORS["panel"],
                                     fg=COLORS["green"], font=("Arial", 10, "bold"))
        self.health_badge.pack(side="left")
        self.status_detail = tk.Label(status, text="", bg=COLORS["panel"], fg=COLORS["muted"], font=("Arial", 9))
        self.status_detail.pack(side="right")

        lower = tk.Frame(self.body, bg=COLORS["bg"]); lower.pack(fill="both", expand=True)
        lower.grid_columnconfigure(0, weight=7); lower.grid_columnconfigure(1, weight=3); lower.grid_rowconfigure(0, weight=1)
        graph_panel = self._panel(lower, 15); graph_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        ctl = self._section_title(graph_panel, "Performance timeline", "Last 90 samples")
        ttk.Combobox(ctl, textvariable=self.graph_metric, values=["CPU", "Memory", "Storage", "Temperature"],
                     state="readonly", width=13).pack(side="right", padx=(7, 0))
        self.graph_metric.trace_add("write", lambda *_: self.draw_graph())
        self.graph = tk.Canvas(graph_panel, bg=COLORS["panel"], highlightthickness=0)
        self.graph.pack(fill="both", expand=True)
        self.graph.bind("<Configure>", lambda _e: self.draw_graph())

        side = tk.Frame(lower, bg=COLORS["bg"]); side.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        quick = self._panel(side, 15); quick.pack(fill="x", pady=(0, 12))
        self._section_title(quick, "System snapshot")
        self.quick_labels = {}
        for label, key in [("Hostname", "host"), ("Uptime", "uptime"), ("CPU cores", "cores"), ("Platform", "platform")]:
            row = tk.Frame(quick, bg=COLORS["panel"]); row.pack(fill="x", pady=5)
            tk.Label(row, text=label, bg=COLORS["panel"], fg=COLORS["muted"], font=("Arial", 9)).pack(side="left")
            val = tk.Label(row, text="—", bg=COLORS["panel"], fg=COLORS["text"], font=("Arial", 9, "bold"))
            val.pack(side="right"); self.quick_labels[key] = val
        self._panel(side, 12).pack(fill="x")
        self.alert_summary = tk.Label(side.winfo_children()[-1], text="No active alerts", bg=COLORS["panel"],
                                      fg=COLORS["green"], justify="left", font=("Arial", 10, "bold"),
                                      wraplength=240)
        self.alert_summary.pack(anchor="w")
        self.update_overview()

    def _draw_bar(self, canvas, percent, color):
        if not canvas.winfo_exists(): return
        canvas.delete("all")
        w = max(canvas.winfo_width(), 80); h = max(canvas.winfo_height(), 6)
        canvas.create_rectangle(0, 0, w, h, fill=COLORS["panel_hi"], outline="")
        pct = max(0.0, min(100.0, float(percent)))
        bar_color = COLORS["red"] if pct >= 90 else COLORS["amber"] if pct >= 75 else color
        canvas.create_rectangle(0, 0, w * pct / 100, h, fill=bar_color, outline="")

    def update_overview(self):
        if self.page != "Overview": return
        r = self.latest
        display = {
            "temperature": ("N/A" if r["temperature"] is None else f'{r["temperature"]:.1f} °C', "Sensor reading", r["temperature"] or 0),
            "cpu": (f'{r["cpu"]:.1f} %', "Current processor load", r["cpu"]),
            "memory": (f'{r["memory"]:.1f} %', "Memory currently in use", r["memory"]),
            "storage": (f'{r["storage"]:.1f} %', "Home filesystem used", r["storage"]),
        }
        for key, (value, desc, pct) in display.items():
            if key in self.metric_cards:
                val, detail, track, accent = self.metric_cards[key]
                val.configure(text=value); detail.configure(text=desc)
                self._draw_bar(track, pct, accent)
        vals = [r["cpu"], r["memory"], r["storage"]]
        temp = r["temperature"]
        critical = max(vals) >= 95 or (temp is not None and temp >= max(85, self.settings["temperature_limit"] + 10))
        warning = max(vals) >= 75 or (temp is not None and temp >= self.settings["temperature_limit"])
        if critical:
            text, color = "● CRITICAL  ·  system resources are very high", COLORS["red"]
        elif warning:
            text, color = "● ATTENTION  ·  one or more readings are elevated", COLORS["amber"]
        else:
            text, color = "● ALL SYSTEMS NOMINAL", COLORS["green"]
        self.health_badge.configure(text=text, fg=color)
        self.status_detail.configure(text=f"{platform.node()}  ·  uptime {read_uptime()}")
        if hasattr(self, "quick_labels"):
            self.quick_labels["host"].configure(text=platform.node()[:22])
            self.quick_labels["uptime"].configure(text=read_uptime())
            self.quick_labels["cores"].configure(text=str(os.cpu_count() or "?"))
            self.quick_labels["platform"].configure(text=platform.machine() or platform.system())
            active = [v for v in self.active_alerts.values() if v]
            self.alert_summary.configure(text=(f"⚑ {len(active)} active threshold alert(s)" if active else "✓ No active threshold alerts"),
                                         fg=COLORS["amber"] if active else COLORS["green"])
        self.draw_graph()

    def draw_graph(self):
        if not hasattr(self, "graph") or not self.graph.winfo_exists(): return
        cv = self.graph; cv.delete("all")
        w, h = max(cv.winfo_width(), 380), max(cv.winfo_height(), 230)
        left, right, top, bottom = 58, 18, 18, 28
        gw, gh = w - left - right, h - top - bottom
        metric = self.graph_metric.get()
        key = {"CPU": "cpu", "Memory": "memory", "Storage": "storage", "Temperature": "temperature"}.get(metric, "cpu")
        points_data = [(stamp, row[key]) for stamp, row in self.samples if row.get(key) is not None]
        if len(points_data) < 2:
            cv.create_text(w/2, h/2, text="Gathering readings… the trend will appear shortly", fill=COLORS["muted"], font=("Arial", 10))
            return
        vals = [float(x[1]) for x in points_data]
        unit = "°C" if key == "temperature" else "%"
        lo, hi = min(vals), max(vals)
        if key != "temperature":
            lo, hi = min(0, lo), max(100, hi)
        if hi - lo < 1: hi, lo = hi + 1, lo - 1
        for i in range(5):
            y = top + gh * i / 4
            cv.create_line(left, y, left + gw, y, fill=COLORS["grid"])
            n = hi - (hi - lo) * i / 4
            cv.create_text(left - 9, y, text=f"{n:.0f}{unit}", fill=COLORS["muted"], anchor="e", font=("Arial", 8))
        coords = []
        for i, value in enumerate(vals):
            x = left + i / max(1, len(vals) - 1) * gw
            y = top + (hi - value) / (hi - lo) * gh
            coords.extend((x, y))
        color = {"CPU": COLORS["blue"], "Memory": COLORS["purple"], "Storage": COLORS["mint"], "Temperature": COLORS["amber"]}.get(metric, COLORS["blue"])
        if len(coords) >= 4:
            cv.create_line(*coords, fill=color, width=3, smooth=True, splinesteps=18)
        cv.create_oval(coords[-2]-4, coords[-1]-4, coords[-2]+4, coords[-1]+4, fill=COLORS["text"], outline=color, width=2)
        cv.create_text(left, h-8, text=points_data[0][0].strftime("%H:%M:%S"), fill=COLORS["muted"], anchor="w", font=("Arial", 8))
        cv.create_text(left+gw, h-8, text=points_data[-1][0].strftime("%H:%M:%S"), fill=COLORS["muted"], anchor="e", font=("Arial", 8))
        cv.create_text(w-right, top, text=f"Latest  {vals[-1]:.1f}{unit}", fill=COLORS["text"], anchor="ne", font=("Arial", 9, "bold"))

    def _sample(self, first=False):
        if not self.running: return
        self.clock.configure(text=datetime.now().strftime("%a, %d %b %Y   %H:%M:%S"))
        self.hostline.configure(text=f"{platform.node()}  ·  {platform.system()} {platform.release()}")
        if not self.paused:
            reading = {"temperature": read_temperature(), "cpu": read_cpu(),
                       "memory": read_memory(), "storage": read_storage()}
            self.latest = reading
            now = datetime.now()
            self.samples.append((now, reading.copy()))
            save_reading(reading)
            self._check_alerts(reading)
            self._update_network_snapshot()
            self.sidebar_status.configure(text="● Live monitoring", fg=COLORS["mint"])
            if self.page == "Overview": self.update_overview()
            elif self.page == "Processes": self.refresh_processes()
            elif self.page == "Network": self.update_network_view()
            elif self.page == "Alert Center": self.refresh_alerts_view()
        else:
            self.sidebar_status.configure(text="Ⅱ Monitoring paused", fg=COLORS["amber"])
        if self.running:
            self.root.after(int(self.settings["interval"]) * 1000, self._sample)

    def _check_alerts(self, reading):
        rules = [("temperature", "CPU temperature", reading.get("temperature"), self.settings["temperature_limit"], "°C"),
                 ("cpu", "CPU utilization", reading.get("cpu"), self.settings["cpu_limit"], "%"),
                 ("memory", "Memory utilization", reading.get("memory"), self.settings["memory_limit"], "%"),
                 ("storage", "Storage utilization", reading.get("storage"), self.settings["storage_limit"], "%")]
        for key, label, value, threshold, unit in rules:
            if value is None: continue
            high = float(value) >= float(threshold)
            was_high = self.active_alerts.get(key, False)
            if high and not was_high:
                self.alert_log.appendleft((datetime.now(), "WARNING", f"{label} reached {value:.1f}{unit} (limit {threshold}{unit})"))
            elif was_high and not high:
                self.alert_log.appendleft((datetime.now(), "RECOVERED", f"{label} returned to {value:.1f}{unit}"))
            self.active_alerts[key] = high

    def show_processes(self):
        bar = tk.Frame(self.body, bg=COLORS["bg"]); bar.pack(fill="x", pady=(0, 12))
        tk.Label(bar, text="Find process", bg=COLORS["bg"], fg=COLORS["muted"]).pack(side="left")
        search = ttk.Entry(bar, textvariable=self.process_search, width=27); search.pack(side="left", padx=(8, 12))
        search.bind("<KeyRelease>", lambda _e: self.refresh_processes())
        ttk.Button(bar, text="Refresh", command=self.refresh_processes).pack(side="left")
        ttk.Button(bar, text="End selected process", command=self.end_selected_process).pack(side="right")
        p = self._panel(self.body, 10); p.pack(fill="both", expand=True)
        columns = ("pid", "name", "cpu", "memory")
        self.process_tree = ttk.Treeview(p, columns=columns, show="headings")
        for key, label, width in [("pid", "PID", 80), ("name", "PROCESS", 360), ("cpu", "CPU %", 120), ("memory", "MEMORY %", 120)]:
            self.process_tree.heading(key, text=label)
            self.process_tree.column(key, width=width, anchor="w" if key == "name" else "center")
        ybar = ttk.Scrollbar(p, orient="vertical", command=self.process_tree.yview)
        self.process_tree.configure(yscrollcommand=ybar.set)
        self.process_tree.pack(side="left", fill="both", expand=True); ybar.pack(side="right", fill="y")
        tk.Label(self.body, text="Stopping a process may cause unsaved work to be lost. Avoid system-critical processes.",
                 bg=COLORS["bg"], fg=COLORS["muted"], font=("Arial", 9)).pack(anchor="w", pady=(9, 0))
        self.refresh_processes()

    def refresh_processes(self):
        if not hasattr(self, "process_tree") or not self.process_tree.winfo_exists(): return
        needle = self.process_search.get().strip().lower()
        self.process_tree.delete(*self.process_tree.get_children())
        for pid, name, cpu, memory in read_processes():
            if needle and needle not in name.lower() and needle not in str(pid): continue
            self.process_tree.insert("", "end", values=(pid, name, f"{cpu:.1f}", f"{memory:.1f}"))

    def end_selected_process(self):
        selection = self.process_tree.selection() if hasattr(self, "process_tree") else ()
        if not selection:
            messagebox.showinfo("No selection", "Pehle list mein ek process select karein."); return
        row = self.process_tree.item(selection[0], "values")
        pid, name = int(row[0]), row[1]
        if pid <= 1 or pid == os.getpid():
            messagebox.showwarning("Protected process", "This process is protected from this action."); return
        if not messagebox.askyesno("End process?", f"Send a stop request to '{name}' (PID {pid})?\n\nUnsaved work in that process may be lost."):
            return
        try:
            try:
                import psutil
                psutil.Process(pid).terminate()
            except ImportError:
                os.kill(pid, signal.SIGTERM)
            messagebox.showinfo("Stop request sent", f"Stop request sent to {name} (PID {pid}).")
        except ProcessLookupError:
            messagebox.showinfo("Already stopped", "That process has already ended.")
        except Exception as exc:
            if exc.__class__.__name__ == "NoSuchProcess":
                messagebox.showinfo("Already stopped", "That process has already ended.")
            elif exc.__class__.__name__ == "AccessDenied":
                messagebox.showerror("Permission denied", "You do not have permission to stop this process.")
            else:
                messagebox.showerror("Could not stop process", str(exc))
        except PermissionError:
            messagebox.showerror("Permission denied", "You do not have permission to stop this process.")
        except OSError as exc:
            messagebox.showerror("Could not stop process", str(exc))
        self.refresh_processes()

    def show_history(self):
        controls = tk.Frame(self.body, bg=COLORS["bg"]); controls.pack(fill="x", pady=(0, 12))
        tk.Label(controls, text="Metric", bg=COLORS["bg"], fg=COLORS["muted"]).pack(side="left")
        metric = ttk.Combobox(controls, textvariable=self.history_metric, values=["All", "Temperature", "CPU", "Memory", "Storage"], state="readonly", width=14)
        metric.pack(side="left", padx=(7, 15))
        tk.Label(controls, text="Period", bg=COLORS["bg"], fg=COLORS["muted"]).pack(side="left")
        period = ttk.Combobox(controls, textvariable=self.history_period, values=["Today", "Last 24 hours", "7 days", "30 days", "All time"], state="readonly", width=15)
        period.pack(side="left", padx=(7, 12))
        ttk.Button(controls, text="Refresh", command=self.refresh_history).pack(side="left")
        ttk.Button(controls, text="Export CSV", command=self.export_csv, style="Accent.TButton").pack(side="right")
        ttk.Button(controls, text="Save system report", command=self.export_report).pack(side="right", padx=(0, 8))
        panel = self._panel(self.body, 10); panel.pack(fill="both", expand=True)
        cols = ("date", "time", "temperature", "cpu", "memory", "storage")
        self.history_tree = ttk.Treeview(panel, columns=cols, show="headings")
        for key, label, width in [("date", "DATE", 100), ("time", "TIME", 90), ("temperature", "TEMP °C", 105), ("cpu", "CPU %", 100), ("memory", "MEMORY %", 110), ("storage", "STORAGE %", 110)]:
            self.history_tree.heading(key, text=label); self.history_tree.column(key, width=width, anchor="center")
        scroll = ttk.Scrollbar(panel, orient="vertical", command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=scroll.set)
        self.history_tree.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y")
        self.stats_label = tk.Label(self.body, text="", bg=COLORS["bg"], fg=COLORS["muted"], anchor="w", justify="left", font=("Arial", 9))
        self.stats_label.pack(fill="x", pady=(10, 0))
        metric.bind("<<ComboboxSelected>>", lambda _e: self.refresh_history())
        period.bind("<<ComboboxSelected>>", lambda _e: self.refresh_history())
        self.refresh_history()

    def _current_history(self):
        rows = query_history(self.history_period.get(), 20000)
        metric = self.history_metric.get()
        if metric == "All": return rows
        idx = {"Temperature": 2, "CPU": 3, "Memory": 4, "Storage": 5}.get(metric)
        return [row for row in rows if row[idx] is not None] if idx is not None else rows

    def refresh_history(self):
        if not hasattr(self, "history_tree") or not self.history_tree.winfo_exists(): return
        rows = self._current_history()
        self.history_tree.delete(*self.history_tree.get_children())
        def fmt(value): return "—" if value is None else f"{float(value):.1f}"
        for row in reversed(rows[-4000:]):
            date, tm, temp, cpu, memory, storage = row
            self.history_tree.insert("", "end", values=(date, tm, fmt(temp), fmt(cpu), fmt(memory), fmt(storage)))
        stats = []
        for idx, metric_name, label, unit in [(2, "Temperature", "Temp", "°C"), (3, "CPU", "CPU", "%"), (4, "Memory", "Memory", "%"), (5, "Storage", "Storage", "%")]:
            vals = [float(r[idx]) for r in rows if r[idx] is not None]
            if vals and (self.history_metric.get() == "All" or metric_name == self.history_metric.get()):
                stats.append(f"{label}: avg {sum(vals)/len(vals):.1f}{unit}  ·  min {min(vals):.1f}{unit}  ·  max {max(vals):.1f}{unit}")
        self.stats_label.configure(text=f"{len(rows):,} readings  ·  " + ("  |  ".join(stats) if stats else "No readings for this filter"))

    def export_csv(self):
        rows = self._current_history()
        if not rows:
            messagebox.showinfo("Export", "No history records match this filter."); return
        path = filedialog.asksaveasfilename(title="Export PiNova history", defaultextension=".csv",
            filetypes=[("CSV file", "*.csv")], initialfile="pinova_history.csv")
        if not path: return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                writer.writerow(["Date", "Time", "Temperature °C", "CPU %", "Memory %", "Storage %"])
                writer.writerows(rows)
            messagebox.showinfo("Export complete", f"History saved to:\n{path}")
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))

    def show_network(self):
        row = tk.Frame(self.body, bg=COLORS["bg"]); row.pack(fill="x", pady=(0, 13))
        self.net_card_labels = {}
        for key, title, color in [("rx", "RECEIVED RATE", COLORS["blue"]), ("tx", "SENT RATE", COLORS["mint"]), ("interfaces", "INTERFACES", COLORS["purple"])]:
            p = self._panel(row, 14); p.pack(side="left", fill="both", expand=True, padx=(0, 8))
            tk.Label(p, text=title, bg=COLORS["panel"], fg=COLORS["muted"], font=("Arial", 8, "bold")).pack(anchor="w")
            val = tk.Label(p, text="Calculating…", bg=COLORS["panel"], fg=color, font=("Arial", 20, "bold")); val.pack(anchor="w", pady=(7, 0))
            self.net_card_labels[key] = val
        p = self._panel(self.body, 10); p.pack(fill="both", expand=True)
        self._section_title(p, "Network interfaces", "Counters supplied by the operating system")
        cols = ("interface", "received", "sent", "rxrate", "txrate")
        self.net_tree = ttk.Treeview(p, columns=cols, show="headings")
        for key, title, width in [("interface", "INTERFACE", 180), ("received", "TOTAL RECEIVED", 160), ("sent", "TOTAL SENT", 160), ("rxrate", "RX RATE", 150), ("txrate", "TX RATE", 150)]:
            self.net_tree.heading(key, text=title); self.net_tree.column(key, width=width, anchor="w" if key == "interface" else "center")
        self.net_tree.pack(fill="both", expand=True)
        self.update_network_view()

    def _update_network_snapshot(self):
        current = read_network(); now = time.monotonic()
        rx_rate, tx_rate = 0, 0
        if self.net_prev:
            old_time, old = self.net_prev
            elapsed = max(0.001, now - old_time)
            rx_rate = sum(max(0, current.get(k, (0, 0))[0] - v[0]) for k, v in old.items()) / elapsed
            tx_rate = sum(max(0, current.get(k, (0, 0))[1] - v[1]) for k, v in old.items()) / elapsed
        per_interface = {}
        if self.net_prev:
            old_time, old = self.net_prev
            elapsed = max(0.001, now - old_time)
            for iface, (rx, tx) in current.items():
                before = old.get(iface, (rx, tx))
                per_interface[iface] = (max(0, rx - before[0]) / elapsed,
                                        max(0, tx - before[1]) / elapsed)
        else:
            per_interface = {iface: (0.0, 0.0) for iface in current}
        self.net_prev = (now, current)
        self.net_snapshot = {"interfaces": current, "rx_rate": rx_rate, "tx_rate": tx_rate,
                             "per_interface_rates": per_interface}

    def update_network_view(self):
        if not hasattr(self, "net_tree") or not self.net_tree.winfo_exists(): return
        data = self.net_snapshot.get("interfaces", {})
        self.net_card_labels["rx"].configure(text=human_bytes(self.net_snapshot.get("rx_rate", 0)) + "/s")
        self.net_card_labels["tx"].configure(text=human_bytes(self.net_snapshot.get("tx_rate", 0)) + "/s")
        self.net_card_labels["interfaces"].configure(text=str(len([k for k in data if k != "lo"])))
        self.net_tree.delete(*self.net_tree.get_children())
        # Linux gives totals, and rate approximations come from the last sample.
        rates = self.net_snapshot.get("per_interface_rates", {})
        for iface, (rx, tx) in sorted(data.items()):
            rx_rate, tx_rate = rates.get(iface, (0, 0))
            self.net_tree.insert("", "end", values=(iface, human_bytes(rx), human_bytes(tx),
                human_bytes(rx_rate) + "/s", human_bytes(tx_rate) + "/s"))

    def show_system_info(self):
        self._info_card("HOST & OS", [("Hostname", platform.node()), ("Operating system", f"{platform.system()} {platform.release()}"),
            ("Architecture", platform.machine()), ("Python", platform.python_version()), ("Uptime", read_uptime())])
        self._info_card("HARDWARE", [("Processor", read_cpu_model()), ("Logical CPU cores", str(os.cpu_count() or "Unknown")),
            ("Home directory", str(Path.home())), ("Current process ID", str(os.getpid()))])
        self._info_card("DATA & DIAGNOSTICS", [("History database", str(DB_PATH)), ("Settings file", str(CONFIG_PATH)),
            ("Application version", VERSION), ("UI toolkit", f"Tk {self.root.tk.call('info', 'patchlevel')}")])
        bar = tk.Frame(self.body, bg=COLORS["bg"]); bar.pack(fill="x", pady=(4, 0))
        ttk.Button(bar, text="Export system report…", command=self.export_report, style="Accent.TButton").pack(side="left")
        ttk.Button(bar, text="Open history folder", command=self.open_history_folder).pack(side="left", padx=8)

    def _info_card(self, title, items):
        p = self._panel(self.body, 14); p.pack(fill="x", pady=(0, 10))
        tk.Label(p, text=title, bg=COLORS["panel"], fg=COLORS["mint"], font=("Arial", 9, "bold")).pack(anchor="w", pady=(0, 8))
        for label, value in items:
            row = tk.Frame(p, bg=COLORS["panel"]); row.pack(fill="x", pady=2)
            tk.Label(row, text=label, bg=COLORS["panel"], fg=COLORS["muted"], font=("Arial", 9)).pack(side="left")
            tk.Label(row, text=str(value), bg=COLORS["panel"], fg=COLORS["text"], font=("Arial", 9, "bold"),
                     wraplength=620, justify="right").pack(side="right")

    def export_report(self):
        now = datetime.now()
        r = self.latest
        history = query_history("Last 24 hours", 20000)
        lines = [f"{APP_NAME} v{VERSION} — System Report", f"Generated: {now:%Y-%m-%d %H:%M:%S}", "",
                 "SYSTEM", f"Hostname: {platform.node()}", f"OS: {platform.system()} {platform.release()}",
                 f"Architecture: {platform.machine()}", f"CPU: {read_cpu_model()}", f"Cores: {os.cpu_count()}",
                 f"Uptime: {read_uptime()}", "", "CURRENT READINGS",
                 f"Temperature: {r['temperature'] if r['temperature'] is not None else 'N/A'} °C",
                 f"CPU: {r['cpu']:.1f}%", f"Memory: {r['memory']:.1f}%", f"Storage: {r['storage']:.1f}%",
                 f"History rows in last 24 hours: {len(history)}", "", "DATABASE", str(DB_PATH), ""]
        path = filedialog.asksaveasfilename(title="Save system report", defaultextension=".txt",
            filetypes=[("Text report", "*.txt")], initialfile="pinova_system_report.txt")
        if not path: return
        try:
            Path(path).write_text("\n".join(lines), encoding="utf-8")
            messagebox.showinfo("Report saved", f"System report saved to:\n{path}")
        except OSError as exc:
            messagebox.showerror("Report failed", str(exc))

    def open_history_folder(self):
        try:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            if platform.system() == "Windows":
                os.startfile(str(DB_PATH.parent))
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", str(DB_PATH.parent)])
            else:
                subprocess.Popen(["xdg-open", str(DB_PATH.parent)])
        except Exception as exc:
            messagebox.showerror("Open folder failed", f"{exc}\n\n{DB_PATH.parent}")

    def show_alerts(self):
        top = tk.Frame(self.body, bg=COLORS["bg"]); top.pack(fill="x", pady=(0, 12))
        ttk.Button(top, text="Clear event list", command=self.clear_alerts).pack(side="right")
        p = self._panel(self.body, 10); p.pack(fill="both", expand=True)
        cols = ("time", "type", "event")
        self.alert_tree = ttk.Treeview(p, columns=cols, show="headings")
        for key, label, width in [("time", "TIME", 175), ("type", "EVENT", 120), ("event", "DETAILS", 670)]:
            self.alert_tree.heading(key, text=label); self.alert_tree.column(key, width=width, anchor="w")
        self.alert_tree.pack(fill="both", expand=True)
        self.refresh_alerts_view()

    def refresh_alerts_view(self):
        if not hasattr(self, "alert_tree") or not self.alert_tree.winfo_exists(): return
        self.alert_tree.delete(*self.alert_tree.get_children())
        for stamp, kind, detail in list(self.alert_log):
            self.alert_tree.insert("", "end", values=(stamp.strftime("%Y-%m-%d %H:%M:%S"), kind, detail))

    def clear_alerts(self):
        self.alert_log.clear()
        self.refresh_alerts_view()

    def show_settings(self):
        p = self._panel(self.body, 18); p.pack(fill="x", pady=(0, 13))
        tk.Label(p, text="MONITORING", bg=COLORS["panel"], fg=COLORS["mint"], font=("Arial", 9, "bold")).pack(anchor="w", pady=(0, 10))
        row = tk.Frame(p, bg=COLORS["panel"]); row.pack(fill="x", pady=5)
        tk.Label(row, text="Sampling interval", bg=COLORS["panel"], fg=COLORS["text"]).pack(side="left")
        self.interval_var = tk.StringVar(value=str(self.settings["interval"]))
        ttk.Combobox(row, textvariable=self.interval_var, values=["2", "3", "5", "10", "15", "30", "60"],
                     state="readonly", width=10).pack(side="right")
        tk.Label(row, text="seconds", bg=COLORS["panel"], fg=COLORS["muted"]).pack(side="right", padx=8)
        tk.Label(p, text="Lower values create more history records.", bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Arial", 9)).pack(anchor="w", pady=(4, 0))

        p2 = self._panel(self.body, 18); p2.pack(fill="x", pady=(0, 13))
        tk.Label(p2, text="ALERT THRESHOLDS", bg=COLORS["panel"], fg=COLORS["mint"], font=("Arial", 9, "bold")).pack(anchor="w", pady=(0, 12))
        self.threshold_vars = {}
        specs = [("temperature_limit", "Temperature warning", "°C"), ("cpu_limit", "CPU warning", "%"),
                 ("memory_limit", "Memory warning", "%"), ("storage_limit", "Storage warning", "%")]
        for key, label, unit in specs:
            row = tk.Frame(p2, bg=COLORS["panel"]); row.pack(fill="x", pady=5)
            tk.Label(row, text=label, bg=COLORS["panel"], fg=COLORS["text"]).pack(side="left")
            var = tk.StringVar(value=str(self.settings[key])); self.threshold_vars[key] = var
            ttk.Entry(row, textvariable=var, width=10).pack(side="right")
            tk.Label(row, text=unit, bg=COLORS["panel"], fg=COLORS["muted"]).pack(side="right", padx=8)
        ttk.Button(p2, text="Save settings", command=self.apply_settings, style="Accent.TButton").pack(anchor="e", pady=(12, 0))

        p3 = self._panel(self.body, 15); p3.pack(fill="x")
        tk.Label(p3, text="DATA LOCATION", bg=COLORS["panel"], fg=COLORS["mint"], font=("Arial", 9, "bold")).pack(anchor="w")
        tk.Label(p3, text=str(DB_PATH), bg=COLORS["panel"], fg=COLORS["muted"], wraplength=800,
                 justify="left").pack(anchor="w", pady=(7, 10))
        row = tk.Frame(p3, bg=COLORS["panel"]); row.pack(fill="x")
        ttk.Button(row, text="Open history folder", command=self.open_history_folder).pack(side="left")
        ttk.Button(row, text="Export system report", command=self.export_report).pack(side="left", padx=8)
        status_row = tk.Frame(p3, bg=COLORS["panel"]); status_row.pack(fill="x", pady=(14, 0))
        self.pause_button = ttk.Button(status_row, text="Resume monitoring" if self.paused else "Pause monitoring",
                                       command=self.toggle_pause)
        self.pause_button.pack(side="left")

    def apply_settings(self):
        try:
            interval = int(self.interval_var.get())
            if interval < 2 or interval > 60: raise ValueError("interval must be 2–60 seconds")
            new = {"interval": interval}
            for key, var in self.threshold_vars.items():
                value = float(var.get())
                maximum = 120 if key == "temperature_limit" else 100
                if value < 1 or value > maximum: raise ValueError(f"{key}: enter a value from 1 to {maximum}")
                new[key] = value
            self.settings.update(new)
            save_settings(self.settings)
            messagebox.showinfo("Settings saved", "Your monitoring settings have been saved.")
        except (ValueError, OSError) as exc:
            messagebox.showerror("Invalid settings", str(exc))

    def toggle_pause(self):
        self.paused = not self.paused
        if self.page == "Settings":
            self.navigate("Settings")
        self.sidebar_status.configure(text="Ⅱ Monitoring paused" if self.paused else "● Live monitoring",
                                      fg=COLORS["amber"] if self.paused else COLORS["mint"])

    def close(self):
        self.running = False
        self.root.destroy()


def main():
    ensure_database()
    root = tk.Tk()
    try:
        PiNovaApp(root)
        root.mainloop()
    except Exception as exc:
        try:
            messagebox.showerror(APP_NAME, f"PiNova could not start:\n{exc}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
