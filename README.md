<div align="center">

# TI — Trajectoire Idéale

**Keep your day on the racing line.**

A local-first focus guardrail for Linux. You plan the day in time blocks; TI watches what you're actually doing and pulls you back when you drift.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Status: alpha](https://img.shields.io/badge/status-alpha-orange)
![Python 3](https://img.shields.io/badge/python-3-3776AB?logo=python&logoColor=white)
![Dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen)
![Platform: Linux](https://img.shields.io/badge/platform-Linux-FCC624?logo=linux&logoColor=black)
![GNOME Shell 50](https://img.shields.io/badge/GNOME%20Shell-50-4A86CF?logo=gnome&logoColor=white)
![Local first](https://img.shields.io/badge/data-stays%20on%20your%20machine-blue)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#contributing)

</div>

---

In motorsport, the *trajectoire idéale* is the ideal racing line: the path that costs the least time. TI applies the same idea to your day. You decide the line (study, work, break, free time); TI keeps you on it.

It isn't limited to a browser tab, and it isn't a calendar that politely pings you. It runs on your desktop, knows which block you're in, notices the window you're actually using, and escalates from a gentle nudge to a full-screen "back to the line" takeover. It never locks you out. You can always override it.

## Features

- **Time-block planning.** Focus, free and break blocks. Only focus blocks are enforced.
- **Real drift detection.** A small GNOME Shell extension reports the focused window, so TI reacts to what you do, not what you said you'd do.
- **Escalating, on-brand UI.** A top-bar status pill, slide-in banners, and a full-screen overlay, all drawn by TI itself rather than generic system notifications.
- **Guardrails you control.** Allowed apps and blocked keywords per focus block, edited in plain language.
- **Score.** Every enforced second is logged; see your "on the line" percentage per block.
- **Browser control panel.** A local web page to plan the day, tune guardrails and check your score. No terminal needed once it's running.
- **Claude Code integration.** Every command has `--json` output, and an optional hook gives Claude Code your current block so it can flag off-plan requests.
- **Private by design.** Everything runs and stays on your machine. No accounts, no network calls, no dependencies beyond Python's standard library.

## How it escalates

When you spend time on something outside the current focus block:

| Time off the line | What TI does |
|---|---|
| 1 minute | Amber **OFF THE LINE** banner |
| 3 minutes | Red banner |
| 5 minutes | Full-screen **BACK TO THE LINE** overlay (dismiss with **I'M BACK**, which snoozes it for 90 seconds) |

Returning to an allowed app clears everything. If the watcher stops, the UI hides itself after 20 seconds, so a crash can't leave a stuck overlay. Thresholds are configurable (`--t1`, `--t2`, `--t3`).

## Quick start

> **Requirements:** Linux with GNOME Shell 50 (Wayland), and Python 3. Developed and tested on Python 3.14.

```bash
git clone https://github.com/ricozama121803/TI.git
cd TI

# 1. Install the GNOME extension (symlinked, so updates apply on re-login)
mkdir -p ~/.local/share/gnome-shell/extensions
ln -sfn "$PWD/gnome-extension/ti-active-window@ti.local" \
        ~/.local/share/gnome-shell/extensions/ti-active-window@ti.local

# 2. Log out and back in (Wayland only loads new extension code at login), then:
gnome-extensions enable ti-active-window@ti.local

# 3. Open the control panel; this also starts the watcher
./ti.py ui
```

In the panel, add a focus block that covers the current time, then open a distraction (a YouTube tab, for example) and watch TI react. Want to see the UI without drifting first? Run `./ti.py demo` (with the watcher stopped) for a scripted tour of every state.

## Command line

Everything the panel does is also available from the CLI, and all commands accept `--json` before the subcommand.

| Command | What it does |
|---|---|
| `ti.py ui` | Open the control panel and run the watcher |
| `ti.py watch` | Run the watcher on its own |
| `ti.py add 09:00 11:00 focus "Study"` | Add a block (`focus`, `free` or `break`) |
| `ti.py remove 09:00` | Remove the block starting at that time |
| `ti.py plan` / `ti.py clear` | Show or empty the day |
| `ti.py now` | What should I be doing right now? |
| `ti.py active` | The focused window as TI sees it |
| `ti.py check` | Classify the focused window: `on`, `off` or `neutral` |
| `ti.py score` | On-the-line percentage per block today |
| `ti.py demo` | Scripted walkthrough of the on-screen UI |

## Guardrails

Rules apply to **focus** blocks. Edit them in the control panel, or in `~/.config/ti/rules.json`:

```json
{
  "focus": {
    "allow": ["ghostty", "code", "firefox", "chrome", "obsidian"],
    "deny":  ["youtube", "reddit", "netflix", "steam", "discord"]
  }
}
```

- `allow` patterns are regexes matched against the **app** name. If the list isn't empty, any app that doesn't match counts as drift.
- `deny` patterns are regexes matched against the **app and window title**, and they always win.

## Claude Code integration

TI can feed your current block to Claude Code so it can mention when a request looks unrelated to what you planned (it never refuses). Add this to the `hooks` section of `~/.claude/settings.json`, using the path to your clone:

```json
"UserPromptSubmit": [
  { "matcher": "", "hooks": [
    { "type": "command", "command": "python3 /path/to/TI/ti.py hook" }
  ] }
]
```

You can also ask Claude Code to build your day for you, since it can run `ti.py add` and read `ti.py --json now`.

## How it works

```
 focused window ──► GNOME extension ──► active.json ─┐
                                                     ▼
 plan.json + rules.json ─────────────────────► ti.py watch ──► state.json ──► GNOME extension ──► pill · banner · overlay
                                                     │
                                                     └──► log.jsonl ──► score
                                  ti.py ui ──► local web panel (127.0.0.1)
```

| Path | Purpose |
|---|---|
| `ti.py` | CLI, watcher, rule engine and local web server (standard library only) |
| `ui/index.html` | Control panel (single file, no build step) |
| `gnome-extension/` | Reports the focused window and draws TI's on-screen UI |
| `~/.config/ti/` | Your plan and rules |
| `~/.local/share/ti/log.jsonl` | Activity log used for scoring |

**Security notes.** The control panel binds to `127.0.0.1` only, rejects requests with a non-local `Host`, and requires a custom header on writes so other websites can't modify your plan. Window titles and block names are rendered as text, never HTML.

## Limitations

TI is alpha software; expect rough edges.

- **GNOME on Wayland only** for now. Wayland doesn't let apps read other windows, so TI relies on the extension. It's tested against GNOME Shell 50.
- **Browsers are seen by window title only.** TI can't read URLs or background tabs yet, so a distracting site is caught only if its name appears in the tab title and that tab is focused.
- **The overlay doesn't capture the keyboard.** It covers the screen but keystrokes still reach the window underneath.
- The overlay and banners draw on the **primary monitor** only.
- You start TI yourself (`./ti.py ui`); there's no autostart yet.

## Roadmap

- [ ] Autostart at login and a desktop launcher
- [ ] Browser-side tab awareness (URL and audio per tab)
- [ ] Typed-reason overlay and a daily "lap review"
- [ ] Idle and screen-lock handling
- [ ] Recurring plan templates and score history
- [ ] Per-block custom rules

## Contributing

Issues and pull requests are welcome. For anything non-trivial, open an issue first so we can agree on the approach.

## License

[MIT](LICENSE) © 2026 Enrico Zamarripa
