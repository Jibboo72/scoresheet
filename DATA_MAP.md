# Scoresheet (NHL props) — data map

Master map of every betting app and how they connect:
[`callsheet-data/DATA_MAP.md`](https://github.com/Jibboo72/callsheet-data/blob/main/DATA_MAP.md).
Update both when a file or link changes.

The app is served by GitHub Pages from `docs/` (`jibboo72.github.io/scoresheet/`).

## What this repo publishes (`docs/data/`)

| File | What's in it | Written by | When (UTC cron) | Read by |
|---|---|---|---|---|
| `board.json` | Tonight's board: games, players, goalies, markets (SOG, goals, assists), odds status | `board.py` (tonight.yml; odds only if repo variable `USE_ODDS` = true, using secret `ODDS_API_KEY`) | 13:00, 16:00, 19:00 daily (with odds off every run rebuilds the board; with odds on only the first run of the day) | `board.html` / `board.js`, **SportsMF** |
| `sim_log.json` | Simulated results log | `sim.py` (tonight.yml) | with the board | `sim.js`, `structures.js` |
| `calib/YYYY-MM-DD.json` | Daily calibration snapshot | tonight.yml | with the board | history |
| `backtest.json` | Model backtest | `tune.py` (tune.yml) / `nhl_pipeline.py` (backtest.yml) | manual | `app.js` |

**SportsMF depends on `docs/data/board.json`** — keep the path and the
top-level keys (`date`, `games`, `players`, `goalies`, `markets`) stable.

## Working data (`data/`, not served)

`games_*.csv`, `games_v2_*.csv` (game logs), `goalies_v2_*.csv`,
`tuned_config.json` (model settings from `tune.py`).

## Sources

NHL APIs (`api-web.nhle.com`, `api.nhle.com/stats`) and The Odds API (prices; off since Nov 6, 2026, so the credits go to Buckets. Flip repo variable `USE_ODDS` to true to turn back on).

With odds off, `board.json` is model-only: every player gets an `assist` market and `sog1.5` with `p` and `fair`, but no `price`, `book`, `ev` or `likely`, and games carry no market total. SportsMF's NHL Props tab shows those as model chance and fair odds with "no price".

## Note

There is a stray `github/workflows/` folder (no leading dot) next to
`.github/workflows/`. GitHub only runs the dotted one.
