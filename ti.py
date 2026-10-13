#!/usr/bin/env python3
"""TI - Trajectoire Idéale. Keep the day on the racing line."""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PLAN_PATH = Path.home() / ".config" / "ti" / "plan.json"
RULES_PATH = Path.home() / ".config" / "ti" / "rules.json"
LOG_PATH = Path.home() / ".local" / "share" / "ti" / "log.jsonl"
# Regexes, case-insensitive. Only "focus" blocks are enforced. "deny" is matched against
# "app title" and beats "allow". "allow" is matched against the app class; an empty
# allow list means anything not denied is fine.
DEFAULT_RULES = {
    "focus": {
        "allow": ["ghostty", "terminal", "code", "cursor", "obsidian", "evince", "okular",
                  "libreoffice", "firefox", "chrome", "chromium", "brave", "zotero", "anki"],
        "deny": ["youtube", "reddit", "twitter", "x\\.com", "netflix", "twitch", "tiktok",
                 "instagram", "facebook", "steam", "discord"],
    }
}
BLOCK_TYPES = ("focus", "free", "break")
REMINDERS = {
    "focus": "Focus time. Stay on the line.",
    "free": "Free time. Enjoy it, guilt-free.",
    "break": "Break. Step away from the screen.",
}


def load_plan():
    if not PLAN_PATH.exists():
        return []
    return json.loads(PLAN_PATH.read_text())


def save_plan(plan):
    plan.sort(key=lambda b: b["start"])
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n")


def parse_time(s):
    return datetime.strptime(s, "%H:%M").strftime("%H:%M")


def current_block(plan, now=None):
    now = (now or datetime.now()).strftime("%H:%M")
    for b in plan:
        if b["start"] <= now < b["end"]:
            return b
    return None


def next_block(plan, now=None):
    now = (now or datetime.now()).strftime("%H:%M")
    upcoming = [b for b in plan if b["start"] > now]
    return upcoming[0] if upcoming else None


def emit(args, data, text):
    print(json.dumps(data, ensure_ascii=False) if args.json else text)


def cmd_now(args):
    plan = load_plan()
    cur, nxt = current_block(plan), next_block(plan)
    data = {"current": cur, "next": nxt, "reminder": REMINDERS[cur["type"]] if cur else None}
    if cur:
        text = f"[{cur['type']}] {cur['title']} ({cur['start']}-{cur['end']})\n{data['reminder']}"
    else:
        text = "No block right now."
    if nxt:
        text += f"\nNext: {nxt['start']} [{nxt['type']}] {nxt['title']}"
    emit(args, data, text)


def cmd_hook(args):
    """Claude Code UserPromptSubmit hook: stdout is added to the model's context."""
    plan = load_plan()
    if not plan:
        return
    cur, nxt = current_block(plan), next_block(plan)
    now = datetime.now().strftime("%H:%M")
    lines = [f"[TI] It is {now}."]
    if cur:
        lines.append(f"Current block: [{cur['type']}] {cur['title']} until {cur['end']}.")
        if cur["type"] == "focus":
            lines.append(
                "The user planned to be focused on this. If the request is clearly unrelated "
                "to it, briefly point that out and ask if they want to proceed anyway; "
                "never refuse. Otherwise help normally."
            )
    else:
        lines.append("No block scheduled right now.")
    if nxt:
        lines.append(f"Next: {nxt['start']} [{nxt['type']}] {nxt['title']}.")
    print(" ".join(lines))


def read_active():
    """Focused window written by the GNOME extension, or None if unavailable."""
    try:
        return json.loads(runtime_file("active.json").read_text())
    except (OSError, ValueError):
        return None


def load_rules():
    if RULES_PATH.exists():
        return json.loads(RULES_PATH.read_text())
    return DEFAULT_RULES


