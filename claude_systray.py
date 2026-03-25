"""
Claude Usage Taskbar Widget — Windows
Docks a small always-on-top window to the taskbar showing "x% / y% / z%"
with color-coded percentages. Double-click or left-click opens the visual dialog.
Right-click shows menu.
"""

import json
import os
import sys
import time
import threading
import webbrowser
import tkinter as tk
from datetime import datetime, timezone
from collections import deque
from pathlib import Path
import ctypes
from ctypes import wintypes

import requests
from PIL import Image, ImageDraw, ImageFont, ImageTk
import pystray

# ── Paths ─────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
CREDS_PATH = Path.home() / ".claude" / ".credentials.json"
ICON_PATH = SCRIPT_DIR / "usage-icon.png"
API_URL = "https://api.anthropic.com/api/oauth/usage"
API_HEADERS_EXTRA = {"anthropic-beta": "oauth-2025-04-20"}
GITHUB_URL = "https://github.com/albazzaztariq/Claude-Usage-Systray"
ACCOUNT_SETTINGS_URL = "https://claude.ai/settings/usage"
POLL_INTERVAL = 300

# ── State ─────────────────────────────────────────────────────────────────

usage_data = {}
creds_data = {}
last_refresh = None
usage_history = deque(maxlen=60)
visual_window = None
taskbar_widget = None  # The docked taskbar window


# ── Credentials ───────────────────────────────────────────────────────────

def load_creds():
    global creds_data
    try:
        with open(CREDS_PATH, "r") as f:
            creds_data = json.load(f).get("claudeAiOauth", {})
        return creds_data.get("accessToken")
    except Exception as e:
        print(f"[ERROR] Credentials: {e}")
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

def fetch_usage():
    global usage_data, last_refresh
    token = load_creds()
    if not token:
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
            usage_history.append((time.time(), session_pct))
            return True
    except Exception as e:
        print(f"[ERROR] API: {e}")
    return False


# ── Helpers ───────────────────────────────────────────────────────────────

def format_reset(iso_str):
    if not iso_str: return "unknown"
    try:
        delta = datetime.fromisoformat(iso_str) - datetime.now(timezone.utc)
        total_min = max(0, int(delta.total_seconds() / 60))
        h, m = divmod(total_min, 60)
        return f"{h}h {m}m" if h > 0 else f"{m}m"
    except:
        return "unknown"


def estimate_depletion():
    if len(usage_history) < 2: return None
    t0, p0 = usage_history[0]
    t1, p1 = usage_history[-1]
    dt = t1 - t0
    dp = p1 - p0
    if dt < 60 or dp <= 0: return None
    mins = ((100.0 - p1) / (dp / dt)) / 60
    if mins < 60: return f"~{int(mins)}m"
    return f"~{int(mins // 60)}h {int(mins % 60)}m"


