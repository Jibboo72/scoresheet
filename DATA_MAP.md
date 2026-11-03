# Scoresheet (NHL props) — data map

Master map of every betting app and how they connect:
[`callsheet-data/DATA_MAP.md`](https://github.com/Jibboo72/callsheet-data/blob/main/DATA_MAP.md).
Update both when a file or link changes.

The app is served by GitHub Pages from `docs/` (`jibboo72.github.io/scoresheet/`).

## What this repo publishes (`docs/data/`)

| File | What's in it | Written by | When (UTC cron) | Read by |
|---|---|---|---|---|
| `board.json` | Tonight's board: games, players, goalies, markets (SOG, goals, assists), odds status | `board.py` (tonight.yml, secret `ODDS_API_KEY`) | 13:00, 16:00, 19:00 daily | `board.html` / `board.js`, **SportsMF** |
| `sim_log.json` | Simulated results log | `sim.py` (tonight.yml) | with the board | `sim.js`, `structures.js` |
| `calib/YYYY-MM-DD.json` | Daily calibration snapshot | tonight.yml | with the board | history |
| `backtest.json` | Model backtest | `tune.py` (tune.yml) / `nhl_pipeline.py` (backtest.yml) | manual | `app.js` |

**SportsMF depends on `docs/data/board.json`** — keep the path and the
top-level keys (`date`, `games`, `players`, `goalies`, `markets`) stable.

## Working data (`data/`, not served)

`games_*.csv`, `games_v2_*.csv` (game logs), `goalies_v2_*.csv`,
`tuned_config.json` (model settings from `tune.py`).

## Sources

NHL APIs (`api-web.nhle.com`, `api.nhle.com/stats`) and The Odds API (prices).

## Note

There is a stray `github/workflows/` folder (no leading dot) next to
`.github/workflows/`. GitHub only runs the dotted one.
