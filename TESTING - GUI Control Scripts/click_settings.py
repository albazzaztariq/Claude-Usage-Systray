"""Click the Settings menu item in the context menu."""
import ctypes
import time

user32 = ctypes.windll.user32

# From the screenshot, the context menu is at the right edge of the screen
# "Settings..." appears to be the 3rd item. The menu items in the screenshot
# appear at approximately x=1020, y=870 area (right edge of primary monitor)
# But the coordinates need to match the actual pixel positions

# First, right-click to open the menu
# Widget at (720, 861, 838, 906)
user32.SetCursorPos(779, 883)
time.sleep(0.1)
user32.mouse_event(0x0008, 0, 0, 0, 0)  # right down
time.sleep(0.05)
user32.mouse_event(0x0010, 0, 0, 0, 0)  # right up
time.sleep(0.5)

# Now find the menu window - tkinter menus are separate windows
from ctypes import wintypes

def find_menu_windows():
    wins = []
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value == '#32768':  # Windows menu class
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            wins.append({
                'hwnd': hwnd,
                'rect': (rect.left, rect.top, rect.right, rect.bottom),
            })
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return wins

menus = find_menu_windows()
print(f"Found {len(menus)} menu windows")
for m in menus:
    print(f"  Menu at {m['rect']}")

# Tkinter right-click menus might not be #32768 class
# Let's just find all pythonw windows
def find_all_pythonw():
    wins = []
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == 69280:
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, 256)
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls, 64)
            wins.append({
                'hwnd': hwnd,
                'title': title.value,
                'class': cls.value,
                'rect': (rect.left, rect.top, rect.right, rect.bottom),
            })
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return wins

all_wins = find_all_pythonw()
print(f"\nAll pythonw windows:")
for w in all_wins:
    print(f"  {w['class']} '{w['title']}' at {w['rect']}")
