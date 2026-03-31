"""Find the systray widget window and simulate left-click to open visual dialog."""
import ctypes
from ctypes import wintypes
import time

user32 = ctypes.windll.user32

# Enumerate windows owned by pythonw
def find_widget_windows():
    windows = []
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, 256)
        if pid.value == 69280:
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            windows.append({
                'hwnd': hwnd,
                'title': title.value,
                'rect': (rect.left, rect.top, rect.right, rect.bottom),
                'w': rect.right - rect.left,
                'h': rect.bottom - rect.top,
            })
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return windows

wins = find_widget_windows()
for w in wins:
    print(f"HWND={w['hwnd']} title='{w['title']}' rect={w['rect']} size={w['w']}x{w['h']}")

# The widget is the small borderless one (overrideredirect)
# Find the smallest window — that's the widget
widget = min(wins, key=lambda w: w['w'] * w['h']) if wins else None
if widget:
    print(f"\nWidget: HWND={widget['hwnd']} at {widget['rect']}")
    # Click the center of it
    cx = (widget['rect'][0] + widget['rect'][2]) // 2
    cy = (widget['rect'][1] + widget['rect'][3]) // 2
    print(f"Clicking at ({cx}, {cy})")
    user32.SetCursorPos(cx, cy)
    time.sleep(0.1)
    # Left click
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
    print("Clicked — visual dialog should open")
