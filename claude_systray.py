"""
Claude Usage Taskbar Widget — Windows
Docks a small always-on-top window to the taskbar showing "x% / y% / z%"
with color-coded percentages. Double-click or left-click opens the visual dialog.
Right-click shows menu.
"""

import sys
sys.dont_write_bytecode = True

# ── pythonw crash protection ─────────────────────────────────────────────
# When launched via pythonw.exe (e.g. "Open With" from File Explorer),
# stdout/stderr may be None on some Python versions, causing print() to crash.
# Redirect them to devnull if they're missing, and log crashes to a file.
import os as _os
import traceback as _tb
from pathlib import Path as _Path

_LOG_PATH = _Path(__file__).parent / "crash.log"

if sys.stdout is None:
    sys.stdout = open(_os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(_os.devnull, "w")

def _crash_handler(exc_type, exc_value, exc_tb):
    """Write unhandled exceptions to crash.log so pythonw failures aren't silent."""
    try:
        with open(_LOG_PATH, "a") as f:
            from datetime import datetime
            f.write(f"\n{'='*60}\n{datetime.now()}\n")
            _tb.print_exception(exc_type, exc_value, exc_tb, file=f)
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = _crash_handler

DEBUG = "--debug" in sys.argv

def debug(msg):
    if DEBUG:
        print(msg)

import json
import os
import time
import threading
import webbrowser
import ctypes
from ctypes import wintypes

# Declare DPI awareness BEFORE importing tkinter — gives real pixel coordinates
ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE

# Set AppUserModelID so Windows uses our icon in the taskbar, not Python's
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ClaudeUsageSystray")

import tkinter as tk
from datetime import datetime, timezone
from collections import deque
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, ImageTk
import pystray
import comtypes
from comtypes import GUID, HRESULT, COMMETHOD
from comtypes.automation import VARIANT

# ── Per-window AppUserModelID via IPropertyStore (taskbar grouping) ──
class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", comtypes.GUID), ("pid", wintypes.DWORD)]

_PKEY_AppUserModel_ID = _PROPERTYKEY()
_PKEY_AppUserModel_ID.fmtid = GUID("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}")
_PKEY_AppUserModel_ID.pid = 5

class _IPropertyStore(comtypes.IUnknown):
    _iid_ = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], ctypes.POINTER(wintypes.DWORD), "cProps")),
        COMMETHOD([], HRESULT, "GetAt", (["in"], wintypes.DWORD, "iProp"), (["out"], ctypes.POINTER(_PROPERTYKEY), "pkey")),
        COMMETHOD([], HRESULT, "GetValue", (["in"], ctypes.POINTER(_PROPERTYKEY), "key"), (["out"], ctypes.POINTER(VARIANT), "pv")),
        COMMETHOD([], HRESULT, "SetValue", (["in"], ctypes.POINTER(_PROPERTYKEY), "key"), (["in"], ctypes.POINTER(VARIANT), "propvar")),
        COMMETHOD([], HRESULT, "Commit"),
    ]

_SHGetPropertyStoreForWindow = ctypes.windll.shell32.SHGetPropertyStoreForWindow
_SHGetPropertyStoreForWindow.argtypes = [wintypes.HWND, ctypes.POINTER(comtypes.GUID), ctypes.POINTER(ctypes.POINTER(_IPropertyStore))]
_SHGetPropertyStoreForWindow.restype = HRESULT

def set_window_app_id(hwnd, app_id="ClaudeUsageSystray"):
    """Set AppUserModelID on a window so it groups with others sharing the same ID."""
    try:
        store = ctypes.POINTER(_IPropertyStore)()
        iid = _IPropertyStore._iid_
        hr = _SHGetPropertyStoreForWindow(hwnd, ctypes.byref(iid), ctypes.byref(store))
        if hr == 0:
            var = VARIANT(app_id)
            store.SetValue(ctypes.byref(_PKEY_AppUserModel_ID), ctypes.byref(var))
    except Exception:
        pass  # best-effort — grouping is nice-to-have, not critical

# ── Paths ─────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
CREDS_PATH = Path.home() / ".claude" / ".credentials.json"
ICON_PATH = SCRIPT_DIR / "usage-icon.png"
API_URL = "https://api.anthropic.com/api/oauth/usage"
API_HEADERS_EXTRA = {"anthropic-beta": "oauth-2025-04-20"}
GITHUB_URL = "https://github.com/albazzaztariq/Claude-Usage-Systray"
ISSUES_URL = "https://github.com/albazzaztariq/Claude-Usage-Systray/issues/new"
ACCOUNT_SETTINGS_URL = "https://claude.ai/settings/usage"
POLL_INTERVAL = 300
CONFIG_PATH = SCRIPT_DIR / "config.json"

# ── Config / Settings ─────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "start_on_startup": False,
    "background_collection": False,  # headless daemon polls usage for graphs
    "collector_interval_sec": 600,   # 10 minutes default
    "scale_pct": 100,       # 1-400, affects text and widget size
    "poll_interval_sec": 300, # 1-1800 seconds
    "show_last_refresh": True,
    "refresh_display_mode": "exact",  # "exact" or "approximate"
    "show_depletion_estimates": True,
    "show_session": True,
    "show_weekly": True,
    "show_sonnet": True,
    "show_reddit_ticker": True,
    "widget_x": None,       # None = auto-center
    "widget_y": None,       # None = above taskbar
    "widget_w": None,       # None = auto-size
    "widget_h": 28,
    "bg_color": "#1e1e2e",
    "color_sufficient": "#64c864",
    "color_partial": "#e6c832",
    "color_depleted": "#e65050",
    "color_text": "#ffffff",
}

config = {}


def load_config():
    global config
    config = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r") as f:
                saved = json.load(f)
            config.update(saved)
        except Exception as e:
            debug(f"[WARN] Config load failed: {e}")


def save_config():
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        debug(f"[ERROR] Config save failed: {e}")


def scaled(base_size):
    """Return a font size scaled by config scale_pct."""
    return max(1, int(base_size * config.get("scale_pct", 100) / 100))


def apply_scale_live():
    """Reconfigure widget label fonts and resize based on current scale_pct."""
    if not taskbar_widget:
        return
    fs = scaled(11)
    fs_sep = scaled(10)
    bg_c = config.get("bg_color", "#1e1e2e")

    fs_time = scaled(8)
    taskbar_widget._session_lbl.config(font=("Segoe UI Semibold", fs))
    taskbar_widget._weekly_lbl.config(font=("Segoe UI Semibold", fs))
    taskbar_widget._sonnet_lbl.config(font=("Segoe UI Semibold", fs))
    taskbar_widget._sep1.config(font=("Segoe UI", fs_sep))
    taskbar_widget._sep2.config(font=("Segoe UI", fs_sep))
    taskbar_widget._time_lbl.config(font=("Segoe UI", fs_time))

    # Update bg color on all widget elements
    taskbar_widget.configure(bg=bg_c)
    for child in [taskbar_widget._session_lbl, taskbar_widget._weekly_lbl,
                  taskbar_widget._sonnet_lbl, taskbar_widget._sep1, taskbar_widget._sep2,
                  taskbar_widget._time_lbl]:
        child.config(bg=bg_c)
    # Find frame children and update them too
    for child in taskbar_widget.winfo_children():
        if isinstance(child, tk.Frame):
            child.config(bg=bg_c)
            for grandchild in child.winfo_children():
                if isinstance(grandchild, tk.Frame):
                    grandchild.config(bg=bg_c)

    # Immediately show/hide time label based on current config
    show_time = config.get("show_last_refresh", True)
    if not show_time and getattr(taskbar_widget, '_time_visible', False):
        taskbar_widget._time_lbl.pack_forget()
        taskbar_widget._time_visible = False
    elif show_time and not getattr(taskbar_widget, '_time_visible', False) and last_refresh:
        taskbar_widget._time_lbl.pack(side="top", in_=taskbar_widget._outer_frame,
                                       before=taskbar_widget._pct_frame)
        taskbar_widget._time_visible = True

    # Resize widget to fit new font sizes
    # Clear geometry constraint so tkinter can recalculate natural size
    taskbar_widget.update_idletasks()
    new_w = taskbar_widget.winfo_reqwidth()
    new_h = taskbar_widget.winfo_reqheight()
    x = taskbar_widget.winfo_x()
    y = taskbar_widget.winfo_y()
    taskbar_widget.geometry(f"{new_w}x{new_h}+{x}+{y}")

    # Save the new size
    config["widget_w"] = new_w
    config["widget_h"] = new_h


def save_widget_geometry():
    """Save the current widget position and size to config."""
    if taskbar_widget:
        config["widget_x"] = taskbar_widget.winfo_x()
        config["widget_y"] = taskbar_widget.winfo_y()
        config["widget_w"] = taskbar_widget.winfo_width()
        config["widget_h"] = taskbar_widget.winfo_height()
        save_config()


# ── State ─────────────────────────────────────────────────────────────────

usage_data = {}
creds_data = {}
last_refresh = None
usage_history = deque(maxlen=500)        # (timestamp, session_pct, weekly_pct, sonnet_pct)
HISTORY_PATH = SCRIPT_DIR / "usage_history.json"
visual_window = None
taskbar_widget = None  # The docked taskbar window
fetch_error = False    # True when API fetch has failed after retries
last_fetch_error_detail = ""  # HTTP status code or error message from last failure


def save_usage_history():
    """Persist usage_history to disk."""
    try:
        with open(HISTORY_PATH, "w") as f:
            json.dump(list(usage_history), f)
    except Exception:
        pass

def load_usage_history():
    """Load usage_history from disk."""
    global usage_history
    try:
        if HISTORY_PATH.exists():
            with open(HISTORY_PATH, "r") as f:
                data = json.load(f)
            usage_history = deque(data, maxlen=500)
    except Exception:
        pass

load_usage_history()


# ── Credentials ───────────────────────────────────────────────────────────

def load_creds():
    global creds_data
    try:
        with open(CREDS_PATH, "r") as f:
            creds_data = json.load(f).get("claudeAiOauth", {})
        return creds_data.get("accessToken")
    except Exception as e:
        debug(f"[ERROR] Credentials: {e}")
        return None


def get_email():
    return "albazzaztariq@gmail.com"


def get_plan_label():
    tier = creds_data.get("rateLimitTier", "")
    sub = creds_data.get("subscriptionType", "unknown")
    if "max_20x" in tier: return "Max 20x"
    elif "max_5x" in tier: return "Max 5x"
    elif sub == "max": return "Max"
    elif sub == "pro": return "Pro"
    elif sub == "free": return "Free"
    return sub.capitalize() if sub else "Unknown"


# ── API ───────────────────────────────────────────────────────────────────

