# Claude Usage Systray Widget — Handoff Document

## Project Location
```
C:\Users\azt12\OneDrive\Documents\Computing\Helpful Dev Tools\Claude-Usage-Systray\Source\claude_systray.py
```

NOTE: Previously was at `All Projects\Claude Code Add-on Projects\Claude-Usage-Systray\` — user moved it.

## How to Launch
```powershell
& "C:\Users\azt12\AppData\Local\Programs\Python\Python312\pythonw.exe" "C:\Users\azt12\OneDrive\Documents\Computing\Helpful Dev Tools\Claude-Usage-Systray\Source\claude_systray.py"
```
**Kill + restart after every code change:** `Get-Process pythonw | Stop-Process -Force`

## What This App Does
A small always-on-top borderless tkinter widget docked above the taskbar showing Claude API usage percentages (session/weekly/sonnet). Click opens a visual dialog with details. Right-click opens context menu. Settings has tabs (General, Customize, Colors).

## GitHub Repo
`https://github.com/albazzaztariq/Claude-Usage-Systray`

---

## BROKEN — Must Fix Next Session

### Settings window shows as separate taskbar entry
**Requirement:** ONE taskbar entry when both visual dialog and settings are open. Clicking either window brings it to front (free z-order). Settings X button must look identical to visual dialog's X button (normal Windows 11 title bar).

**What was tried and FAILED:**

| Approach | Result |
|----------|--------|
| `win.transient(visual_window)` | One entry BUT z-order locked — settings always on top, can't bring visual forward |
| `win.transient(taskbar_widget)` | Same z-order lock |
| No transient at all | Free z-order BUT two taskbar entries |
| `WS_EX_TOOLWINDOW` via SetWindowLongW | Hides from taskbar BUT ugly small title bar with tiny X button |
| `WS_EX_TOOLWINDOW` + forcing WS_CAPTION/SYSMENU styles | Still ugly on Windows 11 |
| Hidden owner via `CreateWindowExW` + `SetWindowLongW(GWL_HWNDPARENT)` | Two taskbar entries |
| Owner set to taskbar_widget HWND via `SetWindowLongW(GWL_HWNDPARENT)` | Two taskbar entries |

**What to try next:**
- **Per-window `AppUserModelID` via `IPropertyStore` COM interface** — Call `SHGetPropertyStoreForWindow` on each HWND and set `PKEY_AppUserModel_ID` to the same value. This is the documented Win32 way to group windows under one taskbar button without z-order constraints. Requires COM interop.
- **Single Toplevel that switches content** — Use one window that swaps between visual and settings content. Avoids the multi-window problem entirely.

**Window style reference (from inspecting running app):**
- Visual dialog: Style=`0x16ca0008`, ExStyle=`0x100` (just WS_EX_WINDOWEDGE)
- Settings (current broken state): Style=`0x16ca0008`, ExStyle=`0x180` (WS_EX_WINDOWEDGE | WS_EX_TOOLWINDOW)
- Target: Settings should have ExStyle=`0x100` (matching visual) but not appear in taskbar

---

## CRITICAL: ctypes Callback Safety

The WinEvent foreground callback (`_on_foreground` around line 580) uses `@WINFUNCTYPE` decorator. **It MUST NEVER call any tkinter method.** This includes:
- `root.after()` — CRASHES
- `root.attributes()` — CRASHES
- Any widget.config() or widget.pack() — CRASHES

These cause a **native crash** — no Python traceback, no crash.log, process just dies silently. Only pure Win32 API calls (`SetWindowPos`, `ShowWindow`, `IsWindowVisible`) are safe inside the callback.

The callback sets `root._focus_changed = True` and calls `force_visible()` (Win32-only). The 100ms polling loop (`keep_on_top`) handles all tkinter-side enforcement.

---

## What Works (completed this session)

1. **PythonW Open With** — `pythonw.exe` registered as "PythonW 3.12 (Windowed)" in Open With
2. **Crash protection** — `sys.excepthook` logs to `crash.log`. stdout/stderr protected for pythonw.
3. **Widget topmost** — Survives focus changes, Show Desktop, Explorer opening. 100ms polling + Win32-only reactive hook.
4. **Settings tabs** — General, Customize, Colors. Buttons pinned at bottom.
5. **Apply button** — Between Reset and Save & Exit. Saves + applies without closing.
6. **Colors global** — `bg_color` and `color_text` config keys apply to widget, visual, AND settings.
7. **Text white** — All dialog text is white by default. Configurable via Colors tab.
8. **Time formatting** — Over 24h shows "Xd Yh Zm" instead of just hours.
9. **Depletion estimates** — 3 states: `None`/`"need_time"` → "Insufficient data", `"never"` → "0%/sec (unchanged - insufficient data)", or actual time.
10. **Visual dialog refresh** — Right-click Refresh and in-dialog Refresh both save/restore window position.
11. **Button colors** — Reset: white on red (#aa0000). Save: bright green (#33ff33). Apply: white on surface.
12. **Color swatch fix** — `_refresh_settings_bg()` skips swatch widgets when updating backgrounds.

## Settings Function Structure
- `_save_settings()` — validates inputs, saves config, applies to widget live
- `apply_settings()` — calls `_save_settings()` then `on_close()`
- `apply_only()` — calls `_save_settings()` then `_refresh_settings_bg()`
- `_refresh_settings_bg()` — updates settings window bg/fg live, skips color swatches

## Config Keys Added This Session
- `color_text` (default `"#ffffff"`) — text color everywhere

## Depletion Estimate Logic (`estimate_depletion()`)
Returns:
- `None` — less than 2 entries in `usage_history` deque
- `"need_time"` — 2+ entries but < 60s between first and last
- `"never"` — enough data but dp <= 0 (usage didn't increase)
- Time string (e.g., "~15m", "~2h 30m") — actual projection

Display: `None`, `"need_time"`, and `"never"` all show "100% ETA: Insufficient data". The Calculation Method tooltip in Settings → Customize explains the 3 requirements.

## Unused Files (safe to delete)
- `Source/speedometer_53128.png` — not referenced anywhere
- `Source/usage-icon.png` — `ICON_PATH` defined but never used

## Key File Paths
| Item | Path |
|------|------|
| Main script | `...\Helpful Dev Tools\Claude-Usage-Systray\Source\claude_systray.py` |
| Config | `...\Helpful Dev Tools\Claude-Usage-Systray\Source\config.json` |
| Crash log | `...\Helpful Dev Tools\Claude-Usage-Systray\Source\crash.log` |
| Window icon | `...\Helpful Dev Tools\Claude-Usage-Systray\Source\speedometer.ico` |
| pythonw.exe | `C:\Users\azt12\AppData\Local\Programs\Python\Python312\pythonw.exe` |
