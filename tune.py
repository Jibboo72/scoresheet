#!/usr/bin/env python3
"""Scoresheet auto-tuner.

Tries different model settings on 2025-26, choosing on games before Jan 1 and
checking the winners on games after. A setting is only kept if it also beats
the current setup on the later games, so we don't just fit last year's noise.

Writes data/tuned_config.json (read by board.py) and refreshes
docs/data/backtest.json so the Backtest page shows the tuned model.
"""
import itertools, json, time
from datetime import datetime, timezone
import numpy as np
import nhl_pipeline as m

SPLIT = "2026-01-01"
TUNED = m.ROOT / "data" / "tuned_config.json"
GRIDS = {
    "shots": {"recent_n": [5, 10, 15], "recent_weight": [0.2, 0.35, 0.5, 0.65],
              "prior_games": [10, 20, 35], "toi_recent_weight": [0.4, 0.6, 0.8]},
    "goals": {"sh_prior_shots": [75, 150, 300], "save_prior_shots": [300, 600, 1200]},
    "assists": {"assist_prior_team_goals": [20, 40, 80], "team_prior_games": [5, 10, 20]},
}
DISPERSION = [4, 6, 8, 12, 20]


def brier(p, y):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def scores(proj):
    """Lower is better for every score. Returns (fit-half, check-half) dicts."""
    out = []
    for half in (proj["date"] < SPLIT, proj["date"] >= SPLIT):
        d = proj[half]
        lam, shots = d["lam_sog"].to_numpy(), d["shots"].to_numpy()
        sog = min(-float(np.mean(m.dist_logpmf(shots, lam, r))) for r in DISPERSION)
        out.append({
            "shots": sog,
            "goals": brier(1 - np.exp(-d["lam_goal"]), d["goals"] >= 1),
            "assists": brier(1 - np.exp(-d["lam_assist"]), d["assists"] >= 1),
        })
    return out


def best_dispersion(proj):
    lam, shots = proj["lam_sog"].to_numpy(), proj["shots"].to_numpy()
    return max(DISPERSION, key=lambda r: float(np.mean(m.dist_logpmf(shots, lam, r))))


def main():
    t0 = time.time()
    prior = m.fetch_season(m.PRIOR_SEASON)
    test = m.fetch_season(m.TEST_SEASON)
    cfg = dict(m.CONFIG)
    fit0, check0 = scores(m.build_projections(test, prior, cfg))
    report = {"before": check0}

    for market, grid in GRIDS.items():
        keys = list(grid)
        best_cfg, best_fit = None, fit0[market]
        for combo in itertools.product(*(grid[k] for k in keys)):
            trial = dict(cfg, **dict(zip(keys, combo)))
            fit, check = scores(m.build_projections(test, prior, trial))
            if fit[market] < best_fit:
                best_cfg, best_fit, best_check = trial, fit[market], check
        # keep the winner only if it also holds up on the second half
        if best_cfg and best_check[market] < check0[market]:
            cfg, fit0, check0 = best_cfg, scores(m.build_projections(test, prior, best_cfg))[0], best_check
            print(f"{market}: kept {dict((k, cfg[k]) for k in keys)}")
        else:
            print(f"{market}: no setting beat the current one on the second half, kept as is")

    proj = m.build_projections(test, prior, cfg)
    cfg["nb_dispersion"] = [best_dispersion(proj)]
    report["after"] = check0
    report["improvement"] = {k: round(1 - check0[k] / report["before"][k], 5) for k in check0}

    tuned = {k: cfg[k] for k in [k for g in GRIDS.values() for k in g] + ["nb_dispersion"]}
    TUNED.parent.mkdir(parents=True, exist_ok=True)
    TUNED.write_text(json.dumps(tuned, indent=1))

    markets = m.backtest(proj, cfg)
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
           "season_tested": "2025-26", "prior_season": "2024-25",
           "counts": {"player_games": int(len(proj)), "players": int(proj["player_id"].nunique()),
                      "games": int(proj["game_id"].nunique())},
           "config": cfg, "tuning": report, "markets": markets}
    m.OUT_FILE.write_text(json.dumps(out, indent=1))
    for k, v in report["improvement"].items():
        print(f"  {k}: {v:+.2%} better on the second half")
    print(f"Done in {time.time() - t0:.0f}s. Tuned settings: {tuned}")


if __name__ == "__main__":
    main()
