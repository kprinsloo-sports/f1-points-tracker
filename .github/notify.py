"""Writes the notification text for a dashboard refresh to stdout.

Reads the latest entry of data/<season>/changelog.json plus season.json, so it
must run after update.py has written new data.
"""
import datetime
import json
import os
import sys

season = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else str(datetime.date.today().year)
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", season)
data = json.load(open(os.path.join(out, "season.json"), encoding="utf-8"))
entry = json.load(open(os.path.join(out, "changelog.json"), encoding="utf-8"))[-1]
page = os.environ.get("PAGE_URL") or "https://kprinsloo-sports.github.io/f1-points-tracker/"

rounds = {r["round"]: r for r in data["rounds"]}
drivers = {d["id"]: d["name"] for d in data["drivers"]}
teams = {c["id"]: c["name"] for c in data["constructors"]}
done = [r for r in data["rounds"] if r["completed"]]

lines = [f"**{season} dashboard refreshed** ({len(done)}/{len(data['rounds'])} rounds complete)", ""]
if entry["newRounds"]:
    lines.append("New results: " + ", ".join(
        f"R{n} {rounds[n]['name']}" + (" (sprint weekend)" if rounds[n]["sprint"] else "") for n in entry["newRounds"]))
else:
    lines.append("No new races; existing results or stats were updated.")
if entry["corrections"]:
    lines.append(f"{len(entry['corrections'])} corrections to earlier rounds.")

if done:
    last = done[-1]["round"]
    top = lambda rows: sorted((r for r in rows if r["round"] == last), key=lambda r: r["standing"])[:3]
    lines += ["", f"Standings after R{last} {rounds[last]['name']}:"]
    lines.append("Drivers: " + ", ".join(f"{r['standing']}. {drivers[r['driverId']]} {r['cumulative']:g}"
                                         for r in top(data["driverRounds"])))
    lines.append("Constructors: " + ", ".join(f"{r['standing']}. {teams[r['constructorId']]} {r['cumulative']:g}"
                                              for r in top(data["constructorRounds"])))

lines += ["", f"Dashboard: {page}"]
print("\n".join(lines))
