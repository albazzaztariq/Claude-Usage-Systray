"""Right-click widget, screenshot just the menu area, then dismiss."""
import ctypes
from ctypes import wintypes
import time, subprocess

user32 = ctypes.windll.user32

# Right-click to open menu
user32.SetCursorPos(779, 883)
time.sleep(0.1)
user32.mouse_event(0x0008, 0, 0, 0, 0)
time.sleep(0.05)
user32.mouse_event(0x0010, 0, 0, 0, 0)
time.sleep(0.5)

# Find the menu window
def find_menu():
    result = [None]
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value == '#32768':
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            result[0] = (rect.left, rect.top, rect.right, rect.bottom)
        return True
    WNDPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDPROC(callback), 0)
    return result[0]

menu = find_menu()
if menu:
    print(f"Menu at {menu}")
    # Screenshot just the menu with some padding
    x = menu[0] - 5
    y = menu[1] - 5
    w = menu[2] - menu[0] + 10
    h = menu[3] - menu[1] + 10
    subprocess.run([
        r"C:\Users\azt12\AppData\Local\Programs\Python\Python312\python.exe",
        r"C:\Users\azt12\OneDrive\Documents\Computing\Helpful Dev Tools\Full Autonomy Agent Harness\Source\screenshot.py",
        "--name", "menu_zoomed",
        "--region", f"{x},{y},{w},{h}"
    ])
    # Press Escape to dismiss menu
    time.sleep(0.5)
    import ctypes
    user32.keybd_event(0x1B, 0, 0, 0)  # VK_ESCAPE down
    user32.keybd_event(0x1B, 0, 2, 0)  # VK_ESCAPE up
else:
    print("No menu found")
