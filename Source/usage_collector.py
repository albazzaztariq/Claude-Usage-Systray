"""
Usage Collector Daemon — headless background data collection for Claude usage graphs.

Polls the Anthropic usage API at a configurable interval and appends data points
to usage_history.json. Runs independently of the widget — collects data even when
the widget GUI is closed.

Usage:
    pythonw.exe usage_collector.py          (headless, no console)
    python.exe usage_collector.py           (with console output for debugging)
    python.exe usage_collector.py --once    (single fetch, then exit)

This does NOT cost tokens — it only reads usage/billing data.
"""

import json
import time
import sys
import os
import requests
import logging
from pathlib import Path
from collections import deque
from datetime import datetime, timezone
from filelock import FileLock

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
CREDS_PATH = Path.home() / ".claude" / ".credentials.json"
HISTORY_PATH = SCRIPT_DIR / "usage_history.json"
LOCK_PATH = SCRIPT_DIR / "usage_history.lock"
PID_PATH = SCRIPT_DIR / "collector.pid"
LOG_PATH = SCRIPT_DIR / "collector.log"

API_URL = "https://api.anthropic.com/api/oauth/usage"
DEFAULT_INTERVAL = 600  # 10 minutes
MAX_HISTORY = 500

# Setup logging
logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("collector")

# Also log to console if not pythonw
if sys.executable.lower().endswith("python.exe"):
    logging.getLogger().addHandler(logging.StreamHandler())


def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def load_creds():
    try:
        with open(CREDS_PATH, "r") as f:
            data = json.load(f).get("claudeAiOauth", {})
        return data.get("accessToken")
    except Exception as e:
        log.error(f"Credentials: {e}")
        return None


def load_history():
    try:
        if HISTORY_PATH.exists():
            with open(HISTORY_PATH, "r") as f:
                return deque(json.load(f), maxlen=MAX_HISTORY)
    except Exception as e:
        log.warning(f"Load history: {e}")
    return deque(maxlen=MAX_HISTORY)


def save_history(history):
    """Save history with file locking so the widget can read safely."""
    try:
        lock = FileLock(str(LOCK_PATH), timeout=5)
        with lock:
            with open(HISTORY_PATH, "w") as f:
                json.dump(list(history), f)
    except Exception as e:
        log.error(f"Save history: {e}")


def fetch_once(token):
    """Single API fetch. Returns (session_pct, weekly_pct, sonnet_pct) or None."""
    try:
        r = requests.get(API_URL, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }, timeout=15)
        if r.status_code == 200:
            data = r.json()
            session_pct = data.get("five_hour", {}).get("utilization", 0)
            weekly_pct = data.get("seven_day", {}).get("utilization", 0)
            ss = data.get("seven_day_sonnet", {})
            sonnet_pct = ss.get("utilization", 0) if ss else 0
            return (session_pct, weekly_pct, sonnet_pct)
        elif r.status_code == 429:
            log.warning("Rate limited (429)")
        else:
            log.warning(f"API returned {r.status_code}")
    except requests.exceptions.Timeout:
        log.warning("API timeout")
    except requests.exceptions.ConnectionError:
        log.warning("No connection")
    except Exception as e:
        log.error(f"Fetch error: {e}")
    return None


def write_pid():
    try:
        with open(PID_PATH, "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass


def clear_pid():
    try:
        PID_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def is_already_running():
    """Check if another collector instance is running."""
    try:
        if PID_PATH.exists():
            pid = int(PID_PATH.read_text().strip())
            # Check if process exists
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            # Process doesn't exist — stale PID file
            PID_PATH.unlink(missing_ok=True)
    except Exception:
        pass
    return False


def main():
    single = "--once" in sys.argv

    if not single and is_already_running():
        log.info("Another collector is already running. Exiting.")
        sys.exit(0)

    config = load_config()
    if not config.get("background_collection", False) and not single:
        log.info("Background collection disabled in config. Exiting.")
        sys.exit(0)

    interval = config.get("collector_interval_sec", DEFAULT_INTERVAL)
    log.info(f"Starting usage collector (interval={interval}s, single={single})")

    write_pid()

    try:
        while True:
            token = load_creds()
            if not token:
                log.error("No credentials found")
                if single:
                    break
                time.sleep(interval)
                continue

            result = fetch_once(token)
            if result:
                session_pct, weekly_pct, sonnet_pct = result
                history = load_history()
                history.append((time.time(), session_pct, weekly_pct, sonnet_pct))
                save_history(history)
                log.info(f"Collected: session={session_pct:.1f}% weekly={weekly_pct:.1f}% sonnet={sonnet_pct:.1f}%")

            if single:
                break

            # Re-read config each cycle in case interval changed
            config = load_config()
            if not config.get("background_collection", False):
                log.info("Background collection disabled. Stopping.")
                break
            interval = config.get("collector_interval_sec", DEFAULT_INTERVAL)
            time.sleep(interval)
    finally:
        clear_pid()
        log.info("Collector stopped.")


if __name__ == "__main__":
    main()