def _fetch_once():
    """Single API fetch attempt. Returns True on success."""
    global usage_data, last_refresh, last_fetch_error_detail
    token = load_creds()
    if not token:
        last_fetch_error_detail = "No credentials"
        return False
    try:
        r = requests.get(API_URL, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            **API_HEADERS_EXTRA,
        }, timeout=10)
        if r.status_code == 200:
            usage_data = r.json()
            last_refresh = datetime.now(timezone.utc)
            session_pct = usage_data.get("five_hour", {}).get("utilization", 0)
            weekly_pct = usage_data.get("seven_day", {}).get("utilization", 0)
            ss = usage_data.get("seven_day_sonnet", {})
            sonnet_pct = ss.get("utilization", 0) if ss else 0
            usage_history.append((time.time(), session_pct, weekly_pct, sonnet_pct))
            save_usage_history()
            return True
        else:
            status_messages = {
                429: "Too Many Requests",
                401: "Unauthorized",
                403: "Forbidden",
                500: "Server Error",
                502: "Bad Gateway",
                503: "Service Unavailable",
            }
            last_fetch_error_detail = status_messages.get(r.status_code, f"HTTP {r.status_code}")
            debug(f"[ERROR] API status {r.status_code}")
    except requests.exceptions.Timeout:
        last_fetch_error_detail = "Timeout"
        debug("[ERROR] API: Timeout")
    except requests.exceptions.ConnectionError:
        last_fetch_error_detail = "No connection"
        debug("[ERROR] API: Connection error")
    except Exception as e:
        last_fetch_error_detail = str(e)[:30]
        debug(f"[ERROR] API: {e}")
    return False


def fetch_usage():
    """Fetch with retries — tries every 2s for 20s. Sets fetch_error on failure."""
    global fetch_error
    for attempt in range(10):
        if _fetch_once():
            fetch_error = False
            return True
        if attempt < 9:
            debug(f"[WARN] Fetch failed, retry {attempt + 1}/10...")
            time.sleep(2)
    debug("[ERROR] All fetch retries exhausted.")
    fetch_error = True
    return False


# ── Helpers ───────────────────────────────────────────────────────────────

def format_reset(iso_str):
    if not iso_str: return "unknown"
    try:
        delta = datetime.fromisoformat(iso_str) - datetime.now(timezone.utc)
        total_min = max(0, int(delta.total_seconds() / 60))
        h, m = divmod(total_min, 60)
        if h >= 24:
            d, h = divmod(h, 24)
            return f"{d}d {h}h {m}m"
        return f"{h}h {m}m" if h > 0 else f"{m}m"
    except:
        return "unknown"


def estimate_depletion(metric_idx=1):
    """Estimate depletion for a metric. idx: 1=session, 2=weekly, 3=sonnet.
    Returns: None (need data points), "need_time" (need 60s), or a time string."""
    if len(usage_history) < 2: return None
    first = usage_history[0]
    last = usage_history[-1]
    t0, t1 = first[0], last[0]
    p0, p1 = first[metric_idx], last[metric_idx]
    dt = t1 - t0
    if dt < 60: return "need_time"
    dp = p1 - p0
    if dp <= 0: return "never"
    mins = ((100.0 - p1) / (dp / dt)) / 60
    if mins < 60: return f"~{int(mins)}m"
    return f"~{int(mins // 60)}h {int(mins % 60)}m"


def pct_color_hex(pct):
    if pct < 50: return config.get("color_sufficient", "#64c864")
    elif pct < 75: return config.get("color_partial", "#e6c832")
    elif pct < 90: return config.get("color_partial", "#e6c832")
    return config.get("color_depleted", "#e65050")


def pct_color_rgb(pct):
    if pct < 50: return (100, 200, 100)
    elif pct < 75: return (230, 200, 50)
    elif pct < 90: return (230, 150, 50)
    return (230, 80, 80)


def get_taskbar_height():
    """Get the Windows taskbar height and position."""
    try:
        from ctypes import Structure, c_long, c_ulong, byref, windll

        class RECT(Structure):
            _fields_ = [("left", c_long), ("top", c_long), ("right", c_long), ("bottom", c_long)]

        class APPBARDATA(Structure):
            _fields_ = [
                ("cbSize", c_ulong), ("hWnd", c_ulong), ("uCallbackMessage", c_ulong),
                ("uEdge", c_ulong), ("rc", RECT), ("lParam", c_long),
            ]

        abd = APPBARDATA()
        abd.cbSize = ctypes.sizeof(APPBARDATA)
        windll.shell32.SHAppBarMessage(5, byref(abd))  # ABM_GETTASKBARPOS = 5
        return abd.rc.top, abd.rc.left, abd.rc.right, abd.rc.bottom
    except:
        # Fallback: assume taskbar at bottom, 48px tall
        return None


# ── Taskbar Docked Widget ─────────────────────────────────────────────────