def pct_color_hex(pct):
    if pct < 50: return "#64c864"
    elif pct < 75: return "#e6c832"
    elif pct < 90: return "#e69632"
    return "#e65050"


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
    """Create a tiny borderless always-on-top window docked to the taskbar."""
    global taskbar_widget

    root = tk.Tk()
    taskbar_widget = root
    root.overrideredirect(True)  # No title bar, no border
    root.attributes("-topmost", True)  # Always on top
    root.configure(bg="#1e1e2e")

    # Size and position — dock to bottom-right, above the taskbar
    widget_w = 220
    widget_h = 26
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()

    # Position: right side, just above where taskbar sits
    # Taskbar is typically 48px on Windows 11, 40px on Windows 10
    taskbar_info = get_taskbar_height()
    if taskbar_info:
        tb_top = taskbar_info[0]
        x = screen_w - widget_w - 180  # Left of the clock area
        y = tb_top + 6  # Sit inside the taskbar
    else:
        x = screen_w - widget_w - 180
        y = screen_h - 40  # Guess: 40px taskbar

    root.geometry(f"{widget_w}x{widget_h}+{x}+{y}")

    # Content frame
    frame = tk.Frame(root, bg="#1e1e2e")
    frame.pack(fill="both", expand=True)

    # The percentage labels — these get updated by update_taskbar_text()
    root._session_lbl = tk.Label(frame, text="--", font=("Segoe UI Semibold", 11),
                                  fg="#64c864", bg="#1e1e2e")
    root._session_lbl.pack(side="left", padx=(6, 0))

    root._sep1 = tk.Label(frame, text="/", font=("Segoe UI", 10), fg="#585b70", bg="#1e1e2e")
    root._sep1.pack(side="left", padx=2)

    root._weekly_lbl = tk.Label(frame, text="--", font=("Segoe UI Semibold", 11),
                                 fg="#64c864", bg="#1e1e2e")
    root._weekly_lbl.pack(side="left")

    root._sep2 = tk.Label(frame, text="/", font=("Segoe UI", 10), fg="#585b70", bg="#1e1e2e")
    root._sep2.pack(side="left", padx=2)

    root._sonnet_lbl = tk.Label(frame, text="--", font=("Segoe UI Semibold", 11),
                                 fg="#64c864", bg="#1e1e2e")
    root._sonnet_lbl.pack(side="left")

    # Hover tooltip
    root._tooltip = None

    def show_tooltip(event):
        if root._tooltip: return
        fh = usage_data.get("five_hour", {})
        sd = usage_data.get("seven_day", {})
        sr = format_reset(fh.get("resets_at"))
        wr = format_reset(sd.get("resets_at"))
        depl = estimate_depletion()
        text = f"Session resets in {sr}\nWeekly resets in {wr}"
        if depl: text += f"\nEst. depletion: {depl}"

        tip = tk.Toplevel(root)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.geometry(f"+{event.x_root + 10}+{event.y_root - 60}")
        tip.configure(bg="#2a2a4a")

        tf = tk.Frame(tip, bg="#2a2a4a", padx=8, pady=6, highlightbackground="#4a4a6c",
                      highlightthickness=1)
        tf.pack()
        tk.Label(tf, text=text, font=("Segoe UI", 9), fg="#c0c0d8", bg="#2a2a4a",
                 justify="left").pack()
        root._tooltip = tip

    def hide_tooltip(event):
        if root._tooltip:
            root._tooltip.destroy()
            root._tooltip = None

    # Bind events
    for widget in [frame, root._session_lbl, root._sep1, root._weekly_lbl,
                   root._sep2, root._sonnet_lbl]:
        widget.bind("<Enter>", show_tooltip)
        widget.bind("<Leave>", hide_tooltip)
        widget.bind("<Button-1>", lambda e: threading.Thread(target=open_visual, daemon=True).start())
        widget.bind("<Button-3>", lambda e: show_context_menu(e, root))

    # Allow dragging
    root._drag_data = {"x": 0, "y": 0}

    def start_drag(event):
        root._drag_data["x"] = event.x
        root._drag_data["y"] = event.y

    def do_drag(event):
        dx = event.x - root._drag_data["x"]
        dy = event.y - root._drag_data["y"]
        x = root.winfo_x() + dx
        y = root.winfo_y() + dy
        root.geometry(f"+{x}+{y}")

    frame.bind("<ButtonPress-2>", start_drag)  # Middle-click drag
    frame.bind("<B2-Motion>", do_drag)

    update_taskbar_text()
    return root


def show_context_menu(event, root):
    menu = tk.Menu(root, tearoff=0, bg="#2a2a4a", fg="#e0e0f0",
                   activebackground="#3a5a7c", activeforeground="white",
                   font=("Segoe UI", 9))
    menu.add_command(label="Refresh Now", command=lambda: do_refresh_taskbar())
    menu.add_command(label="Open Visual", command=lambda: threading.Thread(target=open_visual, daemon=True).start())
    menu.add_separator()
    menu.add_command(label="Add-on/Author GitHub", command=lambda: webbrowser.open(GITHUB_URL))
    menu.add_separator()
    menu.add_command(label="Quit", command=lambda: quit_app())
    menu.tk_popup(event.x_root, event.y_root)


def do_refresh_taskbar():
    fetch_usage()
    update_taskbar_text()


def quit_app():
    global taskbar_widget
    if taskbar_widget:
        taskbar_widget.destroy()
    os._exit(0)


