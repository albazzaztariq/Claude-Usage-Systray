"""Right-click widget, find the menu, click Settings item directly."""
import ctypes
from ctypes import wintypes
import time

user32 = ctypes.windll.user32
PID = 69280

# Right click widget
user32.SetCursorPos(780, 883)
time.sleep(0.1)
user32.mouse_event(0x0008, 0, 0, 0, 0)
time.sleep(0.05)
user32.mouse_event(0x0010, 0, 0, 0, 0)
time.sleep(0.5)

# Find the menu window (#32768 class)
menu_rect = [None]
def find_menu(hwnd, _):
    if not user32.IsWindowVisible(hwnd):
        return True
    cls = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, cls, 64)
    if cls.value == "#32768":
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        menu_rect[0] = (r.left, r.top, r.right, r.bottom)
    return True
WNDPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows(WNDPROC(find_menu), 0)

if not menu_rect[0]:
    print("No menu found!")
    exit(1)

left, top, right, bottom = menu_rect[0]
print(f"Menu at ({left},{top},{right},{bottom})")

# Menu has items: Refresh, Open Visual, Settings, [sep], Report, Add-on, [sep], Quit
# Settings is 3rd item (index 2). Each item ~20px high
# Click center-x, and y for 3rd item
cx = (left + right) // 2
item_h = (bottom - top) // 8  # ~8 entries including separators
settings_y = top + int(item_h * 2.5)  # 3rd item center
print(f"Clicking Settings at ({cx}, {settings_y})")
user32.SetCursorPos(cx, settings_y)
time.sleep(0.1)
user32.mouse_event(0x0002, 0, 0, 0, 0)
time.sleep(0.05)
user32.mouse_event(0x0004, 0, 0, 0, 0)
print("Clicked Settings")
time.sleep(2)

# List windows
print("\nAll pythonw windows:")
def list_all(hwnd, _):
    if not user32.IsWindowVisible(hwnd):
        return True
    p = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    if p.value == PID:
        t = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, t, 256)
        print(f"  '{t.value}'")
    return True
user32.EnumWindows(WNDPROC(list_all), 0)
