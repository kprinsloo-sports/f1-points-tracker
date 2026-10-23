# F1 Points Tracker

Driver and constructor points after every Grand Prix, rebuilt from [F1DB](https://github.com/f1db/f1db)
and shown as a public web page.

## How it runs

- `.github/workflows/update.yml` runs every day at 06:47 UTC. It runs `update.py`, commits any new
  results into `data/<season>/`, and republishes the web page. Days with no new results change nothing.
- `index.html` is the dashboard. It reads `data/seasons.json` and `data/<season>/dash_*.json`, so a new
  season (for example 2027) appears in the season picker on its own.
- To run it by hand: **Actions** tab → **Update F1 tracker** → **Run workflow**. You can type a season
  (e.g. `2026`) to rebuild an older year.

## One-time settings

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. Run the workflow once from the **Actions** tab. The page address appears on the run's summary,
   usually `https://<your-username>.github.io/<repo-name>/`.

## Good to know

- GitHub pauses scheduled workflows in a repo with no commits for 60 days, which can happen in the
  winter break. GitHub emails a warning first; if it gets paused, open **Actions → Update F1 tracker →
  Enable workflow** before the first race.
- You can still run `python update.py` on your own PC; it only needs standard Python.
