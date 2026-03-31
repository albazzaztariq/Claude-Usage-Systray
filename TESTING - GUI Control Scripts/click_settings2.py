"""Click Settings in the already-open context menu."""
import ctypes
import time

user32 = ctypes.windll.user32

# Menu is at (779, 729, 938, 868) — 159x139 pixels, ~5 items
# Items from screenshot: Refresh, Open Visual, Settings..., Report a..., Add-on...
# Settings is 3rd item = y offset ~28*2 + 14 = 70 from top
# Settings y = 729 + 70 = 799
# Center x = (779 + 938) / 2 = 858

settings_x = 858
settings_y = 799
print(f"Clicking Settings at ({settings_x}, {settings_y})")
user32.SetCursorPos(settings_x, settings_y)
time.sleep(0.2)
user32.mouse_event(0x0002, 0, 0, 0, 0)  # left down
time.sleep(0.05)
user32.mouse_event(0x0004, 0, 0, 0, 0)  # left up
print("Clicked Settings")
