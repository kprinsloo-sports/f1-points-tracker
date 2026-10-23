#!/usr/bin/env python3
"""F1 points tracker: rebuild one season's per-round and cumulative points from F1DB.

Usage:  python3 update.py [SEASON]          (defaults to the current year)

Source: F1DB (https://github.com/f1db/f1db), pulled with a sparse git checkout when
git is installed, otherwise downloaded file by file. Needs only standard Python.
Every run rebuilds the whole season from source, so it is idempotent: re-running
after a steward penalty or a points correction simply produces corrected data.
Changes versus the previous run are appended to data/<season>/changelog.json.
"""
import csv, datetime, hashlib, json, os, re, shutil, subprocess, sys
import urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

try:
    import yaml
except ImportError:  # PyYAML is optional; F1DB's files are simple enough for the reader below.
    yaml = None

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.environ.get("F1DB_CACHE", os.path.join(HERE, ".f1db"))
REPO = "https://github.com/f1db/f1db.git"

# Team colours, keyed by F1DB constructorId. Unknown teams fall back to grey.
TEAM_COLORS = {
    "mercedes": "#27B9AD", "ferrari": "#E8002D", "mclaren": "#FF8000",
    "red-bull": "#3671C6", "racing-bulls": "#8FA8FF", "aston-martin": "#229971",
    "alpine": "#FF87BC", "williams": "#64C4FF", "haas": "#B6BABD",
    "audi": "#52E252", "cadillac": "#C9A227", "kick-sauber": "#52E252", "rb": "#8FA8FF",
}


def sh(*args, cwd=None):
    try:
        subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as e:
        sys.exit(f"'{' '.join(args)}' failed:\n{e.stderr.strip()}")


def sync_git(season):
    paths = [f"src/data/seasons/{season}", "src/data/drivers", "src/data/constructors", "src/data/grands-prix"]
    if not os.path.isdir(os.path.join(CACHE, ".git")):
        sh("git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", REPO, CACHE)
    else:
        sh("git", "fetch", "--depth", "1", "origin", "main", cwd=CACHE)
        sh("git", "reset", "--hard", "origin/main", cwd=CACHE)
    sh("git", "sparse-checkout", "set", *paths, cwd=CACHE)
    return CACHE, subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=CACHE, text=True).strip()


