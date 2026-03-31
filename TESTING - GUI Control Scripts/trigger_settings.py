"""Trigger settings by right-clicking and using keyboard navigation."""
import ctypes
import time

user32 = ctypes.windll.user32

# Right-click widget to open context menu
user32.SetCursorPos(779, 883)
time.sleep(0.1)
user32.mouse_event(0x0008, 0, 0, 0, 0)
time.sleep(0.05)
user32.mouse_event(0x0010, 0, 0, 0, 0)
time.sleep(0.5)

# Use keyboard: press Down arrow twice to reach "Settings", then Enter
# Menu items: Refresh, Open Visual, Settings...
VK_DOWN = 0x28
VK_RETURN = 0x0D

for _ in range(2):
    user32.keybd_event(VK_DOWN, 0, 0, 0)
    user32.keybd_event(VK_DOWN, 0, 2, 0)
    time.sleep(0.1)

time.sleep(0.1)
user32.keybd_event(VK_RETURN, 0, 0, 0)
user32.keybd_event(VK_RETURN, 0, 2, 0)
print("Sent Down-Down-Enter — Settings should open")