def classify(block, act, rules):
    """'on' (on the line), 'off' (drifting) or 'neutral' (not enforced / no window)."""
    if not block or block["type"] not in rules or not act or not act.get("app"):
        return "neutral"
    r = rules[block["type"]]
    app, text = act["app"], f"{act['app']} {act.get('title', '')}"
    if any(re.search(p, text, re.I) for p in r.get("deny", [])):
        return "off"
    allow = r.get("allow", [])
    if allow and not any(re.search(p, app, re.I) for p in allow):
        return "off"
    return "on"


def log_sample(block, state, act):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    rec = {"t": datetime.now().isoformat(timespec="seconds"), "block": block["start"] if block else None,
           "title": block["title"] if block else None, "state": state,
           "app": act.get("app") if act else None, "win": act.get("title") if act else None}
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def cmd_check(args):
    """Classify the current window against the current block (what watch does each tick)."""
    block, act = current_block(load_plan()), read_active()
    state = classify(block, act, load_rules())
    emit(args, {"state": state, "block": block, "active": act},
         f"{state}  ({act['app'] if act else 'no window data'})  block: {block['title'] if block else 'none'}")


def score_rows():
    today = datetime.now().strftime("%Y-%m-%d")
    stats = {}
    if LOG_PATH.exists():
        for line in LOG_PATH.read_text().splitlines():
            rec = json.loads(line)
            if not rec["t"].startswith(today) or rec["state"] == "neutral":
                continue
            s = stats.setdefault((rec["block"], rec["title"]), {"on": 0, "off": 0})
            s[rec["state"]] += 1
    rows = []
    for (start, title), s in sorted(stats.items()):
        total = s["on"] + s["off"]
        rows.append({"block": start, "title": title, "on_line_pct": round(100 * s["on"] / total), "samples": total})
    return rows


def cmd_score(args):
    rows = score_rows()
    text = "\n".join(f"{r['block']} {r['title']}: {r['on_line_pct']}% on the line" for r in rows) or "No enforced time logged today."
    emit(args, rows, text)


def cmd_active(args):
    act = read_active()
    if act is None:
        sys.exit("No active-window data. Is the TI GNOME extension enabled? (needs re-login on Wayland)")
    emit(args, act, f"{act['app'] or '(none)'}: {act['title']}")


def cmd_plan(args):
    plan = load_plan()
    text = "\n".join(f"{b['start']}-{b['end']}  [{b['type']}] {b['title']}" for b in plan) or "Plan is empty."
    emit(args, plan, text)


def add_block(start, end, type_, title):
    """Validate and store a block. Raises ValueError with a user-facing message."""
    try:
        start, end = parse_time(start), parse_time(end)
    except ValueError:
        raise ValueError("times must look like 09:30")
    title = (title or "").strip()
    if not title or len(title) > 80:
        raise ValueError("give the block a title (max 80 characters)")
    if type_ not in BLOCK_TYPES:
        raise ValueError(f"type must be one of: {', '.join(BLOCK_TYPES)}")
    if start >= end:
        raise ValueError("start must be before end")
    plan = load_plan()
    for b in plan:
        if start < b["end"] and b["start"] < end:
            raise ValueError(f"overlaps with {b['start']}-{b['end']} {b['title']}")
    plan.append({"start": start, "end": end, "type": type_, "title": title})
    save_plan(plan)
    return start, end


def remove_block(start):
    plan = load_plan()
    kept = [b for b in plan if b["start"] != parse_time(start)]
    if len(kept) == len(plan):
        raise ValueError("no block starts at that time")
    save_plan(kept)


def cmd_add(args):
    try:
        start, end = add_block(args.start, args.end, args.type, args.title)
    except ValueError as e:
        sys.exit(str(e))
    print(f"Added {start}-{end} [{args.type}] {args.title}")


def cmd_remove(args):
    try:
        remove_block(args.start)
    except ValueError as e:
        sys.exit(str(e))
    print("Removed.")


def cmd_clear(args):
    save_plan([])
    print("Plan cleared.")


def runtime_file(name):
    return Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000")) / "ti" / name