def fetch(url, accept=None):
    """GET a URL; returns bytes, or None on 404."""
    req = urllib.request.Request(url, headers={"User-Agent": "f1-points-tracker", **({"Accept": accept} if accept else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def sync_http(season):
    """Download just the files the tracker reads, straight from GitHub (no git needed)."""
    api = "https://api.github.com/repos/f1db/f1db"
    commit = fetch(f"{api}/commits/main", "application/vnd.github.sha").decode().strip()
    raw = f"https://raw.githubusercontent.com/f1db/f1db/{commit}/src/data"
    listing = fetch(f"{api}/contents/src/data/seasons/{season}/races?ref={commit}")
    if listing is None:
        sys.exit(f"No F1DB data for season {season} yet")
    folders = [e["name"] for e in json.loads(listing) if e["type"] == "dir"]

    root = os.path.join(CACHE, "http")
    if os.path.isdir(root):
        shutil.rmtree(root)  # start clean so files F1DB removed don't linger

    def get(rel):
        data = fetch(f"{raw}/{rel}")
        if data is not None:
            path = os.path.join(root, "src", "data", *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        return data

    names = ["race.yml", "race-results.yml", "sprint-race-results.yml", "driver-standings.yml", "constructor-standings.yml",
             "qualifying-results.yml", "fastest-laps.yml", "pit-stops.yml"]
    with ThreadPoolExecutor(8) as pool:
        got = dict(zip(
            [(f, n) for f in folders for n in names],
            pool.map(get, [f"seasons/{season}/races/{f}/{n}" for f in folders for n in names])))
        gps, drv, con = set(), set(), set()
        for (folder, name), data in got.items():
            if data is None:
                continue
            text = data.decode("utf-8")
            if name == "race.yml":
                gps.update(re.findall(r"^grandPrixId:\s*(\S+)", text, re.M))
            elif name in ("race-results.yml", "sprint-race-results.yml"):
                drv.update(re.findall(r"driverId:\s*(\S+)", text))
                con.update(re.findall(r"constructorId:\s*(\S+)", text))
        meta = [f"grands-prix/{g}.yml" for g in gps] + [f"drivers/{d}.yml" for d in drv] + [f"constructors/{c}.yml" for c in con]
        list(pool.map(get, meta))
    return root, commit


def sync_source(season):
    return sync_git(season) if shutil.which("git") else sync_http(season)


def _scalar(v):
    v = v.strip()
    if v in ("", "~", "null"):
        return None
    if v[0] == '"':
        return json.loads(v)
    if v[0] == "'":
        return v[1:-1].replace("''", "'")
    if v in ("true", "false"):
        return v == "true"
    if re.fullmatch(r"[-+]?\d+", v):
        return int(v)
    if re.fullmatch(r"[-+]?\d*\.\d+", v):
        return float(v)
    return v


def _parse(lines, i, ind):
    """Block-style YAML (maps, lists, scalars) starting at lines[i], indented by ind."""
    out = [] if lines[i][1].startswith("-") else {}
    while i < len(lines) and lines[i][0] == ind:
        text = lines[i][1]
        if isinstance(out, list):
            if not text.startswith("-"):
                break
            item = text[1:].strip()
            if not item:
                val, i = _parse(lines, i + 1, lines[i + 1][0])
            elif re.match(r"[^\s\"']+:(\s|$)", item):
                # "- key: value" starts a map whose keys sit two columns in.
                lines[i] = (ind + 2, item)
                val, i = _parse(lines, i, ind + 2)
            else:
                val, i = _scalar(item), i + 1
            out.append(val)
        else:
            if text.startswith("-"):
                break
            key, _, rest = text.partition(":")
            i += 1
            if rest.strip():
                out[key.strip()] = _scalar(rest)
            elif i < len(lines) and (lines[i][0] > ind or (lines[i][0] == ind and lines[i][1].startswith("-"))):
                out[key.strip()], i = _parse(lines, i, lines[i][0])
            else:
                out[key.strip()] = None
    return out, i


def parse_yaml(text):
    lines = [(len(l) - len(l.lstrip(" ")), l.strip()) for l in text.splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    return _parse(lines, 0, lines[0][0])[0] if lines else None


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        text = f.read()
    data = yaml.safe_load(text) if yaml else parse_yaml(text)
    return data or default


def seconds(t):
    """'23.062' or '1:01.177' -> seconds as a float."""
    if t is None:
        return None
    m, _, s = str(t).rpartition(":")
    return round((int(m) * 60 if m else 0) + float(s), 3)


def build(season, root, commit):
    base = os.path.join(root, "src", "data")
    sdir = os.path.join(base, "seasons", str(season))
    rdir = os.path.join(sdir, "races")
    if not os.path.isdir(rdir):
        sys.exit(f"No F1DB data for season {season} yet")

    rounds, drows, crows, warnings = [], [], [], []
    drivers, constructors = {}, {}
    dcum, ccum = {}, {}

    for folder in sorted(os.listdir(rdir)):
        f = os.path.join(rdir, folder)
        race = load(os.path.join(f, "race.yml"), {})
        gp = load(os.path.join(base, "grands-prix", f"{race['grandPrixId']}.yml"), {})
        results = load(os.path.join(f, "race-results.yml"))
        sprint = load(os.path.join(f, "sprint-race-results.yml"))
        has_sprint = sprint is not None or bool(race.get("sprintRaceDate"))
        done = results is not None
        rounds.append({
            "round": race["round"], "gpId": race["grandPrixId"],
            "name": gp.get("fullName", race["grandPrixId"]), "short": gp.get("shortName", race["grandPrixId"]),
            "abbr": gp.get("abbreviation", race["grandPrixId"][:3].upper()),
            "date": str(race["date"]), "sprint": has_sprint, "completed": done,
        })
        if not done:
            continue
        rnd = race["round"]

        # Points scored this weekend, per driver (attributed to the team they drove for).
        wk = {}
        for kind, rows in (("race", results), ("sprint", sprint or [])):
            for r in rows:
                d = wk.setdefault(r["driverId"], {"constructorId": r["constructorId"], "race": 0, "sprint": 0,
                                                  "racePos": None, "sprintPos": None, "grid": None, "retired": None})
                d[kind] += r.get("points") or 0
                d[f"{kind}Pos"] = r.get("position") or r.get("positionText")
                if kind == "race":
                    d["constructorId"] = r["constructorId"]
                    # "PL" = started from the pit lane, i.e. behind everyone on the grid.
                    g = r.get("gridPosition")
                    d["grid"] = len(results) if g == "PL" else g
                    d["retired"] = r.get("reasonRetired")
                drivers.setdefault(r["driverId"], None)
                constructors.setdefault(r["constructorId"], None)

        # Qualifying, fastest lap and pit stops. Pit stop times are F1DB's pit lane time (entry to exit).
        quali = {q["driverId"]: q.get("position") for q in load(os.path.join(f, "qualifying-results.yml"), [])}
        laps = load(os.path.join(f, "fastest-laps.yml"), [])
        fastest = next((l["driverId"] for l in laps if l.get("position") == 1), None)
        pits = {}
        for p in load(os.path.join(f, "pit-stops.yml"), []):
            if seconds(p.get("time")) is not None:
                pits.setdefault(p["driverId"], []).append(seconds(p["time"]))

        dstand = {s["driverId"]: s for s in load(os.path.join(f, "driver-standings.yml"), [])}
        cstand = {s["constructorId"]: s for s in load(os.path.join(f, "constructor-standings.yml"), [])}

        cwk = {}
        for did, d in wk.items():
            pts = d["race"] + d["sprint"]
            dcum[did] = dcum.get(did, 0) + pts
            c = cwk.setdefault(d["constructorId"], {"race": 0, "sprint": 0})
            c["race"] += d["race"]; c["sprint"] += d["sprint"]
        # Drivers who sat this round out keep their cumulative total on the trend line.
        for did in list(dcum):
            if did not in wk:
                wk[did] = None
        for did, d in wk.items():
            st = dstand.get(did, {})
            official = st.get("points")
            if official is not None and abs(official - dcum[did]) > 1e-9:
                warnings.append(f"R{rnd} {did}: computed {dcum[did]} vs official {official}; using official")
                dcum[did] = official
            drows.append({
                "round": rnd, "driverId": did,
                "constructorId": d["constructorId"] if d else None,
                "racePoints": d["race"] if d else 0, "sprintPoints": d["sprint"] if d else 0,
                "points": (d["race"] + d["sprint"]) if d else 0,
                "racePos": d["racePos"] if d else None, "sprintPos": d["sprintPos"] if d else None,
                "cumulative": dcum[did], "standing": st.get("position"), "started": d is not None,
                "qualiPos": quali.get(did), "grid": d["grid"] if d else None,
                "retired": d["retired"] if d else None, "fastestLap": did == fastest,
                "pitStops": len(pits.get(did, [])), "pitBest": min(pits[did]) if pits.get(did) else None,
                "pitTotal": round(sum(pits[did]), 3) if pits.get(did) else None,
            })
        for cid in sorted(set(ccum) | set(cwk)):
            c = cwk.get(cid, {"race": 0, "sprint": 0})
            ccum[cid] = ccum.get(cid, 0) + c["race"] + c["sprint"]
            st = cstand.get(cid, {})
            official = st.get("points")
            if official is not None and abs(official - ccum[cid]) > 1e-9:
                warnings.append(f"R{rnd} {cid}: computed {ccum[cid]} vs official {official}; using official")
                ccum[cid] = official
            crows.append({
                "round": rnd, "constructorId": cid, "racePoints": c["race"], "sprintPoints": c["sprint"],
                "points": c["race"] + c["sprint"], "cumulative": ccum[cid], "standing": st.get("position"),
            })

    for did in drivers:
        m = load(os.path.join(base, "drivers", f"{did}.yml"), {})
        drivers[did] = {"id": did, "name": m.get("name", did), "abbr": m.get("abbreviation", did[:3].upper()),
                        "number": m.get("permanentNumber"), "nationality": m.get("nationalityCountryId")}
    for cid in constructors:
        m = load(os.path.join(base, "constructors", f"{cid}.yml"), {})
        constructors[cid] = {"id": cid, "name": m.get("name", cid), "color": TEAM_COLORS.get(cid, "#888888")}
    # A driver's current team is the team of their most recent start.
    for r in drows:
        if r["constructorId"]:
            drivers[r["driverId"]]["team"] = r["constructorId"]

    return {
        "season": season,
        "source": {"name": "F1DB", "url": "https://github.com/f1db/f1db", "commit": commit},
        "rounds": rounds, "drivers": list(drivers.values()), "constructors": list(constructors.values()),
        "driverRounds": drows, "constructorRounds": crows, "warnings": warnings,
    }


def diff(old, new):
    """Point changes for rounds that existed in the previous run (i.e. corrections)."""
    if not old:
        return []
    key = lambda r: (r["round"], r.get("driverId") or r.get("constructorId"))
    out = []
    for table in ("driverRounds", "constructorRounds"):
        prev = {key(r): r for r in old.get(table, [])}
        for r in new[table]:
            p = prev.get(key(r))
            if p and (p["points"], p["cumulative"]) != (r["points"], r["cumulative"]):
                out.append({"round": r["round"], "id": key(r)[1], "table": table,
                            "points": [p["points"], r["points"]], "cumulative": [p["cumulative"], r["cumulative"]]})
    return out


def dashboard_rows(data):
    """Flat, denormalised rows for the dashboard: one per entity per completed round."""
    rnd = {r["round"]: r for r in data["rounds"]}
    drv = {d["id"]: d for d in data["drivers"]}
    con = {c["id"]: c for c in data["constructors"]}

    def enrich(rows, entity):
        out, wins, pods = [], {}, {}
        for r in sorted(rows, key=lambda r: (r["round"], r["standing"] or 99)):
            eid = r[entity]
            lead = max(x["cumulative"] for x in rows if x["round"] == r["round"])
            row = {"round": r["round"], "gp": rnd[r["round"]]["abbr"], "gpName": rnd[r["round"]]["short"],
                   "date": rnd[r["round"]]["date"], "sprintWeekend": rnd[r["round"]]["sprint"]}
            if entity == "driverId":
                d = drv[eid]
                tid = r["constructorId"] or d.get("team")
                p = r["racePos"] if isinstance(r["racePos"], int) else None
                wins[eid] = wins.get(eid, 0) + (p == 1)
                pods[eid] = pods.get(eid, 0) + (p is not None and p <= 3)
                row.update({"driverId": eid, "driver": d["name"], "abbr": d["abbr"],
                            "teamId": tid, "team": con[tid]["name"], "color": con[tid]["color"],
                            "racePos": r["racePos"], "raced": r["started"],
                            "sprintPos": r["sprintPos"], "wins": wins[eid], "podiums": pods[eid],
                            "qualiPos": r["qualiPos"], "grid": r["grid"],
                            "gained": r["grid"] - p if p is not None and isinstance(r["grid"], int) else None,
                            "retired": r["retired"], "fastestLap": r["fastestLap"],
                            "pitStops": r["pitStops"], "pitBest": r["pitBest"], "pitTotal": r["pitTotal"]})
            else:
                row.update({"teamId": eid, "team": con[eid]["name"], "color": con[eid]["color"]})
            row.update({"racePoints": r["racePoints"], "sprintPoints": r["sprintPoints"], "points": r["points"],
                        "cumulative": r["cumulative"], "standing": r["standing"],
                        "gapToLeader": lead - r["cumulative"]})
            out.append(row)
        return out

    rounds = [{"round": r["round"], "gp": r["abbr"], "gpName": r["short"], "name": r["name"], "date": r["date"],
               "sprintWeekend": r["sprint"], "completed": r["completed"]} for r in data["rounds"]]
    return enrich(data["driverRounds"], "driverId"), enrich(data["constructorRounds"], "constructorId"), rounds


def write_csv(path, rows):
    if not rows:  # a new season before its first race
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)


def write_season_index():
    """data/seasons.json lists every season that has data, newest first, for the web page."""
    root = os.path.join(HERE, "data")
    seasons = sorted((int(n) for n in os.listdir(root)
                      if n.isdigit() and os.path.exists(os.path.join(root, n, "dash_rounds.json"))), reverse=True)
    with open(os.path.join(root, "seasons.json"), "w", encoding="utf-8") as f:
        json.dump(seasons, f)


def main():
    season = int(sys.argv[1]) if len(sys.argv) > 1 else datetime.date.today().year
    root, commit = sync_source(season)
    data = build(season, root, commit)

    out = os.path.join(HERE, "data", str(season))
    os.makedirs(out, exist_ok=True)
    jpath = os.path.join(out, "season.json")
    old = json.load(open(jpath, encoding="utf-8")) if os.path.exists(jpath) else None

    body = json.dumps({k: v for k, v in data.items()}, sort_keys=True)
    digest = hashlib.sha256(body.encode()).hexdigest()[:12]
    if old and old.get("contentHash") == digest:
        print(f"{season}: no changes (source {commit[:8]})")
        return
    data["contentHash"] = digest
    data["generatedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    changes = diff(old, data)
    new_rounds = sorted({r["round"] for r in data["driverRounds"]} - {r["round"] for r in (old or {}).get("driverRounds", [])})
    log_path = os.path.join(out, "changelog.json")
    log = json.load(open(log_path, encoding="utf-8")) if os.path.exists(log_path) else []
    log.append({"at": data["generatedAt"], "commit": commit, "newRounds": new_rounds, "corrections": changes})

    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=1)
    write_csv(os.path.join(out, "driver_points.csv"), data["driverRounds"])
    write_csv(os.path.join(out, "constructor_points.csv"), data["constructorRounds"])
    for name, rows in zip(("dash_drivers", "dash_constructors", "dash_rounds"), dashboard_rows(data)):
        with open(os.path.join(out, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(rows, f, separators=(",", ":"))

    write_season_index()

    done = [r for r in data["rounds"] if r["completed"]]
    print(f"{season}: {len(done)}/{len(data['rounds'])} rounds, new rounds {new_rounds or 'none'}, "
          f"{len(changes)} corrections, {len(data['warnings'])} reconciliation warnings")
    for w in data["warnings"]:
        print("  warn:", w)


if __name__ == "__main__":
    main()
