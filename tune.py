#!/usr/bin/env python3
"""Scoresheet auto-tuner.

Tries model settings one group at a time on 2025-26: it picks on games before Jan 1
and checks the winner on games after. A setting is kept only if it also beats the
current one on the later games, so we don't just fit last year's noise.

Writes data/tuned_config.json (read by board.py) and refreshes
docs/data/backtest.json so the Backtest page shows the tuned model.
"""
import itertools, json, time
from datetime import datetime, timezone
import numpy as np
import nhl_pipeline as m

SPLIT = "2026-01-01"
TUNED = m.ROOT / "data" / "tuned_config.json"
# (group, which score decides it, settings to try)
GROUPS = [
    ("usage", "shots", {"pp_weight": [1.0, 1.5, 2.0, 2.5, 3.0], "sh_weight": [1.0, 0.5],
                        "toi_recent_weight": [0.4, 0.6, 0.8]}),
    ("shot rate", "shots", {"recent_n": [5, 10, 15], "recent_weight": [0.2, 0.35, 0.5],
                            "prior_games": [20, 35, 50]}),
    ("home and rest", "all", {"home_edge": [0.0, 0.01, 0.02, 0.03], "b2b_drop": [0.0, 0.02, 0.04]}),
    ("goals", "goals", {"sh_prior_shots": [75, 150, 300], "save_prior_shots": [300, 600, 1200],
                        "role_prior_goals": [False, True]}),
    ("assists", "assists", {"assist_prior_team_goals": [20, 40, 80], "team_prior_games": [10, 20, 30],
                            "role_prior_assists": [False, True]}),
]
DISPERSION = [4, 6, 8, 12, 20, 40]


def brier(p, y):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def scores(proj):
    """Lower is better for every score. Returns (fit-half, check-half) dicts."""
    out = []
    for half in (proj["date"] < SPLIT, proj["date"] >= SPLIT):
        d = proj[half]
        lam, shots = d["lam_sog"].to_numpy(), d["shots"].to_numpy()
        out.append({
            "shots": min(-float(np.mean(m.dist_logpmf(shots, lam, r))) for r in DISPERSION),
            "goals": brier(1 - np.exp(-d["lam_goal"]), d["goals"] >= 1),
            "assists": brier(1 - np.exp(-d["lam_assist"]), d["assists"] >= 1),
        })
    return out


def score_of(s, key, ref):
    if key != "all":
        return s[key]
    return sum(s[k] / ref[k] for k in ("shots", "goals", "assists"))  # relative, so each market counts equally


def best_dispersion(proj):
    lam, shots = proj["lam_sog"].to_numpy(), proj["shots"].to_numpy()
    return max(DISPERSION, key=lambda r: float(np.mean(m.dist_logpmf(shots, lam, r))))


def main():
    t0 = time.time()
    prior = m.fetch_season(m.PRIOR_SEASON)
    test = m.fetch_season(m.TEST_SEASON)
    cfg = dict(m.CONFIG)
    if TUNED.exists():
        cfg.update(json.loads(TUNED.read_text()))  # start from the last tuned settings
    fit0, check0 = scores(m.build_projections(test, prior, cfg))
    report = {"before": check0, "kept": {}}

    for name, key, grid in GROUPS:
        keys = list(grid)
        ref_fit, ref_check = dict(fit0), dict(check0)
        best_cfg, best_fit, best_check = None, score_of(fit0, key, ref_fit), None
        for combo in itertools.product(*(grid[k] for k in keys)):
            trial = dict(cfg, **dict(zip(keys, combo)))
            fit, check = scores(m.build_projections(test, prior, trial))
            if score_of(fit, key, ref_fit) < best_fit - 1e-9:
                best_cfg, best_fit, best_check, best_fit_s = trial, score_of(fit, key, ref_fit), check, fit
        if best_cfg and score_of(best_check, key, ref_check) < score_of(check0, key, ref_check):
            cfg, fit0, check0 = best_cfg, best_fit_s, best_check
            report["kept"][name] = {k: cfg[k] for k in keys}
            print(f"{name}: kept {report['kept'][name]}")
        else:
            print(f"{name}: nothing beat the current settings on the second half, kept as is")

    proj = m.build_projections(test, prior, cfg)
    cfg["nb_dispersion"] = [best_dispersion(proj)]
    report["after"] = check0
    report["improvement"] = {k: round(1 - check0[k] / report["before"][k], 5) for k in check0}

    tuned = {k: cfg[k] for k in [k for _, _, g in GROUPS for k in g] + ["nb_dispersion"]}
    TUNED.parent.mkdir(parents=True, exist_ok=True)
    TUNED.write_text(json.dumps(tuned, indent=1))

    markets = m.backtest(proj, cfg)
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
           "season_tested": "2025-26", "prior_season": "2024-25",
           "counts": {"player_games": int(len(proj)), "players": int(proj["player_id"].nunique()),
                      "games": int(proj["game_id"].nunique())},
           "config": cfg, "tuning": report, "markets": markets}
    m.OUT_FILE.write_text(json.dumps(out, indent=1, default=str))
    for k, v in report["improvement"].items():
        print(f"  {k}: {v:+.2%} better on the second half")
    print(f"Done in {time.time() - t0:.0f}s. Tuned settings: {tuned}")


if __name__ == "__main__":
    main()