def read_state():
    """Live state published by the watcher, or None if absent/stale (>20s)."""
    try:
        s = json.loads(runtime_file("state.json").read_text())
    except (OSError, ValueError):
        return None
    return s if time.time() - s["ts"] <= 20 else None


def publish_state(state):
    """Atomically write the live state the GNOME extension renders."""
    path = runtime_file("state.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False))
    os.replace(tmp, path)


def cmd_demo(args):
    """Play a scripted run through every on-screen state. Stop `watch` first."""
    block = {"start": "09:00", "end": "11:00", "type": "focus", "title": "Study"}
    nxt = {"start": "11:00", "end": "11:15", "type": "break", "title": "Walk"}
    steps = [  # (seconds to hold, state, level, app, what you should see)
        (3, "on", 0, "ghostty", "green pill in the top bar"),
        (9, "on", 0, "ghostty", "'NEW STRETCH' banner"),
        (6, "off", 1, "steam", "amber banner: OFF THE LINE"),
        (6, "off", 2, "steam", "red banner"),
        (12, "off", 3, "steam", "full-screen BACK TO THE LINE (try the I'M BACK button)"),
        (5, "on", 0, "ghostty", "back on the line, everything clears"),
    ]
    other = {**block, "title": "Warm-up"}
    print("TI demo. Ctrl+C to stop.")
    for i, (hold, state, level, app, expect) in enumerate(steps):
        print(f"-> {expect}")
        start = time.time()
        while time.time() - start < hold:
            publish_state({
                "ts": time.time(), "state": state, "level": level,
                "drift_since": start if state == "off" else None,
                "block": other if i == 0 else block, "next": nxt, "app": app, "win": "demo",
            })
            time.sleep(1)


def watch_loop(thresholds, tick):
    """Log on/off-line time and publish state (drives the on-screen UI). Never returns."""
    drift_since, last_key = None, object()
    while True:
        try:
            plan = load_plan()
            cur, act = current_block(plan), read_active()
            state = classify(cur, act, load_rules())
            log_sample(cur, state, act)
            key = (cur["start"], cur["title"]) if cur else None
            if key != last_key or state != "off":
                drift_since = None
            if state == "off" and drift_since is None:
                drift_since = time.time()
            last_key = key
            drifted = time.time() - drift_since if drift_since else 0
            level = sum(drifted >= t for t in thresholds) if state == "off" else 0
            publish_state({
                "ts": time.time(), "state": state, "level": level, "drift_since": drift_since,
                "block": cur, "next": next_block(plan),
                "app": act.get("app") if act else None, "win": act.get("title") if act else None,
            })
        except Exception as e:  # a bad rules file must not kill the watcher
            print(f"TI watch error: {e}", file=sys.stderr)
        time.sleep(tick)


def cmd_watch(args):
    print("TI watching. Ctrl+C to stop.")
    watch_loop([args.t1, args.t2, args.t3], args.tick)


UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"


def validate_rules(data):
    """Rules must be {block_type: {"allow": [regex], "deny": [regex]}}; raises ValueError."""
    if not isinstance(data, dict):
        raise ValueError("rules must be an object")
    out = {}
    for btype, r in data.items():
        if btype not in BLOCK_TYPES or not isinstance(r, dict):
            raise ValueError(f"unknown block type: {btype}")
        out[btype] = {}
        for kind in ("allow", "deny"):
            pats = r.get(kind, [])
            if not isinstance(pats, list) or not all(isinstance(p, str) for p in pats):
                raise ValueError(f"{btype}.{kind} must be a list of text patterns")
            for p in pats:
                try:
                    re.compile(p)
                except re.error as e:
                    raise ValueError(f"bad pattern '{p}': {e}")
            out[btype][kind] = [p for p in pats if p.strip()]
    return out


def overview():
    plan = load_plan()
    live = read_state()
    return {
        "now": datetime.now().strftime("%H:%M"),
        "plan": plan, "current": current_block(plan), "next": next_block(plan),
        "live": live, "watcher": live is not None,
        "active": read_active(), "score": score_rows(),
        "rules": load_rules(), "custom_rules": RULES_PATH.exists(),
    }


class UIHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _host_ok(self):
        return self.headers.get("Host", "").rsplit(":", 1)[0] in ("127.0.0.1", "localhost")

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        path = self.path.split("?")[0]
        if path == "/":
            return self._send(200, UI_PATH.read_bytes(), "text/html")
        if path == "/api/overview":
            return self._send(200, overview())
        self._send(404, {"error": "not found"})

    def do_POST(self):
        # The custom header forces a CORS preflight, which we never grant, so other websites can't write.
        if not self._host_ok() or self.headers.get("X-TI") != "1":
            return self._send(403, {"error": "forbidden"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n > 65536:
                raise ValueError("request too large")
            body = json.loads(self.rfile.read(n) or b"{}")
            path = self.path.split("?")[0]
            if path == "/api/add":
                add_block(body.get("start"), body.get("end"), body.get("type"), body.get("title"))
            elif path == "/api/remove":
                remove_block(body.get("start"))
            elif path == "/api/clear":
                save_plan([])
            elif path == "/api/rules":
                RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
                RULES_PATH.write_text(json.dumps(validate_rules(body), indent=2) + "\n")
            elif path == "/api/rules/reset":
                RULES_PATH.unlink(missing_ok=True)
            else:
                return self._send(404, {"error": "not found"})
        except (ValueError, TypeError) as e:
            return self._send(400, {"error": str(e)})
        self._send(200, {"ok": True})


def cmd_ui(args):
    """Open the TI control panel in a browser and run the watcher alongside it."""
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), UIHandler)
    except OSError as e:
        sys.exit(f"Can't use port {args.port}: {e}")
    if read_state() is None:
        threading.Thread(target=watch_loop, args=([args.t1, args.t2, args.t3], args.tick), daemon=True).start()
        print("Watcher started.")
    else:
        print("A watcher is already running; using it.")
    url = f"http://127.0.0.1:{args.port}/"
    print(f"TI control panel: {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    p = argparse.ArgumentParser(prog="ti", description=__doc__)
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("now").set_defaults(fn=cmd_now)
    sub.add_parser("plan").set_defaults(fn=cmd_plan)
    sub.add_parser("hook").set_defaults(fn=cmd_hook)
    sub.add_parser("active").set_defaults(fn=cmd_active)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    sub.add_parser("demo").set_defaults(fn=cmd_demo)
    u = sub.add_parser("ui", help="open the control panel (also runs the watcher)")
    u.add_argument("--port", type=int, default=8787)
    u.add_argument("--no-browser", action="store_true")
    u.add_argument("--tick", type=int, default=5, help="seconds between checks")
    u.add_argument("--t1", type=int, default=60)
    u.add_argument("--t2", type=int, default=180)
    u.add_argument("--t3", type=int, default=300)
    u.set_defaults(fn=cmd_ui)
    sub.add_parser("score").set_defaults(fn=cmd_score)
    a = sub.add_parser("add")
    a.add_argument("start", help="HH:MM")
    a.add_argument("end", help="HH:MM")
    a.add_argument("type", choices=BLOCK_TYPES)
    a.add_argument("title")
    a.set_defaults(fn=cmd_add)
    r = sub.add_parser("remove")
    r.add_argument("start", help="start time of block to remove")
    r.set_defaults(fn=cmd_remove)
    sub.add_parser("clear").set_defaults(fn=cmd_clear)
    w = sub.add_parser("watch")
    w.add_argument("--tick", type=int, default=5, help="seconds between checks")
    w.add_argument("--t1", type=int, default=60, help="seconds off-line before 1st nudge")
    w.add_argument("--t2", type=int, default=180, help="seconds off-line before 2nd nudge")
    w.add_argument("--t3", type=int, default=300, help="seconds off-line before urgent nudge")
    w.set_defaults(fn=cmd_watch)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