def update_taskbar_text():
    """Update the percentage labels and their colors."""
    if not taskbar_widget:
        return

    fh = usage_data.get("five_hour", {})
    sd = usage_data.get("seven_day", {})
    ss = usage_data.get("seven_day_sonnet", {})

    sp = fh.get("utilization", 0)
    wp = sd.get("utilization", 0)
    snp = ss.get("utilization", 0) if ss else 0

    taskbar_widget._session_lbl.config(text=f"{sp:.0f}%", fg=pct_color_hex(sp))
    taskbar_widget._weekly_lbl.config(text=f"{wp:.0f}%", fg=pct_color_hex(wp))
    taskbar_widget._sonnet_lbl.config(text=f"{snp:.0f}%", fg=pct_color_hex(snp))


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
    depl_str = f"\nEst. session depletion: {depl}" if depl else ""
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

    win = tk.Toplevel() if taskbar_widget else tk.Tk()
    visual_window = win
    win.title("Claude Usage")
    win.geometry("420x540")
    win.resizable(False, False)
    win.configure(bg="#2a2a4a")
    win.attributes("-topmost", True)

    try:
        ico = ImageTk.PhotoImage(Image.open(ICON_PATH).resize((32, 32)))
        win.iconphoto(True, ico)
        win._ico_ref = ico
    except: pass

    def on_close():
        global visual_window
        visual_window = None
        win.destroy()
    win.protocol("WM_DELETE_WINDOW", on_close)

    bg = "#1a1a2e"
    card_bg = "#16213e"
    fg = "#e8e8f0"
    dim = "#b0b0c8"
    accent = "#7ab3e0"
    border_c = "#4a4a6c"

    outer = tk.Frame(win, bg=border_c, padx=2, pady=2)
    outer.pack(fill="both", expand=True)
    main = tk.Frame(outer, bg=bg)
    main.pack(fill="both", expand=True)

    # Header
    hdr = tk.Frame(main, bg=card_bg, padx=16, pady=10)
    hdr.pack(fill="x", padx=8, pady=(8, 4))
    tk.Label(hdr, text=f"Account: {get_email()}", font=("Segoe UI", 10),
             fg=dim, bg=card_bg, anchor="w").pack(fill="x")
    tk.Label(hdr, text=f"Plan: {get_plan_label()}", font=("Segoe UI", 14, "bold"),
             fg=accent, bg=card_bg, anchor="w").pack(fill="x")
    if last_refresh:
        ago = int((datetime.now(timezone.utc) - last_refresh).total_seconds())
        ago_str = f"Updated {ago}s ago" if ago < 120 else f"Updated {ago // 60}m ago"
    else:
        ago_str = "Not yet refreshed"
    tk.Label(hdr, text=ago_str, font=("Segoe UI", 9), fg=dim, bg=card_bg).pack(anchor="w")

    # Usage bars
    def add_bar(parent, label, pct, reset_str):
        f = tk.Frame(parent, bg=bg)
        f.pack(fill="x", padx=16, pady=(8, 2))
        tk.Label(f, text=f"{label}: {pct:.0f}%", font=("Segoe UI", 10, "bold"),
                 fg=fg, bg=bg, anchor="w").pack(fill="x")
        bar = tk.Frame(f, bg="#2a2a4a", height=18, highlightbackground=border_c, highlightthickness=1)
        bar.pack(fill="x", pady=(2, 0))
        bar.pack_propagate(False)
        fw = max(1, int(380 * min(pct, 100) / 100))
        tk.Frame(bar, bg=pct_color_hex(pct), width=fw, height=18).place(x=0, y=0)
        tk.Label(f, text=f"Resets in {reset_str}", font=("Segoe UI", 9),
                 fg=dim, bg=bg, anchor="w").pack(fill="x")

    add_bar(main, "Session (5-hour)", sp, sr)
    add_bar(main, "Weekly (all models)", wp, wr)
    add_bar(main, "Weekly (Sonnet)", snp, wr)

    depl = estimate_depletion()
    if depl:
        tk.Label(main, text=f"Est. session depletion: {depl}",
                 font=("Segoe UI", 9, "bold"), fg="#f38ba8", bg=bg, anchor="w",
                 padx=16).pack(fill="x", pady=(6, 0))

    # Separator
    tk.Frame(main, bg=border_c, height=1).pack(fill="x", padx=16, pady=(12, 8))

    # Extra Usage
    if eu and eu.get("is_enabled"):
        ef = tk.Frame(main, bg=bg)
        ef.pack(fill="x", padx=16)
        used = eu.get("used_credits", 0) / 100
        limit = eu.get("monthly_limit", 0) / 100
        remaining = max(0, limit - used)
        eu_pct = min(100, int((used / limit * 100) if limit > 0 else 0))

        tk.Label(ef, text="Extra Usage via API (Monthly)", font=("Segoe UI", 9),
                 fg=dim, bg=bg, anchor="w").pack(fill="x")
        sr_f = tk.Frame(ef, bg=bg)
        sr_f.pack(fill="x", pady=(2, 0))
        tk.Label(sr_f, text=f"${used:.2f} Used", font=("Segoe UI", 8), fg=dim, bg=bg).pack(side="left")
        tk.Label(sr_f, text=f"  {eu_pct}%  ", font=("Segoe UI", 9, "bold"), fg="#f9e2af", bg=bg).pack(side="left")
        tk.Label(sr_f, text=f"${limit:.0f} Allowed", font=("Segoe UI", 8), fg=dim, bg=bg).pack(side="left")
        tk.Label(sr_f, text=f"${remaining:.2f} Remaining", font=("Segoe UI", 8), fg=dim, bg=bg).pack(side="right")
        eb = tk.Frame(ef, bg="#2a2a4a", height=10, highlightbackground=border_c, highlightthickness=1)
        eb.pack(fill="x", pady=(2, 0))
        eb.pack_propagate(False)
        tk.Frame(eb, bg="#f9e2af", width=max(1, int(380 * eu_pct / 100)), height=10).place(x=0, y=0)
    else:
        ef = tk.Frame(main, bg=bg)
        ef.pack(fill="x", padx=16)
        tk.Label(ef, text="Extra Usage is currently disabled. Enable through",
                 font=("Segoe UI", 9), fg=dim, bg=bg, anchor="w").pack(anchor="w")
        link = tk.Label(ef, text="Account Settings", font=("Segoe UI", 9, "underline"),
                        fg=accent, bg=bg, cursor="hand2")
        link.pack(anchor="w")
        link.bind("<Button-1>", lambda e: webbrowser.open(ACCOUNT_SETTINGS_URL))
        tk.Label(ef, text="Caution: Anthropic API costs can be substantially higher "
                          "than equivalent subscription token generation.",
                 font=("Segoe UI", 8), fg="#e88080", bg=bg, wraplength=380, justify="left",
                 anchor="w").pack(fill="x", pady=(4, 0))

    # Refresh button
    bf = tk.Frame(main, bg=bg)
    bf.pack(pady=(16, 12))

    def do_refresh():
        fetch_usage()
        update_taskbar_text()
        on_close()
        threading.Thread(target=open_visual, daemon=True).start()

    tk.Button(bf, text="Refresh Now", command=do_refresh,
              font=("Segoe UI Semibold", 10), bg="#2d6b8c", fg="white",
              activebackground="#3a8abf", activeforeground="white",
              relief="solid", bd=1, padx=20, pady=6, cursor="hand2").pack()


# ── Polling ───────────────────────────────────────────────────────────────

def poll_loop():
    while True:
        time.sleep(POLL_INTERVAL)
        fetch_usage()
        if taskbar_widget:
            taskbar_widget.after(0, update_taskbar_text)


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    print("[DEBUG] Claude Usage Taskbar Widget starting...")
    fetch_usage()

    # Create the taskbar-docked widget (always visible)
    root = create_taskbar_widget()

    # Start polling in background
    threading.Thread(target=poll_loop, daemon=True).start()

    sp = usage_data.get("five_hour", {}).get("utilization", 0)
    wp = usage_data.get("seven_day", {}).get("utilization", 0)
    ss = usage_data.get("seven_day_sonnet", {})
    snp = ss.get("utilization", 0) if ss else 0
    print(f"[DEBUG] Running: {sp:.0f}% / {wp:.0f}% / {snp:.0f}%")

    root.mainloop()


if __name__ == "__main__":
    main()