def create_taskbar_widget():
    """Create a tiny borderless always-on-top overlay widget."""
    global taskbar_widget

    root = tk.Tk()
    taskbar_widget = root
    bg_c = config.get("bg_color", "#1e1e2e")
    root.overrideredirect(True)  # No title bar, no border
    root.attributes("-topmost", True)  # Always on top
    root.configure(bg=bg_c, highlightbackground="#4a4a6c", highlightthickness=1)

    # Hide while we set up geometry (Win11 overrideredirect fix)
    root.withdraw()

    # Content frame — two rows: last-fetched time on top, percentages below
    outer = tk.Frame(root, bg=bg_c)
    outer.pack(fill="both", expand=True)

    fs = scaled(11)
    fs_sep = scaled(10)
    fs_time = scaled(8)

    # Last-fetched label (not packed yet — update_time_label manages visibility)
    _text_color = config.get("color_text", "#ffffff")
    root._time_lbl = tk.Label(outer, text="", font=("Segoe UI", fs_time),
                               fg=_text_color, bg=bg_c)

    # Percentage row
    frame = tk.Frame(outer, bg=bg_c)
    frame.pack(side="top")
    root._outer_frame = outer
    root._pct_frame = frame

    root._session_lbl = tk.Label(frame, text="---%", font=("Segoe UI Semibold", fs),
                                  fg="#64c864", bg=bg_c)
    root._session_lbl.pack(side="left", padx=(6, 0))

    root._sep1 = tk.Label(frame, text="/", font=("Segoe UI", fs_sep), fg="#585b70", bg=bg_c)
    root._sep1.pack(side="left", padx=2)

    root._weekly_lbl = tk.Label(frame, text="---%", font=("Segoe UI Semibold", fs),
                                 fg="#64c864", bg=bg_c)
    root._weekly_lbl.pack(side="left")

    root._sep2 = tk.Label(frame, text="/", font=("Segoe UI", fs_sep), fg="#585b70", bg=bg_c)
    root._sep2.pack(side="left", padx=2)

    root._sonnet_lbl = tk.Label(frame, text="---%", font=("Segoe UI Semibold", fs),
                                 fg="#64c864", bg=bg_c)
    root._sonnet_lbl.pack(side="left", padx=(0, 6))

    # Size and position — use saved config or auto-calculate
    root.update_idletasks()
    auto_w = root.winfo_reqwidth()
    auto_h = root.winfo_reqheight()
    widget_w = config.get("widget_w") or auto_w
    widget_h = max(auto_h, config.get("widget_h") or auto_h)

    if config.get("widget_x") is not None and config.get("widget_y") is not None:
        x = config["widget_x"]
        y = config["widget_y"]
    else:
        screen_w = root.winfo_screenwidth()
        work_rect = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_rect), 0)
        work_bottom = work_rect.bottom
        x = (screen_w - widget_w) // 2
        y = work_bottom - widget_h - 10

    root.geometry(f"{widget_w}x{widget_h}+{x}+{y}")
    debug(f"[DEBUG] Widget geometry: {widget_w}x{widget_h}+{x}+{y}")

    # Force Windows to actually show the borderless window
    root.deiconify()
    root.update()
    root.lift()
    root.focus_force()

    # Hover tooltip
    root._tooltip = None

    def show_tooltip(event):
        if root._tooltip or root._menu_open or fetch_error: return
        fh = usage_data.get("five_hour", {})
        sd = usage_data.get("seven_day", {})
        sr = format_reset(fh.get("resets_at"))
        wr = format_reset(sd.get("resets_at"))
        depl = estimate_depletion(1)
        text = f"Session resets in {sr}\nWeekly resets in {wr}"
        if depl and depl not in ("need_time", "never"):
            text += f"\nSession depletion: {depl}"

        tip = tk.Toplevel(root)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.geometry(f"+{event.x_root + 10}+{event.y_root - 60}")
        tip.configure(bg="#2a2a4a")

        tf = tk.Frame(tip, bg="#2a2a4a", padx=8, pady=0, highlightbackground="#4a4a6c",
                      highlightthickness=1)
        tf.pack()
        tk.Label(tf, text=text, font=("Segoe UI", 9), fg="#c0c0d8", bg="#2a2a4a",
                 justify="left", pady=6).pack()
        root._tooltip = tip
        root.after(200, _poll_tooltip)

    def hide_tooltip(event=None):
        if root._tooltip:
            try: root._tooltip.destroy()
            except: pass
            root._tooltip = None

    def _poll_tooltip():
        """Poll mouse position while tooltip is visible. Close when mouse leaves widget."""
        if not root._tooltip:
            return
        x, y = root.winfo_pointerxy()
        wx = root.winfo_rootx()
        wy = root.winfo_rooty()
        ww = root.winfo_width()
        wh = root.winfo_height()
        if not (wx <= x <= wx + ww and wy <= y <= wy + wh):
            hide_tooltip()
        else:
            root.after(200, _poll_tooltip)

    # Left-click drag with click-vs-drag detection
    root._drag_data = {"x": 0, "y": 0, "dragging": False}

    def start_drag(event):
        root._drag_data["x"] = event.x
        root._drag_data["y"] = event.y
        root._drag_data["dragging"] = False

    def do_drag(event):
        dx = event.x - root._drag_data["x"]
        dy = event.y - root._drag_data["y"]
        if abs(dx) > 3 or abs(dy) > 3:
            root._drag_data["dragging"] = True
        if root._drag_data["dragging"]:
            new_x = root.winfo_x() + dx
            new_y = root.winfo_y() + dy
            root.geometry(f"+{new_x}+{new_y}")

    def end_drag(event):
        if root._drag_data["dragging"]:
            # Save new position after drag
            save_widget_geometry()
        else:
            # Was a click, not a drag — dismiss tooltip and open visual dialog
            hide_tooltip()
            threading.Thread(target=open_visual, daemon=True).start()

    # Bind events
    for w in [outer, frame, root._time_lbl, root._session_lbl, root._sep1,
              root._weekly_lbl, root._sep2, root._sonnet_lbl]:
        w.bind("<Enter>", show_tooltip)
        w.bind("<ButtonPress-1>", start_drag)
        w.bind("<B1-Motion>", do_drag)
        w.bind("<ButtonRelease-1>", end_drag)
        w.bind("<Button-3>", lambda e: show_context_menu(e, root))

    # ── Win32 topmost enforcement ──
    root._menu_open = False
    root.update()

    # Get the real HWND for SetWindowPos
    user32 = ctypes.windll.user32
    _hwnd = user32.GetParent(root.winfo_id())
    if not _hwnd:
        _hwnd = root.winfo_id()
    debug(f"[DEBUG] Widget HWND: {_hwnd} (winfo_id: {root.winfo_id()})")

    HWND_TOPMOST = -1
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOACTIVATE = 0x0010
    SWP_SHOWWINDOW = 0x0040

    SW_SHOWNOACTIVATE = 8
    root._focus_changed = False  # flag set by Win32 callback, read by polling loop

    # Try SetWindowBand (undocumented) to place window in a higher z-order band
    _set_window_band = None
    try:
        _set_window_band = ctypes.windll.user32.SetWindowBand
        _set_window_band.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.DWORD]
        _set_window_band.restype = wintypes.BOOL
        # ZBID_UIACCESS = 3, ZBID_SYSTEM_TOOLS = 4
        if _set_window_band(_hwnd, 0, 3):
            debug("[INFO] SetWindowBand(ZBID_UIACCESS) succeeded")
        else:
            debug("[WARN] SetWindowBand failed, falling back to HWND_TOPMOST")
            _set_window_band = None
    except Exception as e:
        debug(f"[WARN] SetWindowBand not available: {e}")

    def force_visible():
        """Ensure the window is visible and topmost using Win32 API only."""
        user32.ShowWindow(_hwnd, SW_SHOWNOACTIVATE)
        user32.SetWindowPos(
            _hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        )

    def force_topmost():
        # Don't fight the tooltip for z-order
        if root._tooltip:
            return
        try:
            root.attributes("-topmost", True)
        except: pass
        force_visible()

    # Fast polling loop — runs every 100ms, does full topmost assertion
    def keep_on_top():
        try:
            if not root._menu_open:
                state = root.state()
                if state in ('withdrawn', 'iconic'):
                    root.deiconify()

                if not user32.IsWindowVisible(_hwnd):
                    force_visible()
                    root.deiconify()

                # Re-assert topmost unconditionally via Win32
                user32.SetWindowPos(
                    _hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
                )
                # Also force redraw so the widget visually reappears
                user32.RedrawWindow(_hwnd, None, None, 0x0085)  # RDW_FRAME|RDW_INVALIDATE|RDW_UPDATENOW

                root._focus_changed = False
        except Exception:
            pass
        root.after(100, keep_on_top)

    # Reactive hook — sets a flag and does immediate Win32-only assertion.
    # IMPORTANT: No tkinter calls (root.after, root.attributes, etc.) here —
    # they cause native crashes when called from a ctypes WINFUNCTYPE callback.
    from ctypes import WINFUNCTYPE
    EVENT_SYSTEM_FOREGROUND = 0x0003
    WINEVENT_OUTOFCONTEXT = 0x0000

    @WINFUNCTYPE(
        None,
        wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
        ctypes.c_long, ctypes.c_long, wintypes.DWORD, wintypes.DWORD,
    )
    def _on_foreground(hWinEventHook, event, hwnd_event, idObject, idChild, dwEventThread, dwmsEventTime):
        try:
            if hwnd_event != _hwnd and not root._menu_open:
                force_visible()
                root._focus_changed = True
        except Exception:
            pass  # Never let exceptions escape a ctypes callback

    # Must keep reference to prevent GC
    root._win_event_callback = _on_foreground
    root._win_event_hook = user32.SetWinEventHook(
        EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND,
        0, _on_foreground, 0, 0, WINEVENT_OUTOFCONTEXT,
    )

    force_topmost()
    keep_on_top()
    update_taskbar_text()

    # Live-updating "last fetched" time above the percentages
    def _resize_widget():
        """Recalculate widget size after content change."""
        root.update_idletasks()
        w = root.winfo_reqwidth()
        h = root.winfo_reqheight()
        x = root.winfo_x()
        y = root.winfo_y()
        root.geometry(f"{w}x{h}+{x}+{y}")

    root._time_visible = False

    def update_time_label():
        show = config.get("show_last_refresh", True) and last_refresh is not None

        if not show:
            if root._time_visible:
                root._time_lbl.pack_forget()
                root._time_visible = False
                root.after_idle(_resize_widget)
            root.after(1000, update_time_label)
            return

        if not root._time_visible:
            root._time_lbl.pack(side="top", before=frame)
            root._time_visible = True
            root.after_idle(_resize_widget)

        ago = int((datetime.now(timezone.utc) - last_refresh).total_seconds())
        mode = config.get("refresh_display_mode", "exact")

        if mode == "approximate":
            if ago < 60:
                root._time_lbl.config(text="(Seconds Ago)")
            else:
                mins = ago // 60
                lower = (mins // 5) * 5
                upper = lower + 5
                if lower == 0:
                    lower = 1
                root._time_lbl.config(text=f"({lower}-{upper} mins ago)")
        else:
            if ago < 60:
                root._time_lbl.config(text=f"({ago}s ago)")
            else:
                mins = ago // 60
                root._time_lbl.config(text=f"({mins} min{'s' if mins != 1 else ''} ago)")

        interval = 1000 if ago < 60 else 5000
        root.after(interval, update_time_label)

    update_time_label()
    return root


def show_context_menu(event, root):
    menu = tk.Menu(root, tearoff=0, bg="#2a2a4a", fg="#e0e0f0",
                   activebackground="#3a5a7c", activeforeground="white",
                   font=("Segoe UI", 9))
    menu.add_command(label="Refresh Now", command=lambda: do_refresh_taskbar())
    menu.add_command(label="Open Visual", command=lambda: threading.Thread(target=open_visual, daemon=True).start())
    menu.add_command(label="Settings", command=lambda: open_settings())
    menu.add_separator()
    menu.add_command(label="Report an Issue", command=lambda: webbrowser.open(ISSUES_URL))
    menu.add_command(label="Add-on/Author GitHub", command=lambda: webbrowser.open(GITHUB_URL))
    menu.add_separator()
    menu.add_command(label="Quit", command=lambda: quit_app())

    # Dismiss tooltip and pause topmost toggling while menu is open
    if root._tooltip:
        root._tooltip.destroy()
        root._tooltip = None
    root._menu_open = True
    def on_menu_close():
        root._menu_open = False
        # Re-assert topmost and re-show widget
        root.attributes("-topmost", True)
        root.deiconify()
        root.lift()
    menu.bind("<Unmap>", lambda e: on_menu_close())

    # Position menu above the widget, aligned to widget's left edge
    widget_x = root.winfo_rootx()
    widget_top = root.winfo_rooty()
    menu.update_idletasks()
    try:
        menu_h = menu.yposition("end") + 20
    except:
        menu_h = 180
    menu_y = widget_top - menu_h
    menu.tk_popup(widget_x, menu_y)


def do_refresh_taskbar():
    fetch_usage()
    update_taskbar_text()
    # If the visual dialog is open, close and reopen it to show fresh data
    if visual_window:
        # Save position before closing
        try:
            _vx = visual_window.winfo_x()
            _vy = visual_window.winfo_y()
            visual_window.destroy()
        except:
            _vx, _vy = None, None
        def _reopen():
            open_visual()
            # Restore position
            if visual_window and _vx is not None:
                visual_window.geometry(f"+{_vx}+{_vy}")
        threading.Thread(target=_reopen, daemon=True).start()


def quit_app():
    global taskbar_widget
    save_widget_geometry()
    if taskbar_widget:
        taskbar_widget.destroy()
    os._exit(0)


def update_taskbar_text():
    """Update the percentage labels and their colors, or show error state."""
    if not taskbar_widget:
        return

    if fetch_error:
        err_color = "#e65050"
        detail = last_fetch_error_detail or "Unknown"
        err_text = f"Error: {detail}"
        taskbar_widget._session_lbl.config(text=err_text, fg=err_color)
        # Hide unused labels so they don't take space
        for w in [taskbar_widget._sep1, taskbar_widget._weekly_lbl,
                  taskbar_widget._sep2, taskbar_widget._sonnet_lbl]:
            w.pack_forget()
        # Hide time label too for clean error display
        if getattr(taskbar_widget, '_time_visible', False):
            taskbar_widget._time_lbl.pack_forget()
            taskbar_widget._time_visible = False
        # Auto-fit widget to error text
        taskbar_widget.update_idletasks()
        new_w = taskbar_widget.winfo_reqwidth()
        new_h = taskbar_widget.winfo_reqheight()
        x = taskbar_widget.winfo_x()
        y = taskbar_widget.winfo_y()
        taskbar_widget.geometry(f"{new_w}x{new_h}+{x}+{y}")
        return

    fh = usage_data.get("five_hour", {})
    sd = usage_data.get("seven_day", {})
    ss = usage_data.get("seven_day_sonnet", {})

    sp = fh.get("utilization", 0)
    wp = sd.get("utilization", 0)
    snp = ss.get("utilization", 0) if ss else 0

    show_s = config.get("show_session", True)
    show_w = config.get("show_weekly", True)
    show_n = config.get("show_sonnet", True)

    # Build visible items
    parts = []
    if show_s: parts.append((taskbar_widget._session_lbl, sp))
    if show_w: parts.append((taskbar_widget._weekly_lbl, wp))
    if show_n: parts.append((taskbar_widget._sonnet_lbl, snp))

    # Hide all first
    for lbl in [taskbar_widget._session_lbl, taskbar_widget._weekly_lbl, taskbar_widget._sonnet_lbl,
                taskbar_widget._sep1, taskbar_widget._sep2]:
        lbl.pack_forget()

    # Re-pack only visible ones with separators between them
    pct_frame = taskbar_widget._pct_frame
    for i, (lbl, pct) in enumerate(parts):
        if i > 0:
            sep = taskbar_widget._sep1 if i == 1 else taskbar_widget._sep2
            sep.config(text="/")
            sep.pack(in_=pct_frame, side="left", padx=2)
        padx = (6, 0) if i == 0 else (0, 6) if i == len(parts) - 1 else (0, 0)
        lbl.config(text=f"{pct:.0f}%", fg=pct_color_hex(pct))
        lbl.pack(in_=pct_frame, side="left", padx=padx)

    # Resize widget to fit
    taskbar_widget.update_idletasks()
    w = taskbar_widget.winfo_reqwidth()
    h = taskbar_widget.winfo_reqheight()
    x = taskbar_widget.winfo_x()
    y = taskbar_widget.winfo_y()
    taskbar_widget.geometry(f"{w}x{h}+{x}+{y}")


# ── Tray Icon (kept as backup + double-click) ────────────────────────────

def create_tray_icon():
    session_pct = usage_data.get("five_hour", {}).get("utilization", 0)
    img = Image.new("RGBA", (64, 64), (30, 30, 46, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([4, 8, 60, 56], fill=(50, 50, 70))
    bar_h = int(48 * min(session_pct, 100) / 100)
    if bar_h > 0:
        draw.rectangle([4, 56 - bar_h, 60, 56], fill=pct_color_rgb(session_pct))
    try: font = ImageFont.truetype("arialbd.ttf", 18)
    except: font = ImageFont.load_default()
    txt = f"{int(session_pct)}"
    bbox = draw.textbbox((0, 0), txt, font=font)
    draw.text(((64 - (bbox[2] - bbox[0])) // 2, 56), txt, fill=(255, 255, 255), font=font)
    return img


def get_hover_text():
    fh = usage_data.get("five_hour", {})
    sd = usage_data.get("seven_day", {})
    ss = usage_data.get("seven_day_sonnet", {})
    sp, wp, snp = fh.get("utilization", 0), sd.get("utilization", 0), (ss.get("utilization", 0) if ss else 0)
    sr, wr = format_reset(fh.get("resets_at")), format_reset(sd.get("resets_at"))
    depl = estimate_depletion()
    depl_str = f"\nEst. session depletion: {depl}" if depl and depl not in ("need_time", "stable") else ""
    return (f"{get_plan_label()} — {sp:.0f}% / {wp:.0f}% / {snp:.0f}%\n"
            f"Session resets in {sr} | Weekly resets in {wr}{depl_str}")


# ── Visual Dialog ─────────────────────────────────────────────────────────

def open_visual():
    global visual_window
    if visual_window is not None:
        try: visual_window.lift(); visual_window.focus_force(); return
        except: pass

    fh = usage_data.get("five_hour", {})
    sd = usage_data.get("seven_day", {})
    ss = usage_data.get("seven_day_sonnet", {})
    eu = usage_data.get("extra_usage")
    sp = fh.get("utilization", 0)
    wp = sd.get("utilization", 0)
    snp = ss.get("utilization", 0) if ss else 0
    sr = format_reset(fh.get("resets_at"))
    wr = format_reset(sd.get("resets_at"))

    # ── Palette (uses config colors) ──
    bg       = config.get("bg_color", "#1e1e2e")
    surface  = "#1e1e1e"
    raised   = "#252525"
    border   = "#333333"
    _text_c  = config.get("color_text", "#ffffff")
    fg       = _text_c
    fg_dim   = _text_c
    fg_br    = _text_c
    accent   = "#56d4c8"  # teal accent
    green    = "#3fb950"
    blue     = "#58a6ff"
    cyan     = "#56d4c8"
    red      = "#f85149"
    bar_bg   = "#30363d"
    titlebar = "#111111"

    win = tk.Toplevel() if taskbar_widget else tk.Tk()
    visual_window = win
    win.title("Dashboard")
    win.configure(bg=bg)
    win.geometry("440x1")
    win.update_idletasks()

    # Group visual + settings under one taskbar button via AppUserModelID.
    # Must withdraw, set ID, then deiconify so taskbar picks up the new ID.
    _v_hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
    GWL_EXSTYLE = -20
    WS_EX_APPWINDOW = 0x00040000
    WS_EX_TOOLWINDOW = 0x00000080
    win.withdraw()
    _style = ctypes.windll.user32.GetWindowLongW(_v_hwnd, GWL_EXSTYLE)
    ctypes.windll.user32.SetWindowLongW(_v_hwnd, GWL_EXSTYLE, (_style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW)
    set_window_app_id(_v_hwnd)
    win.deiconify()
    win.attributes("-topmost", True)
    win.after(200, lambda: win.attributes("-topmost", False))
    win.focus_force()

    # Use speedometer icon for title bar AND taskbar
    try:
        ico_path = SCRIPT_DIR / "speedometer.ico"
        win.iconbitmap(str(ico_path))
    except: pass

    def on_close():
        global visual_window
        visual_window = None
        win.destroy()
    win.protocol("WM_DELETE_WINDOW", on_close)

    # ── Decorative header banner with Reddit ticker ──
    _show_ticker = config.get("show_reddit_ticker", True)
    tb = tk.Frame(win, bg=titlebar, height=36)
    if _show_ticker:
        tb.pack(fill="x")
    tb.pack_propagate(False)

    _ticker_label = tk.Label(tb, text='"usage" @ r/ClaudeAI:', font=("Consolas", 9, "bold"),
                             fg=accent, bg=titlebar)
    _ticker_label.pack(side="left", padx=(12, 0))

    # Scrolling ticker area
    _ticker_canvas = tk.Canvas(tb, bg=titlebar, height=20, bd=0, highlightthickness=0)
    _ticker_canvas.pack(side="left", fill="x", expand=True, padx=(4, 8))

    # Fetch Reddit threads and build ticker
    _ticker_texts = []
    _ticker_urls = []
    def _fetch_reddit_threads():
        try:
            r = requests.get("https://www.reddit.com/r/ClaudeAI/search.json",
                             params={"q": "usage", "sort": "new", "limit": "3", "restrict_sr": "on"},
                             headers={"User-Agent": "ClaudeUsageSystray/1.0"}, timeout=8)
            if r.status_code == 200:
                posts = r.json().get("data", {}).get("children", [])
                now = time.time()
                for p in posts:
                    d = p["data"]
                    age_sec = now - d.get("created_utc", now)
                    if age_sec < 3600:
                        age_str = f"{int(age_sec / 60)}m ago"
                    elif age_sec < 86400:
                        age_str = f"{int(age_sec / 3600)}h ago"
                    else:
                        age_str = f"{int(age_sec / 86400)}d ago"
                    _ticker_texts.append(f"{d['title']} ({age_str})")
                    _ticker_urls.append(f"https://reddit.com{d['permalink']}")
        except Exception:
            _ticker_texts.append("Could not load Reddit threads")

    threading.Thread(target=_fetch_reddit_threads, daemon=True).start()

    # Ticker animation
    _ticker_offset = [0]
    _ticker_text_id = [None]

    def _animate_ticker():
        if not _ticker_texts:
            win.after(500, _animate_ticker)
            return

        full_text = "     \u2022     ".join(_ticker_texts)
        _ticker_canvas.delete("all")
        w = _ticker_canvas.winfo_width()
        if w < 10:
            win.after(100, _animate_ticker)
            return

        tid = _ticker_canvas.create_text(
            w - _ticker_offset[0], 10, text=full_text,
            font=("Consolas", 8), fill="#ffffff", anchor="w")
        bbox = _ticker_canvas.bbox(tid)
        text_w = bbox[2] - bbox[0] if bbox else 200

        _ticker_offset[0] += 1
        if _ticker_offset[0] > w + text_w:
            _ticker_offset[0] = 0

        win.after(40, _animate_ticker)

    def _on_ticker_click(event):
        if not _ticker_urls:
            return
        # Open the first URL (or could determine which based on click position)
        webbrowser.open(_ticker_urls[0])

    _ticker_canvas.bind("<Button-1>", _on_ticker_click)
    _ticker_canvas.configure(cursor="hand2")
    win.after(500, _animate_ticker)

    # ── Body ──
    body = tk.Frame(win, bg=bg, padx=20, pady=16)
    body.pack(fill="both", expand=True)

    win.geometry("440x1")  # Set width, minimal height — will expand to fit content

    # ── Header ──
    if last_refresh:
        ago = int((datetime.now(timezone.utc) - last_refresh).total_seconds())
        ago_str = f"Updated {ago}s ago" if ago < 60 else f"Updated {ago // 60}m ago"
    else:
        ago_str = "Not yet refreshed"

    hdr = tk.Frame(body, bg=bg)
    hdr.pack(fill="x", pady=(0, 10))
    tk.Label(hdr, text=get_email(), font=("Consolas", 10),
             fg=fg_dim, bg=bg, anchor="w").pack(fill="x")
    plan_row = tk.Frame(hdr, bg=bg)
    plan_row.pack(fill="x", pady=(2, 0))
    tk.Label(plan_row, text=get_plan_label(), font=("Consolas", 10, "bold"),
             fg=fg_br, bg=bg).pack(side="left")
    _ago_lbl = tk.Label(plan_row, text=f"  \u00b7  {ago_str}", font=("Consolas", 9),
                        fg=fg_dim, bg=bg)
    _ago_lbl.pack(side="left")

    def _update_ago():
        if last_refresh:
            ago = int((datetime.now(timezone.utc) - last_refresh).total_seconds())
            if ago < 60:
                txt = f"  \u00b7  Updated {ago}s ago"
            elif ago < 7200:
                txt = f"  \u00b7  Updated {ago // 60}m ago"
            else:
                txt = f"  \u00b7  Updated {ago // 3600}h {(ago % 3600) // 60}m ago"
        else:
            txt = "  \u00b7  Not yet refreshed"
        _ago_lbl.config(text=txt)
        win.after(1000, _update_ago)

    win.after(1000, _update_ago)

    tk.Frame(body, bg=border, height=1).pack(fill="x", pady=(0, 14))

    # ── Usage bars ──
    def bar_color(pct):
        if pct < 50: return green
        elif pct < 75: return cyan
        elif pct < 90: return "#e3b341"
        return red

    # Create chart icon — small white line chart drawn on canvas
    _chart_icon_img = None
    try:
        _ci = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        _cd = ImageDraw.Draw(_ci)
        # Draw a small line chart shape in white
        _cd.line([(1, 13), (5, 8), (8, 10), (11, 4), (15, 6)], fill="#ffffff", width=2)
        _cd.line([(1, 14), (15, 14)], fill="#888888", width=1)  # x-axis
        _chart_icon_img = ImageTk.PhotoImage(_ci)
        # Prevent garbage collection — store reference on the window
        win._chart_icon_ref = _chart_icon_img
    except Exception as e:
        debug(f"[WARN] Chart icon creation failed: {e}")

    def _draw_chart(canvas, metric_idx, gw, gh, pad=35, tpad=22):
        """Draw a usage chart on the given canvas."""
        canvas.delete("all")
        titles = {1: "Session (5-hour)", 2: "Weekly (All Models)", 3: "Weekly (Sonnet)"}
        canvas.create_text(pad + gw // 2, 10, text=titles.get(metric_idx, ""),
                           fill="#ffffff", font=("Consolas", 9, "bold"))

        data = [(h[0], h[metric_idx]) for h in usage_history]
        if len(data) < 2:
            canvas.create_text(pad + gw // 2, tpad + gh // 2, text="Insufficient data",
                               fill="#ffffff", font=("Consolas", 9))
            return

        # X-axis range: use real period start if available
        t1 = data[-1][0]
        fh = usage_data.get("five_hour", {})
        sd = usage_data.get("seven_day", {})
        if metric_idx == 1:
            # Session: 5 hours before reset time
            reset_iso = fh.get("resets_at")
            if reset_iso:
                try:
                    reset_dt = datetime.fromisoformat(reset_iso.replace("Z", "+00:00"))
                    t0 = (reset_dt - __import__("datetime").timedelta(hours=5)).timestamp()
                except Exception:
                    t0 = data[0][0]
            else:
                t0 = data[0][0]
        else:
            # Weekly: 7 days before reset time
            reset_iso = sd.get("resets_at")
            if reset_iso:
                try:
                    reset_dt = datetime.fromisoformat(reset_iso.replace("Z", "+00:00"))
                    t0 = (reset_dt - __import__("datetime").timedelta(days=7)).timestamp()
                except Exception:
                    t0 = data[0][0]
            else:
                t0 = data[0][0]

        if t1 - t0 < 1:
            t0 = data[0][0]

        max_v = 100

        # Grid lines and y-axis labels (skip 0%)
        for i in range(4):
            y = tpad + int(gh * i / 4)
            val = 100 - 25 * i
            canvas.create_line(pad, y, pad + gw, y, fill="#2a2a4a")
            canvas.create_text(pad - 4, y, text=f"{val}%", fill="#ffffff",
                               font=("Consolas", 7), anchor="e")
        # Bottom grid line (0%) — line only, no label
        canvas.create_line(pad, tpad + gh, pad + gw, tpad + gh, fill="#2a2a4a")

        # X-axis time labels
        from datetime import datetime as dt
        for i in range(3):
            x = pad + int(gw * i / 2)
            t = t0 + (t1 - t0) * i / 2
            ts = dt.fromtimestamp(t).strftime("%m/%d %H:%M") if (t1 - t0) > 86400 else dt.fromtimestamp(t).strftime("%H:%M")
            canvas.create_text(x, tpad + gh + 12, text=ts, fill="#ffffff",
                               font=("Consolas", 7))

        # Draw line
        points = []
        for ts, val in data:
            if ts < t0:
                continue
            x = pad + int((ts - t0) / max(1, t1 - t0) * gw)
            y = tpad + int((1 - val / max_v) * gh)
            points.append((x, y))

        if len(points) >= 2:
            line_color = bar_color(data[-1][1])
            for i in range(len(points) - 1):
                canvas.create_line(points[i][0], points[i][1],
                                   points[i + 1][0], points[i + 1][1],
                                   fill=line_color, width=2)

    def _show_graph_tooltip(event, metric_idx, anchor_widget):
        """Show a line graph tooltip for the given metric."""
        if len(usage_history) < 2:
            return
        tt = tk.Toplevel(win)
        tt.overrideredirect(True)
        tt.attributes("-topmost", True)
        tt.configure(bg="#1a1a2e")
        gw, gh = 280, 140
        canvas = tk.Canvas(tt, width=gw + 65, height=gh + 42,
                           bg="#1a1a2e", bd=0, highlightthickness=0)
        canvas.pack(padx=6, pady=6)
        _draw_chart(canvas, metric_idx, gw, gh)

        tt.update_idletasks()
        tw = tt.winfo_reqwidth()
        th = tt.winfo_reqheight()
        sx = win.winfo_screenwidth()
        sy = win.winfo_screenheight()
        tx = max(5, min(event.x_root - tw // 2, sx - tw - 5))
        ty = event.y_root + 20
        if ty + th > sy - 5:
            ty = event.y_root - th - 20
        tt.geometry(f"+{tx}+{ty}")
        anchor_widget._graph_tooltip = tt

    def _hide_graph_tooltip(event, anchor_widget):
        tt = getattr(anchor_widget, '_graph_tooltip', None)
        if tt:
            tt.destroy()
            anchor_widget._graph_tooltip = None

    def _open_chart_window(metric_idx):
        """Open a full chart window for the given metric."""
        if len(usage_history) < 2:
            return
        titles = {1: "Session (5-hour)", 2: "Weekly (All Models)", 3: "Weekly (Sonnet)"}
        cw = tk.Toplevel(win)
        cw.title(f"Usage Chart — {titles.get(metric_idx, '')}")
        cw.configure(bg="#1a1a2e")
        cw.geometry("600x400")
        try:
            ico_path = SCRIPT_DIR / "speedometer.ico"
            cw.iconbitmap(str(ico_path))
        except: pass

        gw, gh = 520, 300
        canvas = tk.Canvas(cw, width=gw + 75, height=gh + 50,
                           bg="#1a1a2e", bd=0, highlightthickness=0)
        canvas.pack(padx=20, pady=20, fill="both", expand=True)
        _draw_chart(canvas, metric_idx, gw, gh, pad=40, tpad=25)

        def on_resize(event):
            new_gw = max(200, event.width - 95)
            new_gh = max(100, event.height - 70)
            _draw_chart(canvas, metric_idx, new_gw, new_gh, pad=40, tpad=25)
        canvas.bind("<Configure>", on_resize)

    def add_bar(parent, label, pct, reset_str, metric_idx=1):
        f = tk.Frame(parent, bg=bg)
        f.pack(fill="x", pady=(0, 10))
        top = tk.Frame(f, bg=bg)
        top.pack(fill="x")
        tk.Label(top, text=label, font=("Consolas", 9), fg=fg, bg=bg).pack(side="left")
        tk.Label(top, text=f"{pct:.0f}%", font=("Consolas", 10, "bold"),
                 fg=bar_color(pct), bg=bg).pack(side="right")
        bar = tk.Canvas(f, height=6, bg=bar_bg, bd=0, highlightthickness=0)
        bar.pack(fill="x", pady=(4, 0))
        color = bar_color(pct)
        def redraw_bar(event=None, c=color, p=pct):
            bar.delete("all")
            w = bar.winfo_width()
            if w > 1:
                fw = max(1, int(w * min(p, 100) / 100))
                bar.create_rectangle(0, 0, fw, 6, fill=c, outline="")
        bar.bind("<Configure>", redraw_bar)

        # Reset/ETA row with chart icon right-aligned
        eta_row = tk.Frame(f, bg=bg)
        eta_row.pack(fill="x", pady=(2, 0))
        tk.Label(eta_row, text=f"Resets in {reset_str}", font=("Consolas", 8),
                 fg=fg_dim, bg=bg, anchor="w").pack(side="left")

        if _chart_icon_img and len(usage_history) >= 2:
            chart_btn = tk.Label(eta_row, image=_chart_icon_img, bg=bg, cursor="hand2")
            chart_btn.pack(side="right")
            mi = metric_idx
            chart_btn.bind("<Enter>", lambda e, m=mi, w=chart_btn: _show_graph_tooltip(e, m, w))
            chart_btn.bind("<Leave>", lambda e, w=chart_btn: _hide_graph_tooltip(e, w))
            chart_btn.bind("<Button-1>", lambda e, m=mi: _open_chart_window(m))

        if config.get("show_depletion_estimates", True):
            depl = estimate_depletion(metric_idx)
            eta_row2 = tk.Frame(f, bg=bg)
            eta_row2.pack(fill="x")
            if depl in (None, "need_time", "never"):
                tk.Label(eta_row2, text="100% ETA: Insufficient data",
                         font=("Consolas", 8), fg=fg_dim, bg=bg, anchor="w").pack(side="left")
            else:
                tk.Label(eta_row2, text=f"100% ETA: {depl}", font=("Consolas", 8),
                         fg=red, bg=bg, anchor="w").pack(side="left")

            if _chart_icon_img and len(usage_history) >= 2 and not getattr(eta_row, '_has_chart', False):
                pass  # chart icon already on the reset row above

    if config.get("show_session", True):
        add_bar(body, "Session (5-hour)", sp, sr, metric_idx=1)
    if config.get("show_weekly", True):
        add_bar(body, "Weekly (All Models)", wp, wr, metric_idx=2)
    if config.get("show_sonnet", True):
        add_bar(body, "Weekly (Sonnet)", snp, wr, metric_idx=3)

    tk.Frame(body, bg=border, height=1).pack(fill="x", pady=(6, 12))

    # ── Extra Usage ──
    if eu and eu.get("is_enabled"):
        used = eu.get("used_credits", 0) / 100
        limit = eu.get("monthly_limit", 0) / 100
        remaining = max(0, limit - used)
        eu_pct = min(100, int((used / limit * 100) if limit > 0 else 0))
        limit_str = f"${limit:,.2f}"

        tk.Label(body, text=f"Extra Usage (Monthly Limit of {limit_str})",
                 font=("Consolas", 9), fg=fg, bg=bg, anchor="w",
                 wraplength=400, justify="left").pack(fill="x")

        # Format amounts — shorten to no decimals if >= $1000
        def fmt_money(val):
            if val >= 1000: return f"${val:,.0f}"
            return f"${val:,.2f}"

        row = tk.Frame(body, bg=bg)
        row.pack(fill="x", pady=(4, 0))
        row.columnconfigure(0, weight=1, uniform="eu")
        row.columnconfigure(1, weight=1, uniform="eu")
        row.columnconfigure(2, weight=1, uniform="eu")
        tk.Label(row, text=f"{fmt_money(used)} used", font=("Consolas", 9),
                 fg=fg_dim, bg=bg, anchor="w").grid(row=0, column=0, sticky="w")
        eu_color = bar_color(eu_pct)
        tk.Label(row, text=f"{eu_pct}%", font=("Consolas", 10, "bold"),
                 fg=eu_color, bg=bg).grid(row=0, column=1)
        remaining_color = red if remaining <= 0 else fg_dim
        tk.Label(row, text=f"{fmt_money(remaining)} left", font=("Consolas", 9),
                 fg=remaining_color, bg=bg, anchor="e").grid(row=0, column=2, sticky="e")

        eb = tk.Canvas(body, height=4, bg=bar_bg, bd=0, highlightthickness=0)
        eb.pack(fill="x", pady=(4, 0))
        def redraw_eb(event=None, c=eu_color, p=eu_pct):
            eb.delete("all")
            w = eb.winfo_width()
            if w > 1:
                eb.create_rectangle(0, 0, max(1, int(w * min(p, 100) / 100)), 4,
                                    fill=c, outline="")
        eb.bind("<Configure>", redraw_eb)
    elif eu is not None and not eu.get("is_enabled"):
        # Extra Usage exists in API response but is explicitly disabled
        ef = tk.Frame(body, bg=bg)
        ef.pack(fill="x")
        tk.Label(ef, text="Extra Usage is disabled.", font=("Consolas", 9),
                 fg=fg_dim, bg=bg, anchor="w").pack(anchor="w")
        link = tk.Label(ef, text="Enable in Account Settings",
                        font=("Consolas", 9, "underline"), fg=blue, bg=bg, cursor="hand2")
        link.pack(anchor="w", pady=(2, 0))
        link.bind("<Button-1>", lambda e: webbrowser.open(ACCOUNT_SETTINGS_URL))
        tk.Label(ef, text="Note: API costs can exceed equivalent subscription rates.",
                 font=("Consolas", 8), fg="#b35c55", bg=bg, wraplength=390, justify="left",
                 anchor="w").pack(fill="x", pady=(6, 0))
    else:
        # No extra_usage data (fetch failed or not yet loaded)
        tk.Label(body, text="Extra Usage: data unavailable", font=("Consolas", 9),
                 fg=fg_dim, bg=bg, anchor="w").pack(fill="x")

    # ── Refresh button ──
    def do_refresh():
        fetch_usage()
        update_taskbar_text()
        _rx = win.winfo_x()
        _ry = win.winfo_y()
        on_close()
        def _reopen():
            open_visual()
            if visual_window:
                visual_window.geometry(f"+{_rx}+{_ry}")
        threading.Thread(target=_reopen, daemon=True).start()

    # Rounded button via Canvas — redraws on resize so text stays centered
    btn_h = 38
    radius = 8
    btn_canvas = tk.Canvas(body, height=btn_h, bg=bg, bd=0, highlightthickness=0)
    btn_canvas.pack(fill="x", pady=(12, 0))
    btn_canvas._hover = False

    def draw_rounded_btn(event=None):
        btn_canvas.delete("all")
        w = btn_canvas.winfo_width()
        h = btn_h
        r = radius
        fill_c = "#2e2e2e" if btn_canvas._hover else raised
        text_c = accent if btn_canvas._hover else fg
        # Rounded rectangle via arcs + rectangles
        btn_canvas.create_arc(0, 0, 2*r, 2*r, start=90, extent=90, fill=fill_c, outline=border, width=1)
        btn_canvas.create_arc(w - 2*r, 0, w, 2*r, start=0, extent=90, fill=fill_c, outline=border, width=1)
        btn_canvas.create_arc(0, h - 2*r, 2*r, h, start=180, extent=90, fill=fill_c, outline=border, width=1)
        btn_canvas.create_arc(w - 2*r, h - 2*r, w, h, start=270, extent=90, fill=fill_c, outline=border, width=1)
        btn_canvas.create_rectangle(r, 0, w - r, h, fill=fill_c, outline="")
        btn_canvas.create_rectangle(0, r, r, h - r, fill=fill_c, outline="")
        btn_canvas.create_rectangle(w - r, r, w, h - r, fill=fill_c, outline="")
        # Border lines between arcs
        btn_canvas.create_line(r, 0, w - r, 0, fill=border)
        btn_canvas.create_line(r, h, w - r, h, fill=border)
        btn_canvas.create_line(0, r, 0, h - r, fill=border)
        btn_canvas.create_line(w, r, w, h - r, fill=border)
        btn_canvas.create_text(w / 2, h / 2, text="Refresh Now",
                               font=("Consolas", 10), fill=text_c)

    btn_canvas.bind("<Configure>", draw_rounded_btn)
    btn_canvas.bind("<Enter>", lambda e: (setattr(btn_canvas, '_hover', True), draw_rounded_btn()))
    btn_canvas.bind("<Leave>", lambda e: (setattr(btn_canvas, '_hover', False), draw_rounded_btn()))
    btn_canvas.bind("<Button-1>", lambda e: do_refresh())
    btn_canvas.config(cursor="hand2")

    # Auto-size height to content, lock width at 440
    win.update_idletasks()
    content_h = win.winfo_reqheight()
    win.geometry(f"440x{content_h}")
    win.minsize(440, content_h)
    win.maxsize(440, content_h)
    win.resizable(False, False)

    # Force the dialog to be the active window
    win.lift()
    win.focus_force()
    win.after(100, win.focus_force)


# ── Settings Dialog ───────────────────────────────────────────────────────

settings_window = None

def open_settings():
    global settings_window
    if settings_window is not None:
        try: settings_window.lift(); settings_window.focus_force(); return
        except: pass

    from tkinter.colorchooser import askcolor

    bg = config.get("bg_color", "#1e1e2e")
    surface = "#252525"
    border = "#333333"
    _text_c = config.get("color_text", "#ffffff")
    fg = _text_c
    fg_dim = _text_c
    accent = "#56d4c8"

    win = tk.Toplevel() if taskbar_widget else tk.Tk()
    settings_window = win
    win.title("Settings")
    win.configure(bg=bg)
    win.geometry("540x580")
    win.resizable(False, False)

    try:
        ico_path = SCRIPT_DIR / "speedometer.ico"
        win.iconbitmap(str(ico_path))
    except: pass

    # Group settings + visual under one taskbar button via AppUserModelID.
    # Must withdraw, set ID + WS_EX_APPWINDOW, then deiconify.
    win.update_idletasks()
    _s_hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
    GWL_EXSTYLE = -20
    WS_EX_APPWINDOW = 0x00040000
    WS_EX_TOOLWINDOW = 0x00000080
    win.withdraw()
    _style = ctypes.windll.user32.GetWindowLongW(_s_hwnd, GWL_EXSTYLE)
    ctypes.windll.user32.SetWindowLongW(_s_hwnd, GWL_EXSTYLE, (_style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW)
    set_window_app_id(_s_hwnd)
    win.deiconify()
    # Force to front: briefly set topmost then remove — guarantees it appears above Visual
    win.attributes("-topmost", True)
    win.after(200, lambda: win.attributes("-topmost", False))
    win.focus_force()

    def on_close():
        global settings_window
        settings_window = None
        win.destroy()
    win.protocol("WM_DELETE_WINDOW", on_close)

    # ── Tab bar at top ──
    tab_bar = tk.Frame(win, bg="#111111")
    tab_bar.pack(fill="x")

    tab_frames = {}
    active_tab = ["general"]
    tab_buttons = {}

    def switch_tab(name):
        active_tab[0] = name
        for n, f in tab_frames.items():
            f.pack_forget()
        tab_frames[name].pack(fill="both", expand=True, after=tab_bar)
        for n, b in tab_buttons.items():
            if n == name:
                b.config(bg="#2a2a2a", fg=accent)
            else:
                b.config(bg="#111111", fg=fg_dim)

    for tab_name, tab_label in [("general", " General "), ("display", " Customize "), ("colors", " Colors ")]:
        b = tk.Label(tab_bar, text=tab_label, font=("Consolas", 10, "bold"),
                     bg="#111111", fg=fg_dim, padx=16, pady=8, cursor="hand2")
        b.pack(side="left")
        b.bind("<Button-1>", lambda e, n=tab_name: switch_tab(n))
        tab_buttons[tab_name] = b

    # ── Create tab frames ──
    for name in ["general", "display", "colors"]:
        f = tk.Frame(win, bg=bg, padx=20, pady=16)
        tab_frames[name] = f

    gen = tab_frames["general"]
    disp = tab_frames["display"]
    col = tab_frames["colors"]

    # ════════════════════════════════════════════════════════════════════
    # TAB 1: General — startup, scale, poll interval
    # ════════════════════════════════════════════════════════════════════

    startup_var = tk.BooleanVar(value=config.get("start_on_startup", False))
    tk.Checkbutton(gen, text="  Launch widget on Windows startup",
                   variable=startup_var, font=("Consolas", 9),
                   fg=fg, bg=bg, selectcolor=surface,
                   activebackground=bg, activeforeground=fg,
                   highlightthickness=0).pack(anchor="w", pady=(0, 6))

    bg_collect_var = tk.BooleanVar(value=config.get("background_collection", False))
    tk.Checkbutton(gen, text="  Collect usage data in the background",
                   variable=bg_collect_var, font=("Consolas", 9),
                   fg=fg, bg=bg, selectcolor=surface,
                   activebackground=bg, activeforeground=fg,
                   highlightthickness=0).pack(anchor="w")
    tk.Label(gen, text="Polls usage every 10 min for graphs. Does NOT cost tokens.",
             font=("Consolas", 7), fg=fg_dim, bg=bg, anchor="w").pack(anchor="w", padx=(24, 0), pady=(0, 12))

    tk.Frame(gen, bg=border, height=1).pack(fill="x", pady=(0, 12))

    # Scale
    tk.Label(gen, text="Display Scale", font=("Consolas", 10, "bold"),
             fg=fg, bg=bg).pack(anchor="w", pady=(0, 6))

    scale_frame = tk.Frame(gen, bg=bg)
    scale_frame.pack(fill="x", pady=(0, 4))

    last_valid_scale = [config.get("scale_pct", 100)]
    scale_var = tk.StringVar(value=str(last_valid_scale[0]))

    scale_entry = tk.Entry(scale_frame, textvariable=scale_var, font=("Consolas", 10),
                           bg=surface, fg=fg, insertbackground=fg, relief="solid", bd=1,
                           width=5, justify="center")
    scale_entry.pack(side="left")
    tk.Label(scale_frame, text=" %", font=("Consolas", 10), fg=fg_dim, bg=bg).pack(side="left")

    arrow_frame = tk.Frame(scale_frame, bg=bg)
    arrow_frame.pack(side="left", padx=(6, 0))

    def increment_scale(delta):
        try: val = int(scale_var.get().strip())
        except (ValueError, TypeError): val = last_valid_scale[0]
        val = max(1, min(400, val + delta))
        scale_var.set(str(val))
        last_valid_scale[0] = val

    btn_up = tk.Label(arrow_frame, text=" \u25b2 ", font=("Consolas", 8),
                      fg=fg, bg=surface, cursor="hand2", relief="solid", bd=1)
    btn_up.pack(side="top", pady=(0, 1))
    btn_up.bind("<Button-1>", lambda e: increment_scale(5))
    btn_dn = tk.Label(arrow_frame, text=" \u25bc ", font=("Consolas", 8),
                      fg=fg, bg=surface, cursor="hand2", relief="solid", bd=1)
    btn_dn.pack(side="top")
    btn_dn.bind("<Button-1>", lambda e: increment_scale(-5))

    scale_err_lbl = tk.Label(scale_frame, text="", font=("Consolas", 9, "bold"),
                              fg="#ff3333", bg=bg)
    scale_err_lbl.pack(side="left", padx=(10, 0))

    def on_scale_change(event=None):
        raw = scale_var.get().strip()
        try:
            val = int(raw)
            if 1 <= val <= 400:
                last_valid_scale[0] = val
                scale_err_lbl.config(text="")
                return
        except (ValueError, TypeError): pass
        scale_var.set(str(last_valid_scale[0]))
        scale_err_lbl.config(text="Invalid Input")
        def clear_err():
            try: scale_err_lbl.config(text="")
            except: pass
        win.after(3000, clear_err)

    scale_entry.bind("<Return>", on_scale_change)
    scale_entry.bind("<FocusOut>", on_scale_change)

    tk.Label(gen, text="Enter any value between 1-400",
             font=("Consolas", 8), fg=fg_dim, bg=bg, anchor="w").pack(fill="x", pady=(2, 6))

    tk.Frame(gen, bg=border, height=1).pack(fill="x", pady=(0, 12))

    # Poll Interval
    _poll_header = tk.Frame(gen, bg=bg)
    _poll_header.pack(fill="x", pady=(0, 6))
    tk.Label(_poll_header, text="Automatic Refresh Interval", font=("Consolas", 10, "bold"),
             fg=fg, bg=bg).pack(side="left")

    poll_frame = tk.Frame(gen, bg=bg)
    poll_frame.pack(fill="x", pady=(0, 4))

    current_interval = config.get("poll_interval_sec", 300)
    poll_mode = [0]
    if current_interval >= 60 and current_interval % 60 == 0:
        poll_mode[0] = 1
        last_valid_poll = [current_interval // 60]
    else:
        last_valid_poll = [current_interval]
    poll_var = tk.StringVar(value=str(last_valid_poll[0]))

    poll_entry = tk.Entry(poll_frame, textvariable=poll_var, font=("Consolas", 10),
                          bg=surface, fg=fg, insertbackground=fg, relief="solid", bd=1,
                          width=5, justify="center")
    poll_entry.pack(side="left")

    btn_sec = tk.Label(poll_frame, text=" Seconds ", font=("Consolas", 9),
                       fg=fg, bg="#3a3a3a", cursor="hand2", relief="solid", bd=1)
    btn_min = tk.Label(poll_frame, text=" Minutes ", font=("Consolas", 9),
                       fg=fg_dim, bg=surface, cursor="hand2", relief="solid", bd=1)
    btn_sec.pack(side="left", padx=(8, 0))
    btn_min.pack(side="left", padx=(2, 0))

    poll_hint_lbl = tk.Label(gen, text="", font=("Consolas", 8), fg=fg_dim, bg=bg, anchor="w")
    poll_hint_lbl.pack(fill="x", pady=(2, 0))
    poll_err_lbl = tk.Label(gen, text="", font=("Consolas", 9, "bold"), fg="#ff3333", bg=bg, anchor="w")
    poll_err_lbl.pack(fill="x", pady=(0, 2))

    # Rate limit warning with hover tooltip — inline with header
    rate_link = tk.Label(_poll_header, text="Note: Request Limits", font=("Consolas", 8, "underline"),
                         fg=accent, bg=bg, cursor="hand2")
    rate_link.pack(side="left", padx=(8, 0))
    rate_tooltip = None

    def show_rate_tooltip(event):
        nonlocal rate_tooltip
        if rate_tooltip: return
        rate_tooltip = tk.Toplevel(win)
        rate_tooltip.overrideredirect(True)
        rate_tooltip.attributes("-topmost", True)
        rate_tooltip.configure(bg="#2a2a4a")
        tf = tk.Frame(rate_tooltip, bg="#2a2a4a", padx=10, pady=8,
                      highlightbackground="#4a4a6c", highlightthickness=1)
        tf.pack()
        explanation = (
            "Anthropic rate-limits the usage API.\n"
            "Querying too frequently returns HTTP 429\n"
            "(Too Many Requests) and the widget shows\n"
            "an error until the limit resets.\n\n"
            "Recommended intervals:\n"
            "  5+ minutes  — safe, no risk of 429\n"
            "  1-5 minutes — usually fine\n"
            "  < 1 minute  — likely to trigger 429\n\n"
            "The retry loop (10 attempts x 2s) can\n"
            "worsen a 429 by hitting the API 10 more\n"
            "times. If you see 429 errors, increase\n"
            "the interval to 5+ minutes."
        )
        tk.Label(tf, text=explanation, font=("Consolas", 8), fg="#c0c0d8",
                 bg="#2a2a4a", justify="left", wraplength=300).pack()
        rate_tooltip.update_idletasks()
        tw = rate_tooltip.winfo_reqwidth(); th = rate_tooltip.winfo_reqheight()
        sx = win.winfo_screenwidth(); sy = win.winfo_screenheight()
        # Position well below the link to avoid cursor overlap flicker
        tx = max(5, min(event.x_root - tw // 2, sx - tw - 5))
        ty = event.y_root + 20
        if ty + th > sy - 5:
            ty = event.y_root - th - 20
        rate_tooltip.geometry(f"+{tx}+{ty}")

    def hide_rate_tooltip(event):
        nonlocal rate_tooltip
        if rate_tooltip:
            # Only hide if cursor actually left the link (not entering the tooltip)
            x, y = event.x_root, event.y_root
            lx = rate_link.winfo_rootx()
            ly = rate_link.winfo_rooty()
            lw = rate_link.winfo_width()
            lh = rate_link.winfo_height()
            if lx <= x <= lx + lw and ly <= y <= ly + lh:
                return  # still on the link
            rate_tooltip.destroy()
            rate_tooltip = None

    rate_link.bind("<Enter>", show_rate_tooltip)
    rate_link.bind("<Leave>", hide_rate_tooltip)

    def update_poll_hint():
        if poll_mode[0] == 0: poll_hint_lbl.config(text="Enter any value 1-1800 (30 minutes)")
        else: poll_hint_lbl.config(text="Enter any value 1-30")

    def set_poll_mode(mode):
        old_mode = poll_mode[0]
        poll_mode[0] = mode
        if mode == 0:
            btn_sec.config(fg=fg, bg="#3a3a3a"); btn_min.config(fg=fg_dim, bg=surface)
            if old_mode == 1:
                try: val = int(poll_var.get().strip()); poll_var.set(str(val * 60)); last_valid_poll[0] = val * 60
                except: pass
        else:
            btn_min.config(fg=fg, bg="#3a3a3a"); btn_sec.config(fg=fg_dim, bg=surface)
            if old_mode == 0:
                try: val = int(poll_var.get().strip()); poll_var.set(str(max(1, val // 60))); last_valid_poll[0] = max(1, val // 60)
                except: pass
        update_poll_hint()

    btn_sec.bind("<Button-1>", lambda e: set_poll_mode(0))
    btn_min.bind("<Button-1>", lambda e: set_poll_mode(1))

    poll_arrow_frame = tk.Frame(poll_frame, bg=bg)
    poll_arrow_frame.pack(side="left", padx=(6, 0))

    def increment_poll(delta):
        try: val = int(poll_var.get().strip())
        except (ValueError, TypeError): val = last_valid_poll[0]
        if poll_mode[0] == 0: val = max(1, min(1800, val + delta))
        else: val = max(1, min(30, val + delta))
        poll_var.set(str(val)); last_valid_poll[0] = val

    poll_btn_up = tk.Label(poll_arrow_frame, text=" \u25b2 ", font=("Consolas", 8),
                           fg=fg, bg=surface, cursor="hand2", relief="solid", bd=1)
    poll_btn_up.pack(side="top", pady=(0, 1))
    poll_btn_up.bind("<Button-1>", lambda e: increment_poll(10 if poll_mode[0] == 0 else 1))
    poll_btn_dn = tk.Label(poll_arrow_frame, text=" \u25bc ", font=("Consolas", 8),
                           fg=fg, bg=surface, cursor="hand2", relief="solid", bd=1)
    poll_btn_dn.pack(side="top")
    poll_btn_dn.bind("<Button-1>", lambda e: increment_poll(-10 if poll_mode[0] == 0 else -1))

    poll_err_inline = tk.Label(poll_frame, text="", font=("Consolas", 9, "bold"),
                               fg="#ff3333", bg=bg)
    poll_err_inline.pack(side="left", padx=(10, 0))

    def on_poll_change(event=None):
        raw = poll_var.get().strip()
        try:
            val = int(raw)
            max_val = 1800 if poll_mode[0] == 0 else 30
            if 1 <= val <= max_val:
                last_valid_poll[0] = val; poll_err_inline.config(text=""); return
        except (ValueError, TypeError): pass
        poll_var.set(str(last_valid_poll[0]))
        poll_err_inline.config(text="Invalid Input")
        def clear_err():
            try: poll_err_inline.config(text="")
            except: pass
        win.after(3000, clear_err)

    poll_entry.bind("<Return>", on_poll_change)
    poll_entry.bind("<FocusOut>", on_poll_change)
    if poll_mode[0] == 1: set_poll_mode(1)
    update_poll_hint()

    # ════════════════════════════════════════════════════════════════════
    # TAB 2: Display — refresh display, depletion, metrics
    # ════════════════════════════════════════════════════════════════════

    # Last Refresh Display
    tk.Label(disp, text="Last Refresh Display", font=("Consolas", 10, "bold"),
             fg=fg, bg=bg).pack(anchor="w", pady=(0, 6))

    show_refresh_var = tk.BooleanVar(value=config.get("show_last_refresh", True))
    tk.Checkbutton(disp, text="  Display Time Since Last Refresh",
                   variable=show_refresh_var, font=("Consolas", 9),
                   fg=fg, bg=bg, selectcolor=surface,
                   activebackground=bg, activeforeground=fg,
                   highlightthickness=0).pack(anchor="w", pady=(0, 6))

    refresh_mode_frame = tk.Frame(disp, bg=bg)
    refresh_mode_frame.pack(fill="x", pady=(0, 8))

    current_mode = config.get("refresh_display_mode", "exact")
    refresh_mode_var = [current_mode]

    btn_approx = tk.Label(refresh_mode_frame, text=" Approximate ", font=("Consolas", 9),
                          fg=fg_dim if current_mode != "approximate" else fg,
                          bg=surface if current_mode != "approximate" else "#3a3a3a",
                          cursor="hand2", relief="solid", bd=1)
    btn_exact = tk.Label(refresh_mode_frame, text=" Seconds/Minutes ", font=("Consolas", 9),
                         fg=fg if current_mode == "exact" else fg_dim,
                         bg="#3a3a3a" if current_mode == "exact" else surface,
                         cursor="hand2", relief="solid", bd=1)
    btn_approx.pack(side="left")
    btn_exact.pack(side="left", padx=(2, 0))

    def set_refresh_mode(mode):
        refresh_mode_var[0] = mode
        if mode == "approximate":
            btn_approx.config(fg=fg, bg="#3a3a3a"); btn_exact.config(fg=fg_dim, bg=surface)
        else:
            btn_exact.config(fg=fg, bg="#3a3a3a"); btn_approx.config(fg=fg_dim, bg=surface)

    btn_approx.bind("<Button-1>", lambda e: set_refresh_mode("approximate"))
    btn_exact.bind("<Button-1>", lambda e: set_refresh_mode("exact"))

    tk.Frame(disp, bg=border, height=1).pack(fill="x", pady=(0, 12))

    # Depletion Estimates
    tk.Label(disp, text="Depletion Estimates", font=("Consolas", 10, "bold"),
             fg=fg, bg=bg).pack(anchor="w", pady=(0, 6))

    depl_var = tk.BooleanVar(value=config.get("show_depletion_estimates", True))
    tk.Checkbutton(disp, text="  Show depletion estimates under each bar",
                   variable=depl_var, font=("Consolas", 9),
                   fg=fg, bg=bg, selectcolor=surface,
                   activebackground=bg, activeforeground=fg,
                   highlightthickness=0).pack(anchor="w", pady=(0, 6))

    calc_link = tk.Label(disp, text="Calculation Method", font=("Consolas", 9, "underline"),
                         fg=accent, bg=bg, cursor="hand2")
    calc_link.pack(anchor="w", pady=(2, 0))
    calc_tooltip = None

    def show_calc_tooltip(event):
        nonlocal calc_tooltip
        if calc_tooltip: return
        calc_tooltip = tk.Toplevel(win)
        calc_tooltip.overrideredirect(True)
        calc_tooltip.attributes("-topmost", True)
        calc_tooltip.configure(bg="#2a2a4a")
        tf = tk.Frame(calc_tooltip, bg="#2a2a4a", padx=10, pady=8,
                      highlightbackground="#4a4a6c", highlightthickness=1)
        tf.pack()
        explanation = (
            "Projects when usage will hit 100% based on the "
            "rate of increase between two snapshots.\n\n"
            "Requires all 3 conditions to be met:\n"
            "  1. At least 60 seconds between snapshots\n"
            "  2. At least 1 percentage point increase\n"
            "  3. At least 1 refresh after launch\n\n"
            "Until all 3 are met, it shows 'Insufficient data'."
        )
        tk.Label(tf, text=explanation, font=("Consolas", 8), fg="#c0c0d8",
                 bg="#2a2a4a", justify="left", wraplength=280).pack()
        calc_tooltip.update_idletasks()
        tw = calc_tooltip.winfo_reqwidth(); th = calc_tooltip.winfo_reqheight()
        sx = win.winfo_screenwidth(); sy = win.winfo_screenheight()
        tx = max(5, min(event.x_root - tw // 2, sx - tw - 5))
        ty = max(5, min(event.y_root - th - 10, sy - th - 5))
        calc_tooltip.geometry(f"+{tx}+{ty}")

    def hide_calc_tooltip(event):
        nonlocal calc_tooltip
        if calc_tooltip: calc_tooltip.destroy(); calc_tooltip = None

    calc_link.bind("<Enter>", show_calc_tooltip)
    calc_link.bind("<Leave>", hide_calc_tooltip)

    tk.Frame(disp, bg=border, height=1).pack(fill="x", pady=(0, 12))

    # Display Metrics
    tk.Label(disp, text="Display Metrics", font=("Consolas", 10, "bold"),
             fg=fg, bg=bg).pack(anchor="w", pady=(0, 6))

    show_session_var = tk.BooleanVar(value=config.get("show_session", True))
    show_weekly_var = tk.BooleanVar(value=config.get("show_weekly", True))
    show_sonnet_var = tk.BooleanVar(value=config.get("show_sonnet", True))

    for var, label in [(show_session_var, "Session (5-hour)"),
                       (show_weekly_var, "Weekly (All Models)"),
                       (show_sonnet_var, "Weekly (Sonnet)")]:
        tk.Checkbutton(disp, text=f"  {label}", variable=var, font=("Consolas", 9),
                       fg=fg, bg=bg, selectcolor=surface,
                       activebackground=bg, activeforeground=fg,
                       highlightthickness=0).pack(anchor="w")

    tk.Frame(disp, bg=border, height=1).pack(fill="x", pady=(12, 12))

    show_ticker_var = tk.BooleanVar(value=config.get("show_reddit_ticker", True))
    tk.Checkbutton(disp, text='  Show Reddit ticker ("usage" @ r/ClaudeAI)',
                   variable=show_ticker_var, font=("Consolas", 9),
                   fg=fg, bg=bg, selectcolor=surface,
                   activebackground=bg, activeforeground=fg,
                   highlightthickness=0).pack(anchor="w")

    # ════════════════════════════════════════════════════════════════════
    # TAB 3: Colors
    # ════════════════════════════════════════════════════════════════════

    color_vars = {}
    color_labels = [
        ("bg_color", "Background Color"),
        ("color_text", "Text Color"),
        ("color_sufficient", "Sufficient Remaining"),
        ("color_partial", "Partial Depletion"),
        ("color_depleted", "Near/Full Depletion"),
    ]

    for key, label in color_labels:
        row = tk.Frame(col, bg=bg)
        row.pack(fill="x", pady=6)

        tk.Label(row, text=label, font=("Consolas", 10), fg=fg, bg=bg,
                 anchor="w").pack(side="left")

        current = config.get(key, DEFAULT_CONFIG[key])
        swatch = tk.Label(row, text="    ", bg=current, width=5,
                          relief="solid", bd=1)
        swatch.pack(side="right", padx=(4, 0))
        hex_lbl = tk.Label(row, text=current, font=("Consolas", 9),
                           fg=fg_dim, bg=bg)
        hex_lbl.pack(side="right")

        color_vars[key] = {"value": current, "swatch": swatch, "hex_lbl": hex_lbl}

        def pick_color(k=key):
            result = askcolor(color=color_vars[k]["value"], title=f"Choose {k}")
            if result and result[1]:
                color_vars[k]["value"] = result[1]
                color_vars[k]["swatch"].config(bg=result[1])
                color_vars[k]["hex_lbl"].config(text=result[1])

        swatch.bind("<Button-1>", lambda e, k=key: pick_color(k))
        swatch.config(cursor="hand2")
        hex_lbl.bind("<Button-1>", lambda e, k=key: pick_color(k))
        hex_lbl.config(cursor="hand2")

    # ════════════════════════════════════════════════════════════════════
    # Bottom buttons — always visible, outside tabs
    # ════════════════════════════════════════════════════════════════════

    tk.Frame(win, bg=border, height=1).pack(fill="x", side="bottom")

    btn_row = tk.Frame(win, bg=bg, padx=20, pady=12)
    btn_row.pack(fill="x", side="bottom")

    def _save_settings():
        on_scale_change()
        on_poll_change()
        config["start_on_startup"] = startup_var.get()
        old_bg_collect = config.get("background_collection", False)
        config["background_collection"] = bg_collect_var.get()
        config["scale_pct"] = last_valid_scale[0]
        if poll_mode[0] == 1:
            config["poll_interval_sec"] = last_valid_poll[0] * 60
        else:
            config["poll_interval_sec"] = last_valid_poll[0]
        config["show_last_refresh"] = show_refresh_var.get()
        config["refresh_display_mode"] = refresh_mode_var[0]
        config["show_depletion_estimates"] = depl_var.get()
        config["show_session"] = show_session_var.get()
        config["show_reddit_ticker"] = show_ticker_var.get()
        config["show_weekly"] = show_weekly_var.get()
        config["show_sonnet"] = show_sonnet_var.get()
        for key in color_vars:
            config[key] = color_vars[key]["value"]
        save_config()

        startup_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "ClaudeUsageWidget"
        try:
            import winreg
            reg = winreg.OpenKey(winreg.HKEY_CURRENT_USER, startup_key, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
            if config["start_on_startup"]:
                exe = sys.executable
                script = str(SCRIPT_DIR / "claude_systray.py")
                winreg.SetValueEx(reg, app_name, 0, winreg.REG_SZ,
                                  f'"{exe}" "{script}"')
            else:
                try: winreg.DeleteValue(reg, app_name)
                except FileNotFoundError: pass
            winreg.CloseKey(reg)
        except Exception as e:
            debug(f"[WARN] Startup registry: {e}")

        # Start/stop background collector daemon
        if config["background_collection"] and not old_bg_collect:
            # Just enabled — start the daemon
            collector_script = str(SCRIPT_DIR / "usage_collector.py")
            pythonw = str(Path(sys.executable).parent / "pythonw.exe")
            try:
                import subprocess
                subprocess.Popen([pythonw, collector_script],
                                 creationflags=0x00000008)  # DETACHED_PROCESS
                debug("[INFO] Started background collector daemon")
            except Exception as e:
                debug(f"[WARN] Failed to start collector: {e}")

            # Also add collector to startup registry if widget startup is enabled
            if config["start_on_startup"]:
                try:
                    import winreg
                    collector_name = "ClaudeUsageCollector"
                    reg = winreg.OpenKey(winreg.HKEY_CURRENT_USER, startup_key, 0,
                                        winreg.KEY_SET_VALUE)
                    winreg.SetValueEx(reg, collector_name, 0, winreg.REG_SZ,
                                      f'"{pythonw}" "{collector_script}"')
                    winreg.CloseKey(reg)
                except Exception:
                    pass

        elif not config["background_collection"] and old_bg_collect:
            # Just disabled — stop the daemon
            pid_file = SCRIPT_DIR / "collector.pid"
            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                    import ctypes
                    kernel32 = ctypes.windll.kernel32
                    handle = kernel32.OpenProcess(1, False, pid)  # PROCESS_TERMINATE
                    if handle:
                        kernel32.TerminateProcess(handle, 0)
                        kernel32.CloseHandle(handle)
                    pid_file.unlink(missing_ok=True)
                    debug("[INFO] Stopped background collector daemon")
                except Exception as e:
                    debug(f"[WARN] Failed to stop collector: {e}")

            # Remove from startup registry
            try:
                import winreg
                collector_name = "ClaudeUsageCollector"
                reg = winreg.OpenKey(winreg.HKEY_CURRENT_USER, startup_key, 0,
                                    winreg.KEY_SET_VALUE)
                try: winreg.DeleteValue(reg, collector_name)
                except FileNotFoundError: pass
                winreg.CloseKey(reg)
            except Exception:
                pass

        apply_scale_live()
        update_taskbar_text()

    def apply_settings():
        _save_settings()
        on_close()

    def _refresh_settings_bg():
        """Update the settings window's own background to match the new config."""
        new_bg = config.get("bg_color", "#1e1e2e")
        new_fg = config.get("color_text", "#ffffff")
        # Collect swatch widgets so we don't overwrite their display colors
        swatch_widgets = set()
        for cv in color_vars.values():
            swatch_widgets.add(cv["swatch"])
        for widget in [win, btn_row]:
            widget.configure(bg=new_bg)
        for tab_f in tab_frames.values():
            tab_f.configure(bg=new_bg)
            for child in tab_f.winfo_children():
                if child in swatch_widgets:
                    continue
                try:
                    child.configure(bg=new_bg)
                    if hasattr(child, 'cget') and child.cget('fg') not in (accent, "#e08080", "#ff3333"):
                        child.configure(fg=new_fg)
                except: pass
                for grandchild in child.winfo_children():
                    if grandchild in swatch_widgets:
                        continue
                    try:
                        grandchild.configure(bg=new_bg)
                    except: pass

    def apply_only():
        _save_settings()
        _refresh_settings_bg()

    def reset_defaults():
        for key, label in color_labels:
            default_val = DEFAULT_CONFIG[key]
            color_vars[key]["value"] = default_val
            color_vars[key]["swatch"].config(bg=default_val)
            color_vars[key]["hex_lbl"].config(text=default_val)
        startup_var.set(False)
        bg_collect_var.set(False)
        scale_var.set("100")
        last_valid_scale[0] = 100
        poll_var.set("300")
        last_valid_poll[0] = 300
        set_poll_mode(0)
        show_refresh_var.set(True)
        set_refresh_mode("exact")
        depl_var.set(True)
        show_session_var.set(True)
        show_ticker_var.set(True)
        show_weekly_var.set(True)
        show_sonnet_var.set(True)
        config.update(DEFAULT_CONFIG)
        save_config()

    tk.Button(btn_row, text="Reset to Defaults", command=reset_defaults,
              font=("Consolas", 9), bg="#aa0000", fg="#ffffff",
              activebackground="#cc0000", activeforeground="#ffffff",
              relief="solid", bd=1, padx=12, pady=6, cursor="hand2").pack(side="left")

    tk.Button(btn_row, text="Apply", command=apply_only,
              font=("Consolas", 9), bg=surface, fg=fg,
              activebackground="#333333", activeforeground=fg,
              relief="solid", bd=1, padx=16, pady=6, cursor="hand2").pack(side="left", expand=True)

    tk.Button(btn_row, text="Save & Exit", command=apply_settings,
              font=("Consolas", 9), bg=surface, fg="#33ff33",
              activebackground="#333333", activeforeground="#55ff55",
              relief="solid", bd=1, padx=20, pady=6, cursor="hand2").pack(side="right")

    # Show default tab
    switch_tab("general")

    win.bind("<Return>", lambda e: apply_settings())
    win.bind("<Escape>", lambda e: on_close())
    win.lift()
    win.focus_force()


# ── Polling ───────────────────────────────────────────────────────────────

def poll_loop():
    while True:
        interval = config.get("poll_interval_sec", 300)
        time.sleep(interval)
        fetch_usage()
        if taskbar_widget:
            taskbar_widget.after(0, update_taskbar_text)


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    debug("[DEBUG] Claude Usage Taskbar Widget starting...")
    load_config()
    fetch_usage()

    # Create the taskbar-docked widget (always visible)
    root = create_taskbar_widget()

    # Start polling in background
    threading.Thread(target=poll_loop, daemon=True).start()

    sp = usage_data.get("five_hour", {}).get("utilization", 0)
    wp = usage_data.get("seven_day", {}).get("utilization", 0)
    ss = usage_data.get("seven_day_sonnet", {})
    snp = ss.get("utilization", 0) if ss else 0
    debug(f"[DEBUG] Running: {sp:.0f}% / {wp:.0f}% / {snp:.0f}%")

    root.mainloop()


if __name__ == "__main__":
    main()
