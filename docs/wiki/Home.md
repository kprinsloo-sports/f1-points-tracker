# F1 Points Tracker

Tracks driver and constructor points after every Formula 1 Grand Prix and shows how the
championship builds up over a season, on a public dashboard that updates itself.

- **Dashboard:** https://kprinsloo-sports.github.io/f1-points-tracker/
- **Repository:** https://github.com/kprinsloo-sports/f1-points-tracker
- **Status:** 2026 is a test run. 2027 is the first season tracked for real.

---

## How it works

```
F1DB (github.com/f1db/f1db)
        │  every day at 06:47 UTC
        ▼
update.py  ──►  data/<season>/*.csv, *.json  ──►  commit to main
                                                   │
                                                   ▼
                                     GitHub Pages dashboard (index.html)
```

1. A GitHub Actions workflow runs `update.py` once a day.
2. `update.py` downloads the season's results from F1DB and rebuilds the whole season from scratch.
3. If anything changed (a new race, or a correction such as a steward penalty), the new data is
   committed to `data/<season>/`. On days with no new results nothing is committed.
4. The workflow then republishes the dashboard to GitHub Pages.

F1DB usually publishes results within a few days of a race, so the dashboard normally catches up
within a day or two of each race weekend.

## Data source: F1DB

[F1DB](https://github.com/f1db/f1db) is an open, community-maintained Formula 1 database stored as
YAML files on GitHub. The tracker reads, for the chosen season:

| F1DB file (per race) | Used for |
|---|---|
| `race.yml` | Round number, date, Grand Prix, whether it is a sprint weekend |
| `race-results.yml` | Grand Prix finishing positions, points, retirements |
| `sprint-race-results.yml` | Sprint positions and points (sprint weekends only) |
| `qualifying-results.yml` | Qualifying positions |
| `fastest-laps.yml` | Fastest lap of the race |
| `pit-stops.yml` | Number of pit stops and pit-lane times |
| `driver-standings.yml`, `constructor-standings.yml` | Official championship totals, used as a cross-check |

It also reads F1DB's driver, constructor and Grand Prix lists for names.

**Cross-check against official standings.** After each round, `update.py` compares its own running
totals with F1DB's official standings. If they disagree it uses the official figure and prints a
reconciliation warning.

## The dashboard

The page at https://kprinsloo-sports.github.io/f1-points-tracker/ has a **season picker** at the top
and a Drivers / Constructors view. It shows:

- **Headline tiles**: drivers' leader, gap to P2, constructors' leader, and the next race (or "Season complete").
- **Cumulative points after each Grand Prix**: one line per driver or team, in team colours.
- **Standings** table after the latest round.
- **Season stats**: wins, podiums, qualifying, positions gained, retirements, fastest laps and pit stops.
- **Grand Prix points vs sprint points**: how much of each total came from sprints.
- **Finishing position in every Grand Prix**: a grid of results race by race.
- **Retirements by cause**.
- **Fastest laps and fastest pit stops, race by race**.

Pit stop times are F1DB's pit-lane times (entry to exit), not stationary time.

New seasons appear in the season picker on their own as soon as they have data.

## Data files

Everything lives under `data/`, one folder per season:

| File | What it holds |
|---|---|
| `data/seasons.json` | List of seasons with data, newest first (feeds the season picker) |
| `data/<season>/driver_points.csv` | One row per driver per round: race and sprint points, positions, cumulative points, standing, qualifying, grid, retirement, fastest lap, pit stops |
| `data/<season>/constructor_points.csv` | One row per team per round: race and sprint points, cumulative points, standing |
| `data/<season>/season.json` | Full rebuilt season, including a content hash and generation time |
| `data/<season>/changelog.json` | One entry per run that changed something: new rounds and any corrections to earlier rounds |
| `data/<season>/dash_drivers.json`, `dash_constructors.json`, `dash_rounds.json` | Ready-made tables the dashboard reads |

The CSV files open directly in Excel if you want to do your own analysis.

## The daily update (GitHub Actions)

The workflow is `.github/workflows/update.yml`, named **Update F1 tracker**.

- **Schedule:** every day at 06:47 UTC.
- **Run it by hand:** Actions tab → **Update F1 tracker** → **Run workflow**. Leave the season box
  empty for the current year, or type a year (for example `2026`) to rebuild that season.
- **What it does:** runs `update.py`, commits `data/` if it changed (as `github-actions[bot]`, message
  "Update F1 points data"), then builds and deploys the Pages site.

One-time settings (already done): **Settings → Pages → Build and deployment → Source: GitHub Actions**.

## Running it on your own PC

`update.py` needs only standard Python 3 (no extra packages). Git is optional.

```
python update.py          # current year
python update.py 2026     # a specific season
```

- **With git installed** it does a small sparse clone of F1DB into a `.f1db` cache folder.
- **Without git** it downloads just the files it needs from GitHub over HTTPS.
- PyYAML is used if it is installed, otherwise a built-in reader handles F1DB's YAML.
- Set the `F1DB_CACHE` environment variable to put the cache somewhere else.

This works on Windows (tested with Python 3.15, no git, no PyYAML). Results are written to
`data/<season>/` next to the script. Running it locally does not update the website; only the
GitHub Actions run does that.

Every run rebuilds the whole season, so running it again is always safe.

## Corrections and penalties

Because each run rebuilds the season from F1DB, a later change (a time penalty, a disqualification,
a points correction) is picked up automatically. Any change to an earlier round's points is recorded
in `changelog.json` with the old and new values.

## Things to know

- **Winter break.** GitHub pauses scheduled workflows in a repository with no commits for 60 days.
  GitHub emails a warning first. If it is paused, open **Actions → Update F1 tracker → Enable
  workflow** before the first race of the new season.
- **Team colours** are set in `TEAM_COLORS` at the top of `update.py`. A new team without a colour
  shows in grey; add its F1DB constructor id there.
- **Delays** come from F1DB: if a race is missing a day or two after the weekend, F1DB has not
  published it yet.

## Plans for 2027

2026 is a test run of the full pipeline. For 2027:

- No setup is needed: from 1 January the daily run builds the current year automatically, and 2027
  appears in the season picker once F1DB has data for it.
- Until F1DB adds the 2027 season, the daily run stops with "No F1DB data for season 2027 yet" and shows
  as failed in the Actions tab. That is expected and harmless; the dashboard keeps showing 2026.
- Before the first race, check the workflow is still enabled (see the winter break note) and add
  colours for any new teams.
- 2026 stays available in the season picker for comparison.
