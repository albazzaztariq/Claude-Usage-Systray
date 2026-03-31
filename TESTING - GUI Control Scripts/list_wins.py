import ctypes
from ctypes import wintypes
user32 = ctypes.windll.user32
def cb(hwnd, _):
    if not user32.IsWindowVisible(hwnd):
        return True
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == 69280:
        t = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, t, 256)
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        print(f"{t.value!r} at ({r.left},{r.top},{r.right},{r.bottom})")
    return True
WNDPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows(WNDPROC(cb), 0)
