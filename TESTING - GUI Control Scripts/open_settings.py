"""Right-click widget then click Settings (3rd menu item)."""
import ctypes
from ctypes import wintypes
import time

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
    # Menu items: Refresh, Open Visual, Settings, Report, Add-on = 5 items
    menu_h = menu[3] - menu[1]
    item_h = menu_h / 5
    # Settings is item index 2 (0-based)
    settings_y = int(menu[1] + item_h * 2 + item_h / 2)
    settings_x = int((menu[0] + menu[2]) / 2)
    print(f"Menu at {menu}, item height={item_h:.0f}")
    print(f"Clicking Settings at ({settings_x}, {settings_y})")
    user32.SetCursorPos(settings_x, settings_y)
    time.sleep(0.2)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    print("Clicked Settings")
else:
    print("No menu found!")
