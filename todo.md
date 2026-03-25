# Claude Usage System Tray Widget — TODO

## Completed
- [x] System tray icon with colored usage bar
- [x] Hover shows session/weekly/sonnet % + reset times
- [x] Right-click menu: Refresh Now, Open Visual, GitHub, Quit
- [x] Visual dialog with usage bars, reset times, depletion estimate
- [x] Extra usage section (enabled: bar + stats, disabled: link to Account Settings)
- [x] Custom icon (usage-icon.png)
- [x] Account/Plan header with email
- [x] Extra usage values divided by 100 (API returns cents)
- [x] 5-minute auto-polling

## Known Issues
- [ ] System tray icon is small/black — Windows may hide it in overflow. User needs to drag it to the visible tray area. Investigate making it always-visible.
- [ ] Tray shows a bar graph, not "x% / y% / z%" text format — Windows system tray icons are 16x16 or 32x32 pixels, too small for readable text. Consider using a Windows notification area text overlay or a different approach (e.g., a floating mini-window pinned to taskbar).
- [ ] Email is hardcoded — need to pull from API or OAuth profile endpoint.
- [ ] Window has no rounded corners — tkinter doesn't natively support rounded windows. Would need `overrideredirect(True)` + custom drawing or switch to a different GUI framework (PyQt, wxPython).

## Features to Explore

### 1. Per-Model Usage Breakdown
- [ ] Display model-specific token usage: Opus, Sonnet, Opus Plan (if applicable), Haiku
- [ ] Format: "Model Usage:" with each model on its own line showing percentage
- [ ] Add a "?" icon next to "Model Usage" that on hover shows a popup (not a dialog) reading:
  "Model Token Generation (last updated [month] dd, yyyy)" with in/out token counts per model
- [ ] "What does this mean?" hyperlink → page explaining tokens, in vs out
- [ ] "Which Model Should I Use?" hyperlink → opens a dialog explaining:
  - Opus: complex reasoning, architecture, deep analysis
  - Sonnet: generic code, everyday tasks, fast responses
  - Opus Plan: best of both worlds for planning + execution
  - Haiku: boilerplate, simple templates, trivial tasks
  - Note: using the web UI (claude.ai) for planning reduces Code token consumption — the web UI uses a separate token pool
- [ ] Investigate: which API endpoint returns per-model usage data? Check if /usage returns model breakdown or if there's a separate endpoint

### 2. Consumption Speed & Estimated Depletion
- [ ] Track usage rate over configurable time window (default: last 5 minutes)
- [ ] Estimate when session allowance will run out at current rate
- [ ] Separately estimate when weekly allowance will run out
- [ ] Display as expandable section in the visual dialog
- [ ] Consider: graph/sparkline showing usage rate over time
- [ ] Consider: alert/notification when approaching limits (80%, 90%, 95%)

### 3. Smart Model Router (Screen Overlay)
- [ ] Build a screen overlay input field that sits always-on-top
- [ ] User types their prompt into the overlay
- [ ] Before sending to Claude Code, the prompt is piped to an external model router service
- [ ] The router analyzes the prompt and recommends which model to use (Opus/Sonnet/Haiku)
- [ ] If the recommended model differs from the current model in Claude Code:
  1. Send `/model [recommended-model]` to the Claude Code TUI terminal
  2. Wait for confirmation that the model switched
  3. Then send the actual prompt
- [ ] This optimizes token consumption by using cheaper models for simple tasks
- [ ] Router service options:
  - Local rules-based classifier (keyword matching, prompt length, complexity heuristics)
  - External API (a lightweight model that classifies prompt complexity)
  - Claude Haiku itself as the router (cheapest model classifies whether the task needs Opus)
- [ ] Technical challenges:
  - Controlling the Claude Code TUI programmatically (stdin/stdout piping or terminal automation)
  - Always-on-top overlay that doesn't interfere with other windows
  - Latency: the routing check adds time before the prompt is sent
- [ ] Consider: make this a VS Code extension command instead of a screen overlay
