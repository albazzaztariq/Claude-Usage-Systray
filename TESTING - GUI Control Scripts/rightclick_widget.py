"""Right-click the systray widget to open context menu, then click Settings."""
import ctypes
from ctypes import wintypes
import time

user32 = ctypes.windll.user32

# Widget is at (720, 861, 838, 906) from earlier scan
# But it might have moved. Re-find it.
def find_widget():
    result = [None]
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != 69280:
            return True
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, 256)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        # Widget is small and borderless, titled 'tk'
        if title.value == 'tk' and w < 200 and h < 100:
            result[0] = (rect.left, rect.top, rect.right, rect.bottom)
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return result[0]

rect = find_widget()
if rect:
    cx = (rect[0] + rect[2]) // 2
    cy = (rect[1] + rect[3]) // 2
    print(f"Widget at {rect}, right-clicking ({cx}, {cy})")
    user32.SetCursorPos(cx, cy)
    time.sleep(0.1)
    # Right click
    user32.mouse_event(0x0008, 0, 0, 0, 0)  # MOUSEEVENTF_RIGHTDOWN
    time.sleep(0.05)
    user32.mouse_event(0x0010, 0, 0, 0, 0)  # MOUSEEVENTF_RIGHTUP
    print("Right-clicked — context menu should appear")
else:
    print("Widget not found!")
