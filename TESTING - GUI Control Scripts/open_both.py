"""Open visual dialog + settings, then list all windows to check taskbar grouping."""
import ctypes
from ctypes import wintypes
import time
import subprocess

user32 = ctypes.windll.user32
WNDPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

# Find pythonw PID
r = subprocess.run(["tasklist", "/fi", "IMAGENAME eq pythonw.exe", "/fo", "csv", "/nh"], capture_output=True, text=True)
pid = None
for line in r.stdout.strip().split("\n"):
    if "pythonw" in line.lower():
        pid = int(line.split(",")[1].strip('"'))
        break
if not pid:
    print("pythonw not running")
    exit(1)
print(f"pythonw PID: {pid}")

# Find widget window
def find_widget():
    result = [None]
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value != pid:
            return True
        t = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, t, 256)
        if t.value == "tk":
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            result[0] = ((rect.left+rect.right)//2, (rect.top+rect.bottom)//2)
        return True
    user32.EnumWindows(WNDPROC(cb), 0)
    return result[0]

def find_menu():
    result = [None]
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value == "#32768":
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            result[0] = (rect.left, rect.top, rect.right, rect.bottom)
        return True
    user32.EnumWindows(WNDPROC(cb), 0)
    return result[0]

def list_all_windows():
    print("\nAll pythonw windows:")
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            t = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, t, 256)
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            print(f"  '{t.value}' at ({rect.left},{rect.top},{rect.right},{rect.bottom})")
        return True
    user32.EnumWindows(WNDPROC(cb), 0)

center = find_widget()
if not center:
    print("Widget not found")
    exit(1)
cx, cy = center
print(f"Widget at ({cx}, {cy})")

# 1. Left click to open visual
user32.SetCursorPos(cx, cy)
time.sleep(0.1)
user32.mouse_event(0x0002, 0, 0, 0, 0)
time.sleep(0.05)
user32.mouse_event(0x0004, 0, 0, 0, 0)
print("Left-clicked -> visual dialog")
time.sleep(2)

# 2. Right click for context menu
user32.SetCursorPos(cx, cy)
time.sleep(0.1)
user32.mouse_event(0x0008, 0, 0, 0, 0)
time.sleep(0.05)
user32.mouse_event(0x0010, 0, 0, 0, 0)
time.sleep(0.5)

# 3. Find menu and click Settings (3rd item)
menu = find_menu()
if not menu:
    print("No menu found!")
    exit(1)
left, top, right, bottom = menu
item_h = (bottom - top) / 8  # 8 entries including separators
settings_y = int(top + item_h * 2.5)
settings_x = (left + right) // 2
print(f"Menu at {menu}, clicking Settings at ({settings_x}, {settings_y})")
user32.SetCursorPos(settings_x, settings_y)
time.sleep(0.1)
user32.mouse_event(0x0002, 0, 0, 0, 0)
time.sleep(0.05)
user32.mouse_event(0x0004, 0, 0, 0, 0)
print("Clicked Settings")
time.sleep(2)

list_all_windows()
